$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host '=== Auto Director Local Worker - mode adaptatif ===' -ForegroundColor Cyan

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

# Detecte le materiel avec uniquement la bibliotheque standard Python.
python (Join-Path $PSScriptRoot 'detect_profile.py')
$AutoProfile = Join-Path $PSScriptRoot '.auto_profile.env'
Import-EnvFile $AutoProfile $true
# Les choix explicites de .env restent prioritaires sur le profil automatique.
Import-EnvFile $EnvFile $true

if ($env:DATABASE_URL -like '*USER:PASSWORD*' -or $env:REDIS_URL -like '*PASSWORD*') {
  throw 'Configure uniquement DATABASE_URL et REDIS_URL dans self_hosted_worker/.env.'
}

Write-Host "Profil: $env:PROFILE_NAME" -ForegroundColor Green
Write-Host "Rendu: $env:RENDER_WIDTH x $env:RENDER_HEIGHT | FFmpeg threads: $env:FFMPEG_THREADS | samples: $env:MOMENT_SAMPLES" -ForegroundColor Green

# Limites globales prudentes pour ne pas monopoliser le PC.
$env:PYTHONUNBUFFERED='1'
$env:OMP_NUM_THREADS=$env:FFMPEG_THREADS
$env:MKL_NUM_THREADS=$env:FFMPEG_THREADS
$env:OPENBLAS_NUM_THREADS=$env:FFMPEG_THREADS
$env:OLLAMA_NUM_PARALLEL='1'
$env:OLLAMA_MAX_LOADED_MODELS='1'
$env:OLLAMA_MAX_QUEUE='2'
$env:OLLAMA_KEEP_ALIVE='2m'

if (-not (Test-Path '.venv-local')) {
  python -m venv .venv-local
}
& .\.venv-local\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt

$UseLocalAI = ($env:LOCAL_AI_AUTO_ENABLED -eq '1' -and $env:LOCAL_VLM_URL)
if ($UseLocalAI) {
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host 'Ollama non installe: le worker continue en V8 leger, sans IA visuelle locale.' -ForegroundColor Yellow
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
      Write-Host "IA locale prudente activee: $model (1 requete a la fois)" -ForegroundColor Cyan
      try {
        ollama pull $model
      } catch {
        Write-Host 'Impossible de charger le modele: fallback V8 leger.' -ForegroundColor Yellow
        $env:LOCAL_VLM_URL=''
      }
    } else {
      Write-Host 'Ollama indisponible: fallback V8 leger.' -ForegroundColor Yellow
      $env:LOCAL_VLM_URL=''
    }
  }
} else {
  $env:LOCAL_VLM_URL=''
  Write-Host 'Profil leger: IA visuelle lourde desactivee automatiquement.' -ForegroundColor Yellow
}

Write-Host 'Worker local lance. Il utilise au maximum un job a la fois.' -ForegroundColor Green
Write-Host 'Tu peux laisser cette fenetre ouverte ou la minimiser.' -ForegroundColor DarkGray
& .\.venv-local\Scripts\python.exe worker.py
