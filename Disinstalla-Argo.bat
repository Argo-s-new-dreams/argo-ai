@echo off
rem Doppio clic per disinstallare Argo su Windows: chiede conferma e propone un backup prima di cancellare.
rem Cerca lo script nella cartella installer (pacchetto completo) oppure accanto a questo file (file scaricati sciolti).
set "SCRIPT=%~dp0installer\disinstalla_windows.ps1"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0disinstalla_windows.ps1"
if not exist "%SCRIPT%" (
  echo Non trovo disinstalla_windows.ps1: mettilo nella stessa cartella di questo file oppure nella sottocartella installer.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%SCRIPT%'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
pause
