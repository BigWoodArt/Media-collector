@echo off
cd /d "%~dp0app"
python -c "import PIL" >nul 2>&1 || python -m pip install --quiet -r requirements.txt
where pythonw >nul 2>&1
if errorlevel 1 (
    python collector.pyw
    if errorlevel 1 pause
) else (
    start "" pythonw collector.pyw
)
