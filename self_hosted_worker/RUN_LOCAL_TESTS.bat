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
echo   Auto Director - Tests worker local
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
"%PYTHON_EXE%" -m unittest tests.test_adaptive_profile -v
set ERR=%ERRORLEVEL%
goto tests_done

:run_py_launcher
py.exe %PYTHON_SELECTOR% -m unittest tests.test_adaptive_profile -v
set ERR=%ERRORLEVEL%

:tests_done
echo.
if "%ERR%"=="0" (
  echo Tous les tests du profil adaptatif sont OK.
) else (
  echo Un test a echoue.
)
pause
exit /b %ERR%
