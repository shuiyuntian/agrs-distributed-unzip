@echo off
cd /d "%~dp0.."

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo.
echo Starting Master Server...
echo URL: http://localhost:8000
echo Dashboard: http://localhost:8000/dashboard
echo.
python master/main.py
pause
