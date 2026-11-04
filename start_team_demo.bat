@echo off
setlocal
set "FINSHIELD_HOST=0.0.0.0"
for /f "delims=" %%I in ('powershell -NoProfile -Command "$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1; if ($route) { Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress -First 1 }"') do set "LAN_IP=%%I"
if defined LAN_IP (
    powershell -NoProfile -Command "$null = Invoke-RestMethod -Uri 'http://%LAN_IP%:5000/api/health' -TimeoutSec 2 -ErrorAction Stop"
    if not errorlevel 1 (
        echo FinShield AI is already available on this network at http://%LAN_IP%:5000/
        endlocal
        exit /b 0
    )
)
powershell -NoProfile -Command "$null = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/health' -TimeoutSec 2 -ErrorAction Stop"
if not errorlevel 1 (
    echo A local-only FinShield instance is already running on port 5000.
    echo Stop its server window, then rerun this script to enable LAN sharing.
    endlocal
    exit /b 1
)
call "%~dp0start_demo.bat"
if errorlevel 1 exit /b 1

if defined LAN_IP (
    echo Team link for devices on your private Wi-Fi/LAN: http://%LAN_IP%:5000/
) else (
    echo Could not detect your LAN IP. Run ipconfig and share the IPv4 address with port 5000.
)
echo Keep this computer and the FinShield server running while teammates use the link.
echo Do not share this link over the public internet.
endlocal
