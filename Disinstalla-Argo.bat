@echo off
rem Doppio clic per disinstallare Argo su Windows: chiede conferma e propone un backup prima di cancellare.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0installer' -Filter disinstalla_windows.ps1 | Unblock-File"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\disinstalla_windows.ps1"
echo.
pause
