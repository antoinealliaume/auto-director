$ErrorActionPreference = 'Stop'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'AutoDirector'
$RepoRoot = Join-Path $InstallRoot 'repo'
$ZipUrl = 'https://github.com/antoinealliaume/auto-director/archive/refs/heads/main.zip'
$TempZip = Join-Path $env:TEMP 'auto-director-main.zip'
$TempExtract = Join-Path $env:TEMP ('auto-director-install-' + [guid]::NewGuid().ToString('N'))

Write-Host '=== Auto Director - installation du worker PC ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host 'Python 3.12 absent. Installation automatique...' -ForegroundColor Yellow
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  } else {
    throw 'Python 3.12 est requis et winget n est pas disponible sur ce PC.'
  }
}

Write-Host 'Téléchargement de la dernière version...' -ForegroundColor Cyan
Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing
if (Test-Path $TempExtract) { Remove-Item $TempExtract -Recurse -Force }
New-Item -ItemType Directory -Force -Path $TempExtract | Out-Null
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
$Source = Join-Path $TempExtract 'auto-director-main'
if (-not (Test-Path $Source)) { throw 'Archive Auto Director invalide.' }

if (Test-Path $RepoRoot) {
  $Backup = Join-Path $InstallRoot 'repo.previous'
  if (Test-Path $Backup) { Remove-Item $Backup -Recurse -Force }
  Move-Item $RepoRoot $Backup
}
Move-Item $Source $RepoRoot

$Agent = Join-Path $RepoRoot 'self_hosted_worker\local_agent.ps1'
if (-not (Test-Path $Agent)) { throw 'Agent local introuvable dans le package.' }

$StartupDir = [Environment]::GetFolderPath('Startup')
$StartupCmd = Join-Path $StartupDir 'AutoDirectorLocalAgent.cmd'
$cmd = "@echo off`r`nstart `"Auto Director Local Agent`" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Agent`"`r`n"
Set-Content -Path $StartupCmd -Value $cmd -Encoding ASCII

# Lance l'agent immédiatement. S'il existe déjà, la nouvelle instance quitte sans erreur.
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$Agent) -WindowStyle Hidden

try { Remove-Item $TempZip -Force -ErrorAction SilentlyContinue } catch {}
try { Remove-Item $TempExtract -Recurse -Force -ErrorAction SilentlyContinue } catch {}

Write-Host ''
Write-Host 'Installation terminée.' -ForegroundColor Green
Write-Host 'Retourne dans Auto Director puis clique sur « Démarrer le worker PC ».' -ForegroundColor Green
Write-Host 'Le petit agent démarrera automatiquement avec Windows, mais le rendu lourd reste arrêté tant que tu ne le lances pas.' -ForegroundColor DarkGray
Start-Sleep -Seconds 3
