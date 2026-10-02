# E-Mail-Verteiler – Server-Betrieb hinter dem Caddy-Dienst unter /verteiler/.
# Zugriff nur über den Intranet-Login (siehe verteiler_core/auth.py).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERTEILER_MODUS=server \
    VERTEILER_DB=/data/verteiler.db \
    VERTEILER_BACKUPS=/data/backups

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin verteiler \
 && mkdir -p /data && chown verteiler:verteiler /data

COPY app.py ./
COPY verteiler_core ./verteiler_core
COPY .streamlit ./.streamlit

# Nicht als root laufen.
USER verteiler
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/verteiler/_stcore/health', timeout=4)"

# Kommandozeilen-Optionen haben Vorrang vor .streamlit/config.toml (dort: nur localhost
# für den Windows-Betrieb). Im Container lauscht Streamlit auf allen Schnittstellen;
# auf dem Host ist Port 8501 nur an 127.0.0.1 gebunden (deploy/docker-compose.yml).
CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.baseUrlPath=verteiler", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
