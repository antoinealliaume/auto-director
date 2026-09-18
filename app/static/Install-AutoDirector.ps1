$ErrorActionPreference = 'Stop'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'AutoDirector'
$RepoRoot = Join-Path $InstallRoot 'repo'
$ZipUrl = 'https://github.com/antoinealliaume/auto-director/archive/refs/heads/main.zip?v=2.6'
$TempZip = Join-Path $env:TEMP 'auto-director-main.zip'
$TempExtract = Join-Path $env:TEMP ('auto-director-install-' + [guid]::NewGuid().ToString('N'))
$ExpectedAgentVersion = [version]'2.6'
$AgentStatusUrl = 'http://127.0.0.1:8765/status'
$AgentStopUrl = 'http://127.0.0.1:8765/stop'

function Test-RealPython([string]$Path) {
  if (-not $Path -or -not (Test-Path $Path)) { return $false }
  $old=$ErrorActionPreference;$ErrorActionPreference='Continue'
  try { & $Path -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)" 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
  catch { return $false }
  finally { $ErrorActionPreference=$old }
}
function Resolve-RealPython {
  $candidates = New-Object System.Collections.Generic.List[string]
  foreach($p in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),(Join-Path $env:ProgramFiles 'Python313\python.exe'),(Join-Path $env:ProgramFiles 'Python312\python.exe'),(Join-Path $env:ProgramFiles 'Python311\python.exe'))){if($p){$candidates.Add($p)}}
  try{Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python') -Directory -ErrorAction SilentlyContinue|Sort-Object Name -Descending|ForEach-Object{$p=Join-Path $_.FullName 'python.exe';if(Test-Path $p){$candidates.Add($p)}}}catch{}
  try{$cmd=Get-Command python.exe -ErrorAction SilentlyContinue;if($cmd -and $cmd.Source -and $cmd.Source -notmatch '\\WindowsApps\\'){$candidates.Add($cmd.Source)}}catch{}
  foreach($p in $candidates){if(Test-RealPython $p){return $p}}
  try{$py=Get-Command py.exe -ErrorAction SilentlyContinue;if($py){foreach($selector in @('-3.13','-3.12','-3.11','-3')){$old=$ErrorActionPreference;$ErrorActionPreference='Continue';try{$resolved=& $py.Source $selector -c "import sys; print(sys.executable)" 2>$null;if($LASTEXITCODE -eq 0 -and $resolved){$path=([string]($resolved|Select-Object -Last 1)).Trim();if(Test-RealPython $path){return $path}}}catch{}finally{$ErrorActionPreference=$old}}}}catch{}
  return $null
}
function Stop-PreviousAutoDirector {
  Write-Host 'Arrêt de l ancien agent/worker...' -ForegroundColor Cyan
  try{Invoke-RestMethod -Method Post -Uri $AgentStopUrl -ContentType 'application/json' -Body '{}' -TimeoutSec 3|Out-Null}catch{}
  try{$agents=Get-CimInstance Win32_Process|Where-Object{$_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'local_agent\.ps1'};foreach($p in $agents){try{Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop}catch{}}}catch{}
  Start-Sleep -Milliseconds 900
}
function Wait-ForAgent {
  $deadline=[DateTime]::UtcNow.AddSeconds(18);$lastVersion=$null
  while([DateTime]::UtcNow -lt $deadline){try{$status=Invoke-RestMethod -Method Get -Uri $AgentStatusUrl -TimeoutSec 2;if($status.agentVersion){$lastVersion=[string]$status.agentVersion;try{if([version]$lastVersion -ge $ExpectedAgentVersion){return $status}}catch{}}}catch{};Start-Sleep -Milliseconds 650}
  if($lastVersion){throw "Ancien agent encore actif (version $lastVersion). Redémarre Windows puis relance cet installateur."};throw 'Le nouvel agent Auto Director ne répond pas sur le port local 8765.'
}

