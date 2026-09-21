@echo off
setlocal
cd /d "%~dp0.."
echo ==============================================
echo   Auto Director - Diagnostic materiel
echo ==============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python n'est pas installe ou n'est pas dans le PATH.
  echo Le worker ne sera pas lance tant que Python n'est pas disponible.
  echo.
  pause
  exit /b 1
)
python "%~dp0detect_profile.py"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Le diagnostic materiel a echoue avec le code %ERR%.
  echo Lis le message ci-dessus, puis relance ce fichier.
  echo.
  pause
  exit /b %ERR%
)
echo Le profil ci-dessus est choisi automatiquement et reste volontairement prudent.
echo Aucun gros modele n'est force si le materiel n'a pas assez de marge.
echo.
pause
exit /b %ERR%
