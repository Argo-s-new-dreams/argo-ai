@echo off
rem Doppio clic per disinstallare Argo su Windows: chiede conferma e propone un backup prima di cancellare.
rem Con Argo installato si puo' anche usare Impostazioni > App installate > Argo AI > Disinstalla.
set "SCRIPT=%~dp0app\disinstallatore\disinstalla_windows.ps1"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0disinstalla_windows.ps1"
if not exist "%SCRIPT%" (
  echo Non trovo disinstalla_windows.ps1: usa la cartella completa di Argo ^(argo-ai-main^) oppure
  echo Impostazioni ^> App ^> App installate ^> Argo AI ^> Disinstalla.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%SCRIPT%'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
pause
