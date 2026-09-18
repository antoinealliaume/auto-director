@echo off
setlocal
cd /d "%~dp0.."
echo ==============================================
echo   Auto Director - Worker local adaptatif
echo ==============================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_LOCAL_WORKER_WINDOWS.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Le worker s'est arrete avec le code %ERR%.
  echo Lis le message ci-dessus, puis relance ce fichier.
) else (
  echo Worker arrete proprement.
)
echo.
pause
exit /b %ERR%
