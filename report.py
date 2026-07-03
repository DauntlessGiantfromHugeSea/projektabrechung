"""
Wochenbericht erzeugen: Intervalle auf einen Zeitraum + ein Projekt filtern,
pro Mitarbeiter summieren und als Text/HTML aufbereiten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

import activities
import config
import manual
from events import (Interval, OpenPunch, load_records, normalize,
                    open_punches, pair_intervals)


def _punches():
    return [p for p in (normalize(r) for r in load_records()) if p is not None]


def collect_intervals(include_no_project: bool = False) -> list[Interval]:
    """Alle Arbeitsintervalle: Webhook-Buchungen (ohne ausgeblendete) plus
    manuell hinzugefuegte/korrigierte Eintraege. Zentrale Datenquelle fuer
    Bericht, Log und Detailansicht.

    include_no_project=True liefert auch Buchungen OHNE Projekt mit --
    z. B. damit Mitarbeiter ihnen nachtraeglich ein Projekt zuweisen koennen."""
    hidden = manual.hidden_ids()
    ivs = [iv for iv in pair_intervals(_punches()) if iv.id not in hidden]
    ivs += manual.to_intervals()
    if config.REQUIRE_PROJECT and not include_no_project:
        ivs = [iv for iv in ivs if (iv.project or "").strip()]
    desc = activities.mapping()
    for iv in ivs:
        if iv.id in desc:
            iv.description = desc[iv.id]
    return ivs


def collect_open(include_no_project: bool = False) -> list[OpenPunch]:
    """Offene Stempelungen (eingestempelt, noch nicht ausgestempelt)."""
    opens = open_punches(_punches())
    if config.REQUIRE_PROJECT and not include_no_project:
        opens = [o for o in opens if (o.project or "").strip()]
    return opens


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


def detail_sessions(start: datetime, end: datetime,
                    project: str | None = None) -> list[Interval]:
    """Einzelne Arbeitsintervalle im Zeitraum (optional auf ein Projekt
    gefiltert), chronologisch -- fuer die Detailansicht mit Kommt/Geht."""
    wanted = (project if project is not None else config.PROJECT_CODE).strip()
    start = start.astimezone(config.TIMEZONE)
    end = end.astimezone(config.TIMEZONE)
    out: list[Interval] = []
    for iv in collect_intervals():
        if not (start <= iv.start.astimezone(config.TIMEZONE) < end):
            continue
        if not _project_matches(iv.project, wanted):
            continue
        out.append(iv)
    out.sort(key=lambda iv: iv.start)
    return out


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_attachment(start: datetime, end: datetime, projects: list[str],
                     fmt: str, name: str) -> tuple[bytes, str, str]:
    """Bericht-Datei je Format erzeugen -> (bytes, dateiname, mime)."""
    import csvout
    import xlsxout
    ivs = scope_intervals(start, end, projects)
    safe = (name or "bericht").replace("/", "_").replace(" ", "_")[:50]
    stamp = start.astimezone(config.TIMEZONE).strftime("%Y%m%d")
    if fmt == "csv":
        return (csvout.arcadis_csv(ivs), f"{safe}_{stamp}.csv",
                "text/csv; charset=utf-8")
    return (xlsxout.intervals_xlsx(ivs, title=name), f"{safe}_{stamp}.xlsx",
            _XLSX_MIME)


def scope_intervals(start: datetime, end: datetime,
                    projects: list[str]) -> list[Interval]:
    """Detail-Intervalle im Zeitraum, gefiltert auf eine Projektliste
    (Teilstring, beliebiges Match). Leere Liste = alle Projekte."""
    start = start.astimezone(config.TIMEZONE)
    end = end.astimezone(config.TIMEZONE)
    wanted = [w.lower() for w in projects if w.strip()]
    out: list[Interval] = []
    for iv in collect_intervals():
        if not (start <= iv.start.astimezone(config.TIMEZONE) < end):
            continue
        if wanted:
            low = (iv.project or "").lower()
            if not any(w in low for w in wanted):
                continue
        out.append(iv)
    return out


def filter_intervals(start: datetime | None = None, end: datetime | None = None,
                     project: str = "", employee: str = "") -> list[Interval]:
    """Alle Arbeitsintervalle, optional gefiltert nach Zeitraum, Projekt
    (Teilstring) und Mitarbeiter (Teilstring). Neueste zuerst -- fuer die
    Log-/Ansichtsseite."""
    proj = (project or "").strip().lower()
    emp = (employee or "").strip().lower()
    out: list[Interval] = []
    for iv in collect_intervals():
        ivp = iv.start.astimezone(config.TIMEZONE)
        if start and ivp < start.astimezone(config.TIMEZONE):
            continue
        if end and ivp >= end.astimezone(config.TIMEZONE):
            continue
        if proj and (not iv.project or proj not in iv.project.lower()):
            continue
        if emp and emp not in iv.employee.lower():
            continue
        out.append(iv)
    out.sort(key=lambda iv: iv.start, reverse=True)
    return out


def this_week_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Liefert (Montag 00:00, naechster Montag 00:00) der *laufenden* Woche."""
    now = (now or datetime.now(config.TIMEZONE)).astimezone(config.TIMEZONE)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_monday = today - timedelta(days=today.weekday())
    return this_monday, this_monday + timedelta(days=7)


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

    intervals = collect_intervals()

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