Write-Host '=== Auto Director V9.1 Quality - installation / mise a jour du worker PC ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallRoot|Out-Null
$PythonExe=Resolve-RealPython
if(-not $PythonExe){
  Write-Host 'Python réel 3.12 absent. Installation automatique...' -ForegroundColor Yellow;$winget=Get-Command winget.exe -ErrorAction SilentlyContinue
  if(-not $winget){throw 'Python 3.12 est requis et winget n est pas disponible sur ce PC.'}
  $old=$ErrorActionPreference;$ErrorActionPreference='Continue';try{& $winget.Source install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements;$wingetCode=$LASTEXITCODE}finally{$ErrorActionPreference=$old}
  if($wingetCode -ne 0 -and $wingetCode -ne -1978335189){throw 'Installation automatique de Python 3.12 impossible.'}
  $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User');Start-Sleep -Seconds 2;$PythonExe=Resolve-RealPython
  if(-not $PythonExe){throw 'Python a été installé mais reste introuvable. Redémarre Windows puis relance cet installateur.'}
}
Write-Host "Python valide: $PythonExe" -ForegroundColor Green
Stop-PreviousAutoDirector
Write-Host 'Téléchargement de Auto Director V9.1 Quality...' -ForegroundColor Cyan
Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing -Headers @{'Cache-Control'='no-cache'}
if(Test-Path $TempExtract){Remove-Item $TempExtract -Recurse -Force};New-Item -ItemType Directory -Force -Path $TempExtract|Out-Null;Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
$Source=Join-Path $TempExtract 'auto-director-main';if(-not(Test-Path $Source)){throw 'Archive Auto Director invalide.'}
if(Test-Path $RepoRoot){$Backup=Join-Path $InstallRoot 'repo.previous';if(Test-Path $Backup){Remove-Item $Backup -Recurse -Force};Move-Item $RepoRoot $Backup};Move-Item $Source $RepoRoot
$Agent=Join-Path $RepoRoot 'self_hosted_worker\local_agent.ps1';$Runner=Join-Path $RepoRoot 'self_hosted_worker\run_worker_logged.ps1';if(-not(Test-Path $Agent)){throw 'Agent local introuvable dans le package.'};if(-not(Test-Path $Runner)){throw 'Runner worker introuvable dans le package.'}
[Environment]::SetEnvironmentVariable('AUTO_DIRECTOR_PYTHON',$PythonExe,'User');$env:AUTO_DIRECTOR_PYTHON=$PythonExe
$StartupDir=[Environment]::GetFolderPath('Startup');$StartupCmd=Join-Path $StartupDir 'AutoDirectorLocalAgent.cmd';$cmd="@echo off`r`nset `"AUTO_DIRECTOR_PYTHON=$PythonExe`"`r`nstart `"Auto Director Local Agent`" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Agent`"`r`n";Set-Content -Path $StartupCmd -Value $cmd -Encoding ASCII
Write-Host 'Démarrage du nouvel agent...' -ForegroundColor Cyan
$psi=New-Object System.Diagnostics.ProcessStartInfo;$psi.FileName='powershell.exe';$psi.Arguments="-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Agent`"";$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.EnvironmentVariables['AUTO_DIRECTOR_PYTHON']=$PythonExe;$proc=[System.Diagnostics.Process]::Start($psi);if(-not $proc){throw 'Impossible de démarrer le nouvel agent.'};$status=Wait-ForAgent
try{Remove-Item $TempZip -Force -ErrorAction SilentlyContinue}catch{};try{Remove-Item $TempExtract -Recurse -Force -ErrorAction SilentlyContinue}catch{}
Write-Host '';Write-Host ("Installation V9.1 terminée. Agent PC version "+$status.agentVersion+" actif.") -ForegroundColor Green;Write-Host 'Le Quality Engine installera automatiquement ses composants au premier démarrage si ton PC le permet.' -ForegroundColor Green;Write-Host 'Retourne dans Auto Director puis clique sur Démarrer le worker PC.' -ForegroundColor Green;Write-Host 'Aucun secret PostgreSQL/Redis n est envoyé au PC.' -ForegroundColor DarkGray;Start-Sleep -Seconds 4
