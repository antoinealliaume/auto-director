@echo off
setlocal
title Auto Director V9.2 - Installation Worker PC
echo.
echo ==============================================
echo   AUTO DIRECTOR V9.2 STYLE - WORKER PC 2.8
echo ==============================================
echo.
set "PS1=%TEMP%\Install-AutoDirector.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Headers @{'Cache-Control'='no-cache'} 'https://auto-director-web.onrender.com/static/Install-AutoDirector.ps1?v=2.8' -OutFile (Join-Path $env:TEMP 'Install-AutoDirector.ps1')"
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
echo Mise a jour V9.2 terminee. Retourne sur Auto Director.
timeout /t 4 /nobreak >nul