# --- Gruppierter Bericht (mehrere Projekte, Abschnitt je Projekt) -----------

@dataclass
class GroupedSection:
    project: str
    rows: list[ReportRow] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        return sum(r.hours for r in self.rows)


@dataclass
class GroupedReport:
    name: str
    start: datetime
    end: datetime
    projects_filter: list[str]
    sections: list[GroupedSection] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        return sum(s.total_hours for s in self.sections)

    @property
    def has_data(self) -> bool:
        return any(s.rows for s in self.sections)


def build_grouped(start: datetime, end: datetime,
                  projects: list[str], name: str = "Bericht") -> GroupedReport:
    """Bericht ueber AUSGEWAEHLTE Projekte, gruppiert nach Projekt.

    Ein Intervall zaehlt, wenn sein Projekt zu IRGENDEINEM der Filter passt
    (Teilstring, case-insensitive). Leere Projektliste => keine Daten
    (es wird absichtlich nicht "alles" einbezogen)."""
    intervals = collect_intervals()

    start = start.astimezone(config.TIMEZONE)
    end = end.astimezone(config.TIMEZONE)
    wanted = [w.lower() for w in projects if w.strip()]

    # je echtem Projektnamen -> {employee -> ReportRow}
    buckets: dict[str, dict[str, ReportRow]] = {}
    for iv in intervals:
        ivp = iv.start.astimezone(config.TIMEZONE)
        if not (start <= ivp < end):
            continue
        if not iv.project:
            continue
        low = iv.project.lower()
        if not any(w in low for w in wanted):
            continue
        emp = buckets.setdefault(iv.project, {})
        row = emp.setdefault(iv.employee, ReportRow(employee=iv.employee))
        row.sessions += 1
        row.hours += max(iv.duration_hours, 0.0)

    sections = []
    for project in sorted(buckets):
        rows = sorted(buckets[project].values(),
                      key=lambda r: r.hours, reverse=True)
        sections.append(GroupedSection(project=project, rows=rows))

    return GroupedReport(name=name, start=start, end=end,
                         projects_filter=projects, sections=sections)


def _period_label_g(rep: GroupedReport) -> str:
    last_day = rep.end - timedelta(days=1)
    return (f"KW {rep.start.isocalendar().week:02d} "
            f"({rep.start:%d.%m.%Y} - {last_day:%d.%m.%Y})")


def render_grouped_text(rep: GroupedReport) -> str:
    lines = [f"{rep.name}", f"Zeitraum: {_period_label_g(rep)}", "=" * 52]
    if not rep.has_data:
        lines += ["", "Keine Buchungen für die gewählten Projekte in diesem "
                  "Zeitraum."]
        return "\n".join(lines) + "\n"
    for s in rep.sections:
        lines += ["", f"Projekt: {s.project}", "-" * 52]
        name_w = max([len("Mitarbeiter")] + [len(r.employee) for r in s.rows])
        for r in s.rows:
            lines.append(f"{r.employee:<{name_w}}  {_fmt_hours(r.hours):>9}  "
                         f"{r.sessions:>3} Sessions")
        lines.append(f"{'Summe':<{name_w}}  {_fmt_hours(s.total_hours):>9}")
    lines += ["", "=" * 52,
              f"Gesamtsumme: {_fmt_hours(rep.total_hours)}"]
    return "\n".join(lines) + "\n"


def render_grouped_html(rep: GroupedReport) -> str:
    head = (f"<h2>{escape(rep.name)}</h2>"
            f"<p><b>Zeitraum:</b> {escape(_period_label_g(rep))}</p>")
    if not rep.has_data:
        return head + ("<p>Keine Buchungen für die gewählten Projekte in "
                       "diesem Zeitraum.</p>")
    parts = [head]
    for s in rep.sections:
        rows_html = "".join(
            f"<tr><td>{escape(r.employee)}</td>"
            f"<td style='text-align:right'>{_fmt_hours(r.hours)}</td>"
            f"<td style='text-align:right'>{r.sessions}</td></tr>"
            for r in s.rows)
        parts.append(
            f"<h3 style='margin:1rem 0 .3rem'>{escape(s.project)}</h3>"
            f"<table border='1' cellpadding='6' cellspacing='0' "
            f"style='border-collapse:collapse'>"
            f"<thead><tr style='background:#eef5e9'>"
            f"<th align='left'>Mitarbeiter</th><th>Stunden</th><th>Sessions</th>"
            f"</tr></thead><tbody>{rows_html}</tbody>"
            f"<tfoot><tr style='font-weight:bold'><td>Summe</td>"
            f"<td style='text-align:right'>{_fmt_hours(s.total_hours)}</td>"
            f"<td></td></tr></tfoot></table>")
    parts.append(f"<p style='margin-top:1rem;font-weight:bold'>Gesamtsumme: "
                 f"{_fmt_hours(rep.total_hours)}</p>")
    return "".join(parts)


def subject_grouped(rep: GroupedReport) -> str:
    return f"{config.REPORT_SUBJECT_PREFIX}: {rep.name} - {_period_label_g(rep)}"
