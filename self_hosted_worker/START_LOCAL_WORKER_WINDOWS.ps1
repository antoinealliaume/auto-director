$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host '=== Auto Director Local Worker - mode auto prudent ===' -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw 'Python 3.12+ est requis.'
}

$EnvFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $PSScriptRoot '.env.example') $EnvFile
  Write-Host "Fichier cree: $EnvFile" -ForegroundColor Yellow
  Write-Host 'Renseigne seulement DATABASE_URL et REDIS_URL externes de Render, puis relance.' -ForegroundColor Yellow
  exit 1
}

function Import-EnvFile([string]$Path, [bool]$Overwrite=$true) {
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $parts = $_ -split '=', 2
    $key = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($Overwrite -or -not [Environment]::GetEnvironmentVariable($key, 'Process')) {
      [Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
  }
}

# Load connection settings first. The automatic profile then overrides only
# performance-related variables so an old .env cannot accidentally overload the PC.
Import-EnvFile $EnvFile $true

$AutoProfileEnabled = ($env:AUTO_PROFILE -ne '0')
if ($AutoProfileEnabled) {
  python (Join-Path $PSScriptRoot 'detect_profile.py')
  $AutoProfile = Join-Path $PSScriptRoot '.auto_profile.env'
  Import-EnvFile $AutoProfile $true
} else {
  Write-Host 'AUTO_PROFILE=0: reglages materiels manuels actifs.' -ForegroundColor Yellow
}

if (-not $env:DATABASE_URL -or -not $env:REDIS_URL -or $env:DATABASE_URL -like '*USER:PASSWORD*' -or $env:REDIS_URL -like '*PASSWORD*') {
  throw 'Configure DATABASE_URL et REDIS_URL dans self_hosted_worker/.env.'
}

if (-not $env:PROFILE_NAME) { $env:PROFILE_NAME='manual-safe' }
if (-not $env:RENDER_WIDTH) { $env:RENDER_WIDTH='720' }
if (-not $env:RENDER_HEIGHT) { $env:RENDER_HEIGHT='1280' }
if (-not $env:RENDER_FPS) { $env:RENDER_FPS='30' }
if (-not $env:FFMPEG_THREADS) { $env:FFMPEG_THREADS='2' }
if (-not $env:MOMENT_SAMPLES) { $env:MOMENT_SAMPLES='5' }
if (-not $env:MAX_REVISIONS) { $env:MAX_REVISIONS='0' }

Write-Host "Profil: $env:PROFILE_NAME" -ForegroundColor Green
Write-Host "Rendu: $env:RENDER_WIDTH x $env:RENDER_HEIGHT @ $env:RENDER_FPS fps" -ForegroundColor Green
Write-Host "Charge limitee: FFmpeg=$env:FFMPEG_THREADS threads | analyse=$env:MOMENT_SAMPLES points | revisions=$env:MAX_REVISIONS" -ForegroundColor Green

$env:WORKER_KIND='local'
$env:PYTHONUNBUFFERED='1'
$env:OMP_NUM_THREADS=$env:FFMPEG_THREADS
$env:MKL_NUM_THREADS=$env:FFMPEG_THREADS
$env:OPENBLAS_NUM_THREADS=$env:FFMPEG_THREADS
$env:OLLAMA_NUM_PARALLEL='1'
$env:OLLAMA_MAX_LOADED_MODELS='1'
$env:OLLAMA_MAX_QUEUE='1'
$env:OLLAMA_KEEP_ALIVE='90s'

try { [System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = 'BelowNormal' } catch {}

if (-not (Test-Path '.venv-local')) {
  python -m venv .venv-local
}
& .\.venv-local\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt

$UseLocalAI = ($env:LOCAL_AI_AUTO_ENABLED -eq '1' -and $env:LOCAL_VLM_URL)
if ($UseLocalAI) {
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host 'Ollama absent: le worker continue normalement avec le Director V8 leger.' -ForegroundColor Yellow
    $env:LOCAL_VLM_URL=''
  } else {
    $OllamaReady = $false
    try {
      Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null
      $OllamaReady = $true
    } catch {
      Write-Host 'Demarrage d Ollama en arriere-plan...' -ForegroundColor Cyan
      Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
      Start-Sleep -Seconds 4
      try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null
        $OllamaReady = $true
      } catch { $OllamaReady = $false }
    }

    if ($OllamaReady) {
      $model = if ($env:LOCAL_VLM_MODEL) { $env:LOCAL_VLM_MODEL } else { 'qwen2.5vl:3b' }
      $Installed = $false
      try {
        $list = ollama list | Out-String
        if ($list -match [regex]::Escape($model)) { $Installed = $true }
      } catch {}
      if (-not $Installed) {
        Write-Host "Petit modele local non present. Installation unique: $model" -ForegroundColor Cyan
        try { ollama pull $model } catch { $env:LOCAL_VLM_URL='' }
      }
      if ($env:LOCAL_VLM_URL) {
        Write-Host "IA locale activee en mode prudent: $model, 1 requete a la fois." -ForegroundColor Cyan
      } else {
        Write-Host 'Modele indisponible: fallback V8 leger.' -ForegroundColor Yellow
      }
    } else {
      $env:LOCAL_VLM_URL=''
      Write-Host 'Ollama indisponible: fallback V8 leger.' -ForegroundColor Yellow
    }
  }
} else {
  $env:LOCAL_VLM_URL=''
  Write-Host 'IA visuelle lourde desactivee automatiquement sur cette machine.' -ForegroundColor Yellow
}

Write-Host 'Worker local lance en priorite basse. Il devient prioritaire sur Render.' -ForegroundColor Green
Write-Host 'Si tu fermes cette fenetre, Render reprend automatiquement les jobs.' -ForegroundColor DarkGray
& .\.venv-local\Scripts\python.exe worker.py
