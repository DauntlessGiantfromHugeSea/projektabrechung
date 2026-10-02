@echo off
REM E-Mail-Verteiler starten (Windows). Beim ersten Start wird eine
REM eigene Python-Umgebung (.venv) angelegt und pandas/streamlit installiert.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Erstinstallation, bitte warten ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Python 3 wurde nicht gefunden. Bitte von python.org installieren.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run app.py
pause
