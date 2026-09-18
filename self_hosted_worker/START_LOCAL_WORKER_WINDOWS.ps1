$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host '=== Auto Director Local Worker ===' -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw 'Python 3.12+ est requis.'
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  throw 'Ollama est requis. Installe-le depuis ollama.com puis relance ce script.'
}

$EnvFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $PSScriptRoot '.env.example') $EnvFile
  Write-Host "Fichier cree: $EnvFile" -ForegroundColor Yellow
  Write-Host 'Renseigne DATABASE_URL et REDIS_URL externes de Render puis relance.' -ForegroundColor Yellow
  exit 1
}

Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $parts = $_ -split '=', 2
  [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
}

if ($env:DATABASE_URL -like '*USER:PASSWORD*' -or $env:REDIS_URL -like '*PASSWORD*') {
  throw 'Configure DATABASE_URL et REDIS_URL dans self_hosted_worker/.env.'
}

if (-not (Test-Path '.venv-local')) {
  python -m venv .venv-local
}
& .\.venv-local\Scripts\python.exe -m pip install --upgrade pip
& .\.venv-local\Scripts\python.exe -m pip install -r requirements.txt

$model = if ($env:LOCAL_VLM_MODEL) { $env:LOCAL_VLM_MODEL } else { 'qwen2.5vl:3b' }
Write-Host "Verification du modele local: $model" -ForegroundColor Cyan
ollama pull $model

Write-Host 'Worker local en cours. Tu peux laisser cette fenetre ouverte/minimisee.' -ForegroundColor Green
& .\.venv-local\Scripts\python.exe worker.py
