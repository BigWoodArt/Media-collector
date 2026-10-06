@echo off
cd /d "%~dp0"
python -c "import PIL" >nul 2>&1 || python -m pip install --quiet -r requirements.txt
where pythonw >nul 2>&1
if errorlevel 1 (
    python collector.py
    if errorlevel 1 pause
) else (
    start "" pythonw collector.pyw
)
