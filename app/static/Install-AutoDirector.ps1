$ErrorActionPreference = 'Stop'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'AutoDirector'
$RepoRoot = Join-Path $InstallRoot 'repo'
$ZipUrl = 'https://github.com/antoinealliaume/auto-director/archive/refs/heads/main.zip?v=2.1'
$TempZip = Join-Path $env:TEMP 'auto-director-main.zip'
$TempExtract = Join-Path $env:TEMP ('auto-director-install-' + [guid]::NewGuid().ToString('N'))
$ExpectedAgentVersion = [version]'2.1'
$AgentStatusUrl = 'http://127.0.0.1:8765/status'
$AgentStopUrl = 'http://127.0.0.1:8765/stop'

function Stop-PreviousAutoDirector {
  Write-Host 'Arrêt de l ancien agent/worker...' -ForegroundColor Cyan
  try { Invoke-RestMethod -Method Post -Uri $AgentStopUrl -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null } catch {}
  try {
    $agents = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'local_agent\.ps1' }
    foreach ($p in $agents) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} }
  } catch {}
  Start-Sleep -Milliseconds 900
}

function Wait-ForAgent {
  $deadline = [DateTime]::UtcNow.AddSeconds(18)
  $lastVersion = $null
  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      $status = Invoke-RestMethod -Method Get -Uri $AgentStatusUrl -TimeoutSec 2
      if ($status.agentVersion) {
        $lastVersion = [string]$status.agentVersion
        try { if ([version]$lastVersion -ge $ExpectedAgentVersion) { return $status } } catch {}
      }
    } catch {}
    Start-Sleep -Milliseconds 650
  }
  if ($lastVersion) { throw "Ancien agent encore actif (version $lastVersion). Ferme les anciens installateurs puis relance celui-ci." }
  throw 'Le nouvel agent Auto Director ne répond pas sur le port local 8765.'
}

Write-Host '=== Auto Director - installation / mise a jour du worker PC ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host 'Python 3.12 absent. Installation automatique...' -ForegroundColor Yellow
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  } else { throw 'Python 3.12 est requis et winget n est pas disponible sur ce PC.' }
}

Stop-PreviousAutoDirector

Write-Host 'Téléchargement de la dernière version...' -ForegroundColor Cyan
Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing -Headers @{ 'Cache-Control'='no-cache' }
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

Write-Host 'Démarrage du nouvel agent...' -ForegroundColor Cyan
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$Agent) -WindowStyle Hidden
$status = Wait-ForAgent

try { Remove-Item $TempZip -Force -ErrorAction SilentlyContinue } catch {}
try { Remove-Item $TempExtract -Recurse -Force -ErrorAction SilentlyContinue } catch {}

Write-Host ''
Write-Host ("Installation terminée. Agent PC version " + $status.agentVersion + " actif.") -ForegroundColor Green
Write-Host 'Retourne dans Auto Director puis clique sur « Démarrer le worker PC ».' -ForegroundColor Green
Write-Host 'En cas de problème, le Studio peut maintenant lire le journal local du démarrage.' -ForegroundColor DarkGray
Start-Sleep -Seconds 4
