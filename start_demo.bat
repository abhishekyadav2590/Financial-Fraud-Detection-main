@echo off
setlocal
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" || (
    echo ERROR: Could not open the project folder.
    pause
    exit /b 1
)

set "DEMO_URL=http://127.0.0.1:5000/"
set "HEALTH_URL=http://127.0.0.1:5000/api/health"
set "APP_ENV=development"
set "FLASK_DEBUG=false"
set "SESSION_COOKIE_SECURE=false"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3.12 and the Windows Python Launcher were not found.
        echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
        echo Make sure the Python Launcher is enabled, then run this file again.
        pause
        popd
        exit /b 1
    )
    py -3.12 -m venv ".venv"
    if errorlevel 1 (
        echo ERROR: Could not create the local virtual environment with Python 3.12.
        echo Check that Python 3.12 is installed by running: py -3.12 --version
        pause
        popd
        exit /b 1
    )
    set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
)

"%PYTHON%" -c "import flask, flask_login, flask_migrate, flask_sqlalchemy, flask_wtf, joblib, openpyxl, pandas, reportlab, sklearn" >nul 2>nul
if errorlevel 1 (
    echo Installing the pinned project dependencies into .venv...
    "%PYTHON%" -m pip install -r requirements.lock
    if errorlevel 1 (
        echo ERROR: Dependency installation failed. Review the pip output above.
        pause
        popd
        exit /b 1
    )
)

"%PYTHON%" -c "from config import Config; import sys; sys.exit(0 if Config.SQLALCHEMY_DATABASE_URI.startswith('sqlite:') else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: The local demo requires a SQLite DATABASE_URL.
    echo Remove the remote database override from your local .env or configure a local SQLite URL.
    echo No database was changed.
    pause
    popd
    exit /b 1
)

powershell -NoProfile -Command "$health = $null; try { $health = Invoke-RestMethod -Uri '%HEALTH_URL%' -TimeoutSec 2 } catch {}; if ($health -and $health.model_loaded -eq $true) { exit 0 }; $client = [System.Net.Sockets.TcpClient]::new(); try { $client.Connect('127.0.0.1', 5000); exit 2 } catch { exit 1 } finally { $client.Dispose() }"
if not errorlevel 1 (
    echo FinShield AI is already running and its saved model is healthy.
    echo Opening %DEMO_URL%
    start "" "%DEMO_URL%"
    popd
    exit /b 0
)
if errorlevel 2 (
    echo ERROR: Port 5000 is already occupied by a service that is not a healthy FinShield AI app.
    echo Close the other service or configure its port, then try again.
    pause
    popd
    exit /b 1
)

echo Applying pending database migrations without deleting existing records...
"%PYTHON%" -m flask --app app db upgrade
if errorlevel 1 (
    echo ERROR: Database migration failed. Existing database files were not reset.
    pause
    popd
    exit /b 1
)

echo Starting the local Flask demo...
start "FinShield AI server - close this window to stop" /D "%PROJECT_DIR%" "%PYTHON%" app.py

powershell -NoProfile -Command "$ready = $false; for ($i = 0; $i -lt 30; $i++) { try { $health = Invoke-RestMethod -Uri '%HEALTH_URL%' -TimeoutSec 2; if ($health.model_loaded -eq $true) { $ready = $true; break } } catch {}; Start-Sleep -Seconds 1 }; if ($ready) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo ERROR: The app did not become healthy within 30 seconds.
    echo Check the FinShield AI server window for the startup error.
    popd
    exit /b 1
)

echo FinShield AI is ready at %DEMO_URL%
start "" "%DEMO_URL%"
popd
exit /b 0
