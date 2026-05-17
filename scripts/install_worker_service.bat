@echo off
cd /d "%~dp0.."

set NSSM_PATH=nssm.exe
where nssm >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: nssm.exe not found.
    echo Please download NSSM from https://nssm.cc/download and add it to PATH.
    pause
    exit /b 1
)

set /p MASTER_URL="Enter Master URL: "
if "%MASTER_URL%"=="" (
    echo Master URL cannot be empty.
    pause
    exit /b 1
)

set SERVICE_NAME=DistUnzipWorker
set WORKER_DIR=%CD%

nssm install %SERVICE_NAME% "%WORKER_DIR%\venv\Scripts\python.exe"
nssm set %SERVICE_NAME% AppDirectory "%WORKER_DIR%"
nssm set %SERVICE_NAME% AppParameters "worker/worker.py --master %MASTER_URL%"
nssm set %SERVICE_NAME% DisplayName "Distributed Unzip Worker"
nssm set %SERVICE_NAME% Description "Distributed unzip worker node"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%WORKER_DIR%\logs\worker.log"
nssm set %SERVICE_NAME% AppStderr "%WORKER_DIR%\logs\worker.log"

mkdir logs 2>nul
nssm start %SERVICE_NAME%

echo.
echo Worker service installed and started.
echo Service name: %SERVICE_NAME%
pause
