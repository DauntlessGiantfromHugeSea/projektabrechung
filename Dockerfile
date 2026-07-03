FROM python:3.12-slim

# DejaVu-Fonts fuer die PDF-Erzeugung (Umlaute etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Alle Python-Module der App kopieren
COPY *.py ./

# Standard-Port; per ENV ueberschreibbar
ENV PORT=8080
EXPOSE 8080

# --proxy-headers: hinter fbe-caddy korrektes Schema/Host (HTTPS-Links).
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
