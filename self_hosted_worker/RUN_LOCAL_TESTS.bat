@echo off
setlocal
cd /d "%~dp0.."
echo ==============================================
echo   Auto Director - Tests worker local
echo ==============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python introuvable.
  pause
  exit /b 1
)
python -m unittest tests.test_adaptive_profile -v
set ERR=%ERRORLEVEL%
echo.
if "%ERR%"=="0" (
  echo Tous les tests du profil adaptatif sont OK.
) else (
  echo Un test a echoue.
)
pause
exit /b %ERR%
