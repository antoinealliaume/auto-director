@echo off
setlocal
title Auto Director - Installation Worker PC
echo.
echo ==============================================
echo   AUTO DIRECTOR - INSTALLATION DU WORKER PC
echo ==============================================
echo.
set "PS1=%TEMP%\Install-AutoDirector.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing 'https://auto-director-web.onrender.com/static/Install-AutoDirector.ps1' -OutFile '%PS1%'"
if errorlevel 1 (
  echo Echec du telechargement de l'installateur.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
if errorlevel 1 (
  echo.
  echo Installation incomplete. Regarde le message ci-dessus.
  pause
  exit /b 1
)
echo.
echo Installation terminee. Retourne sur Auto Director.
timeout /t 4 /nobreak >nul
