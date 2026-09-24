@echo off
setlocal
goto :main

:try_python
if defined PYTHON_EXE exit /b 0
set "CANDIDATE=%~1"
if not defined CANDIDATE exit /b 0
if /I not "%CANDIDATE:\WindowsApps\=%"=="%CANDIDATE%" exit /b 0
if not exist "%CANDIDATE%" exit /b 0
"%CANDIDATE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=%CANDIDATE%"
exit /b 0

:main
cd /d "%~dp0.."
echo ==============================================
echo   Auto Director - Diagnostic materiel
echo ==============================================
echo.
set "PYTHON_EXE="
set "PYTHON_SELECTOR="
call :try_python "%~dp0..\.venv-local\Scripts\python.exe"
if defined AUTO_DIRECTOR_PYTHON call :try_python "%AUTO_DIRECTOR_PYTHON%"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try_python "%%~fD\python.exe"
for /d %%D in ("%ProgramFiles%\Python3*") do call :try_python "%%~fD\python.exe"
for /f "delims=" %%P in ('where python.exe 2^>nul') do call :try_python "%%P"
if not defined PYTHON_EXE (
  for %%S in (-3.14 -3.13 -3.12 -3.11 -3.10 -3) do (
    if not defined PYTHON_SELECTOR (
      py.exe %%S -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" >nul 2>nul
      if not errorlevel 1 set "PYTHON_SELECTOR=%%S"
    )
  )
)
if not defined PYTHON_EXE if not defined PYTHON_SELECTOR (
  echo Python ^>= 3.10 compatible avec le worker introuvable.
  echo Reinstalle le worker PC pour reparer Python automatiquement.
  echo.
  pause
  exit /b 1
)
if defined PYTHON_EXE goto run_python_exe
goto run_py_launcher

:run_python_exe
"%PYTHON_EXE%" "%~dp0detect_profile.py"
set ERR=%ERRORLEVEL%
goto diagnostic_done

:run_py_launcher
py.exe %PYTHON_SELECTOR% "%~dp0detect_profile.py"
set ERR=%ERRORLEVEL%

:diagnostic_done
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
