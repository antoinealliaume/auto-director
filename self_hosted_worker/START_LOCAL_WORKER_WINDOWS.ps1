$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host '=== Auto Director PC Worker - HTTPS sécurisé ===' -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.12+ est requis.' }

$EnvFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $PSScriptRoot '.env.example') $EnvFile
  Write-Host "Configuration locale créée: $EnvFile" -ForegroundColor Green
}

function Import-EnvFile([string]$Path,[bool]$Overwrite=$true) {
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $parts=$_ -split '=',2;$key=$parts[0].Trim();$value=$parts[1].Trim()
    if ($Overwrite -or -not [Environment]::GetEnvironmentVariable($key,'Process')) { [Environment]::SetEnvironmentVariable($key,$value,'Process') }
  }
}
Import-EnvFile $EnvFile $true

$StudioUrl = if ($env:STUDIO_URL) { $env:STUDIO_URL.TrimEnd('/') } else { 'https://auto-director-web.onrender.com' }
if ($StudioUrl -ne 'https://auto-director-web.onrender.com') { throw 'STUDIO_URL non autorisée.' }

if (-not $env:WORKER_TOKEN) {
  Write-Host ''
  Write-Host "Connexion au Studio: $StudioUrl" -ForegroundColor Cyan
  $Secure=Read-Host 'Mot de passe du Studio' -AsSecureString
  $Ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { $StudioPassword=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
  if (-not $StudioPassword) { throw 'Mot de passe du Studio requis.' }
  try {
    $LoginBody=@{password=$StudioPassword}|ConvertTo-Json -Compress
    $Login=Invoke-RestMethod -Method Post -Uri "$StudioUrl/api/login" -ContentType 'application/json' -Body $LoginBody -TimeoutSec 20
    if (-not $Login.token) { throw 'Session Studio absente.' }
    $Headers=@{Authorization="Bearer $($Login.token)"}
    $Session=Invoke-RestMethod -Method Post -Uri "$StudioUrl/api/local-worker/session" -Headers $Headers -ContentType 'application/json' -Body '{"label":"windows-manual"}' -TimeoutSec 20
    if (-not $Session.workerToken) { throw 'Jeton worker absent.' }
    $env:WORKER_TOKEN=[string]$Session.workerToken
  } finally { $StudioPassword=$null;$LoginBody=$null;$Login=$null }
}

$env:STUDIO_URL=$StudioUrl;$env:REMOTE_WORKER_MODE='1';$env:WORKER_KIND='local';$env:PYTHONUNBUFFERED='1'

$AutoProfileEnabled=($env:AUTO_PROFILE -ne '0')
if($AutoProfileEnabled){python (Join-Path $PSScriptRoot 'detect_profile.py');Import-EnvFile (Join-Path $PSScriptRoot '.auto_profile.env') $true}
if(-not $env:PROFILE_NAME){$env:PROFILE_NAME='safe-unknown'}
if(-not $env:RENDER_WIDTH){$env:RENDER_WIDTH='720'};if(-not $env:RENDER_HEIGHT){$env:RENDER_HEIGHT='1280'};if(-not $env:RENDER_FPS){$env:RENDER_FPS='24'}
if(-not $env:FFMPEG_THREADS){$env:FFMPEG_THREADS='2'};if(-not $env:MOMENT_SAMPLES){$env:MOMENT_SAMPLES='5'};if(-not $env:MAX_REVISIONS){$env:MAX_REVISIONS='0'}
if(-not $env:LOCAL_TRANSCRIBE){$env:LOCAL_TRANSCRIBE='0'};if(-not $env:LOCAL_WHISPER_MODEL){$env:LOCAL_WHISPER_MODEL='tiny'};if(-not $env:LOCAL_WHISPER_THREADS){$env:LOCAL_WHISPER_THREADS='1'}

$env:OMP_NUM_THREADS=$env:FFMPEG_THREADS;$env:MKL_NUM_THREADS=$env:FFMPEG_THREADS;$env:OPENBLAS_NUM_THREADS=$env:FFMPEG_THREADS
$env:OLLAMA_NUM_PARALLEL='1';$env:OLLAMA_MAX_LOADED_MODELS='1';$env:OLLAMA_MAX_QUEUE='1';$env:OLLAMA_KEEP_ALIVE='90s'
try{[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'}catch{}

Write-Host "Profil: $env:PROFILE_NAME" -ForegroundColor Green
Write-Host "Rendu: $env:RENDER_WIDTH x $env:RENDER_HEIGHT @ $env:RENDER_FPS fps" -ForegroundColor Green
Write-Host "Charge limitée: FFmpeg=$env:FFMPEG_THREADS threads | analyse=$env:MOMENT_SAMPLES | révisions=$env:MAX_REVISIONS" -ForegroundColor Green
Write-Host ("Transcription locale: " + $(if($env:LOCAL_TRANSCRIBE -eq '1'){"$env:LOCAL_WHISPER_MODEL / $env:LOCAL_WHISPER_THREADS thread(s)"}else{'désactivée sur ce profil'})) -ForegroundColor Green
Write-Host 'Transport: HTTPS uniquement · aucun secret PostgreSQL/Redis sur le PC' -ForegroundColor Green

if(-not (Test-Path '.venv-local')){Write-Host 'Création de l environnement Python local...' -ForegroundColor Cyan;python -m venv .venv-local}
& .\.venv-local\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'Installation Python du worker impossible.'}
if($env:LOCAL_TRANSCRIBE -eq '1'){
  Write-Host 'Préparation de la transcription locale légère...' -ForegroundColor Cyan
  & .\.venv-local\Scripts\python.exe -m pip install --disable-pip-version-check 'faster-whisper>=1.1,<2'
  if($LASTEXITCODE -ne 0){Write-Host 'Transcription indisponible: le montage continuera sans elle.' -ForegroundColor Yellow;$env:LOCAL_TRANSCRIBE='0'}
}

$UseLocalAI=($env:LOCAL_AI_AUTO_ENABLED -eq '1' -and $env:LOCAL_VLM_URL)
if($UseLocalAI){
  if(-not (Get-Command ollama -ErrorAction SilentlyContinue)){Write-Host 'Ollama absent: fallback Director V8 léger.' -ForegroundColor Yellow;$env:LOCAL_VLM_URL=''}
  else{
    $ready=$false
    try{Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3|Out-Null;$ready=$true}catch{try{Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden;Start-Sleep -Seconds 4;Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5|Out-Null;$ready=$true}catch{$ready=$false}}
    if($ready){$model=if($env:LOCAL_VLM_MODEL){$env:LOCAL_VLM_MODEL}else{'qwen2.5vl:3b'};$installed=$false;try{$list=ollama list|Out-String;if($list -match [regex]::Escape($model)){$installed=$true}}catch{};if(-not $installed){try{ollama pull $model}catch{$env:LOCAL_VLM_URL=''}}}else{$env:LOCAL_VLM_URL=''}
  }
}else{$env:LOCAL_VLM_URL=''}

Write-Host 'Diagnostic sécurisé...' -ForegroundColor Cyan
& .\.venv-local\Scripts\python.exe (Join-Path $PSScriptRoot 'doctor.py')
if($LASTEXITCODE -ne 0){throw 'Le diagnostic a détecté un problème critique.'}

Write-Host ''
Write-Host 'Worker PC démarré. Il devient prioritaire sur Render quand son heartbeat HTTPS est reçu.' -ForegroundColor Green
& .\.venv-local\Scripts\python.exe (Join-Path $PSScriptRoot 'http_worker_v2.py')
