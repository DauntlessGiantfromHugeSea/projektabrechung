"""
Wochenbericht erzeugen: Intervalle auf einen Zeitraum + ein Projekt filtern,
pro Mitarbeiter summieren und als Text/HTML aufbereiten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

import config
from events import Interval, load_records, normalize, pair_intervals


@dataclass
class ReportRow:
    employee: str
    sessions: int = 0
    hours: float = 0.0


@dataclass
class Report:
    project: str            # Filter-Bezeichnung ("" = alle Projekte)
    start: datetime         # Zeitraum-Beginn (inkl.)
    end: datetime           # Zeitraum-Ende (exkl.)
    rows: list[ReportRow] = field(default_factory=list)
    projects_seen: list[str] = field(default_factory=list)
    total_intervals: int = 0  # Intervalle insgesamt im Zeitraum (vor Filter)

    @property
    def total_hours(self) -> float:
        return sum(r.hours for r in self.rows)

    @property
    def has_data(self) -> bool:
        return bool(self.rows)


def previous_week_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Liefert (Montag 00:00, naechster Montag 00:00) der *vorigen* Woche
    in der konfigurierten Zeitzone."""
    now = now or datetime.now(config.TIMEZONE)
    now = now.astimezone(config.TIMEZONE)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    return last_monday, this_monday


def _project_matches(interval_project: str | None, wanted: str) -> bool:
    if not wanted:
        return True  # kein Filter -> alles
    if interval_project is None:
        return False
    return wanted.lower() in interval_project.lower()


def build_report(start: datetime, end: datetime,
                 project: str | None = None) -> Report:
    """Bericht fuer [start, end) und optionalen Projektfilter erzeugen."""
    wanted = (project if project is not None else config.PROJECT_CODE).strip()

    records = load_records()
    punches = [p for p in (normalize(r) for r in records) if p is not None]
    intervals = pair_intervals(punches)

    start = start.astimezone(config.TIMEZONE)
    end = end.astimezone(config.TIMEZONE)

    in_window: list[Interval] = [
        iv for iv in intervals
        if start <= iv.start.astimezone(config.TIMEZONE) < end
    ]

    projects_seen = sorted({iv.project for iv in in_window if iv.project})

    agg: dict[str, ReportRow] = {}
    for iv in in_window:
        if not _project_matches(iv.project, wanted):
            continue
        row = agg.setdefault(iv.employee, ReportRow(employee=iv.employee))
        row.sessions += 1
        row.hours += max(iv.duration_hours, 0.0)

    rows = sorted(agg.values(), key=lambda r: r.hours, reverse=True)

    return Report(project=wanted, start=start, end=end, rows=rows,
                  projects_seen=projects_seen, total_intervals=len(in_window))


# --- Formatierung ----------------------------------------------------------

def _fmt_hours(h: float) -> str:
    total_minutes = round(h * 60)
    return f"{total_minutes // 60}:{total_minutes % 60:02d} h"


def _period_label(rep: Report) -> str:
    last_day = rep.end - timedelta(days=1)
    iso_week = rep.start.isocalendar().week
    return (f"KW {iso_week:02d} ({rep.start:%d.%m.%Y} - {last_day:%d.%m.%Y})")


def render_text(rep: Report) -> str:
    proj = rep.project or "alle Projekte"
    lines = [
        f"Projektzeiten - {proj}",
        f"Zeitraum: {_period_label(rep)}",
        "=" * 52,
    ]
    if not rep.has_data:
        lines.append("")
        lines.append("Keine Buchungen in diesem Zeitraum gefunden.")
        if rep.project and rep.projects_seen:
            lines.append("")
            lines.append("Im Zeitraum vorhandene Projekte (zur Kontrolle des "
                         "Filters PROJECT_CODE):")
            for p in rep.projects_seen:
                lines.append(f"  - {p}")
        elif not rep.projects_seen and rep.total_intervals:
            lines.append("")
            lines.append("Hinweis: Es gibt Buchungen, aber kein erkennbares "
                         "Projektfeld. Pruefe /report/inspect.")
        return "\n".join(lines) + "\n"

    name_w = max([len("Mitarbeiter")] + [len(r.employee) for r in rep.rows])
    lines.append(f"{'Mitarbeiter':<{name_w}}  {'Stunden':>9}  Sessions")
    lines.append("-" * (name_w + 22))
    for r in rep.rows:
        lines.append(f"{r.employee:<{name_w}}  {_fmt_hours(r.hours):>9}  "
                     f"{r.sessions:>8}")
    lines.append("-" * (name_w + 22))
    lines.append(f"{'Summe':<{name_w}}  {_fmt_hours(rep.total_hours):>9}")
    return "\n".join(lines) + "\n"


def render_html(rep: Report) -> str:
    proj = escape(rep.project or "alle Projekte")
    period = escape(_period_label(rep))
    if not rep.has_data:
        extra = ""
        if rep.project and rep.projects_seen:
            items = "".join(f"<li>{escape(p)}</li>" for p in rep.projects_seen)
            extra = (f"<p>Im Zeitraum vorhandene Projekte (Filter pr&uuml;fen):</p>"
                     f"<ul>{items}</ul>")
        return (f"<h2>Projektzeiten &ndash; {proj}</h2>"
                f"<p><b>Zeitraum:</b> {period}</p>"
                f"<p>Keine Buchungen in diesem Zeitraum gefunden.</p>{extra}")

    rows_html = "".join(
        f"<tr><td>{escape(r.employee)}</td>"
        f"<td style='text-align:right'>{_fmt_hours(r.hours)}</td>"
        f"<td style='text-align:right'>{r.sessions}</td></tr>"
        for r in rep.rows
    )
    return (
        f"<h2>Projektzeiten &ndash; {proj}</h2>"
        f"<p><b>Zeitraum:</b> {period}</p>"
        f"<table border='1' cellpadding='6' cellspacing='0' "
        f"style='border-collapse:collapse'>"
        f"<thead><tr style='background:#f0f0f0'>"
        f"<th align='left'>Mitarbeiter</th><th>Stunden</th><th>Sessions</th>"
        f"</tr></thead><tbody>{rows_html}</tbody>"
        f"<tfoot><tr style='font-weight:bold'>"
        f"<td>Summe</td><td style='text-align:right'>"
        f"{_fmt_hours(rep.total_hours)}</td><td></td></tr></tfoot>"
        f"</table>"
    )


def subject(rep: Report) -> str:
    proj = rep.project or "alle Projekte"
    return f"{config.REPORT_SUBJECT_PREFIX} {proj} - {_period_label(rep)}"
