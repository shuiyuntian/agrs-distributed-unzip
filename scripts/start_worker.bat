@echo off
cd /d "%~dp0.."

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

set /p MASTER_URL="Enter Master URL (default: http://localhost:8000): "
if "%MASTER_URL%"=="" set MASTER_URL=http://localhost:8000

echo.
echo Starting Worker, connecting to: %MASTER_URL%
echo.
python worker/worker.py --master %MASTER_URL%
pause
