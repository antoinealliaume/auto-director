param(
  [Parameter(Mandatory=$true)][string]$Launcher,
  [Parameter(Mandatory=$true)][string]$LogFile
)

$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8

function Write-Log([string]$Text) {
  if ($null -eq $Text) { return }
  [System.IO.File]::AppendAllText($LogFile, $Text + [Environment]::NewLine, $Utf8)
}

try {
  $dir = Split-Path -Parent $LogFile
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  [System.IO.File]::WriteAllText(
    $LogFile,
    ('=== Auto Director worker start ' + (Get-Date -Format o) + ' ===' + [Environment]::NewLine),
    $Utf8
  )

  if (-not (Test-Path $Launcher)) {
    throw "Launcher introuvable: $Launcher"
  }

  & $Launcher *>&1 | ForEach-Object {
    Write-Log ([string]$_)
  }

  $code = 0
  if ($null -ne $LASTEXITCODE) { $code = [int]$LASTEXITCODE }
  Write-Log ("Worker launcher exit code: $code")
  exit $code
} catch {
  $message = ($_ | Out-String).Trim()
  Write-Log ('FATAL: ' + $message)
  exit 1
}
