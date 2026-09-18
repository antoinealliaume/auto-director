$ErrorActionPreference = 'Stop'

$AgentVersion = '2.4'
$AllowedOrigin = 'https://auto-director-web.onrender.com'
$Port = 8765
$InstallRoot = Join-Path $env:LOCALAPPDATA 'AutoDirector'
$RepoRoot = Join-Path $InstallRoot 'repo'
$Launcher = Join-Path $RepoRoot 'self_hosted_worker\START_LOCAL_WORKER_WINDOWS.ps1'
$Runner = Join-Path $RepoRoot 'self_hosted_worker\run_worker_logged.ps1'
$LogFile = Join-Path $InstallRoot 'worker.log'
$script:WorkerPid = $null
$script:LastExitCode = $null
$script:LastStartError = ''

function Get-LogTail {
  try {
    if (-not (Test-Path $LogFile)) { return '' }
    $text = ((Get-Content $LogFile -Encoding UTF8 -Tail 24 -ErrorAction Stop) -join "`n")
    if ($text.Length -gt 3000) { $text = $text.Substring($text.Length - 3000) }
    return $text
  } catch { return '' }
}
function Worker-IsRunning {
  if (-not $script:WorkerPid) { return $false }
  try { Get-Process -Id $script:WorkerPid -ErrorAction Stop | Out-Null; return $true }
  catch { $script:WorkerPid=$null; return $false }
}
function Json-Response([bool]$ok,[hashtable]$extra=@{}) {
  $running=Worker-IsRunning;$body=@{ok=$ok;agent=$true;agentVersion=$AgentVersion;workerRunning=$running;workerPid=$script:WorkerPid;lastExitCode=$script:LastExitCode;lastStartError=$script:LastStartError;logTail=(Get-LogTail)}
  foreach($k in $extra.Keys){$body[$k]=$extra[$k]};return ($body|ConvertTo-Json -Compress -Depth 6)
}
function Write-Response($stream,[int]$status,[string]$body,[string]$origin) {
  $statusText=switch($status){200{'OK'}204{'No Content'}400{'Bad Request'}401{'Unauthorized'}403{'Forbidden'}404{'Not Found'}409{'Conflict'}500{'Internal Server Error'}default{'OK'}};$payload=[Text.Encoding]::UTF8.GetBytes($body)
  $headers="HTTP/1.1 $status $statusText`r`nContent-Type: application/json; charset=utf-8`r`nContent-Length: $($payload.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n"
  if($origin -eq $AllowedOrigin){$headers+="Access-Control-Allow-Origin: $AllowedOrigin`r`nVary: Origin`r`nAccess-Control-Allow-Methods: GET, POST, OPTIONS`r`nAccess-Control-Allow-Headers: Content-Type`r`nAccess-Control-Allow-Private-Network: true`r`n"};$headers+="`r`n";$hb=[Text.Encoding]::ASCII.GetBytes($headers);$stream.Write($hb,0,$hb.Length);if($payload.Length -gt 0){$stream.Write($payload,0,$payload.Length)};$stream.Flush()
}
function Stop-Worker { if(Worker-IsRunning){try{& taskkill.exe /PID $script:WorkerPid /T /F|Out-Null}catch{}};$script:WorkerPid=$null }
function Send-StartingHeartbeat([string]$studioUrl,[string]$workerToken) { try{$headers=@{Authorization="Bearer $workerToken"};$hb=@{engine='8.7';profile='starting';resolution=@(720,1280);fps=24;ffmpegThreads=1;localAI=$false}|ConvertTo-Json -Compress;Invoke-RestMethod -Method Post -Uri ($studioUrl.TrimEnd('/')+'/api/local-worker/heartbeat') -Headers $headers -ContentType 'application/json' -Body $hb -TimeoutSec 12|Out-Null}catch{} }
function Start-Worker([string]$studioUrl,[string]$studioToken) {
  if(Worker-IsRunning){return @{alreadyRunning=$true;pid=$script:WorkerPid}};$script:LastStartError='';$script:LastExitCode=$null
  if(-not(Test-Path $Launcher)){throw 'Worker local non installé. Réinstalle Auto Director Local Agent.'};if(-not(Test-Path $Runner)){throw 'Runner local manquant. Mets à jour Auto Director Local Agent.'}
  $uri=[Uri]$studioUrl;if($uri.Scheme -ne 'https' -or $uri.Host -ne 'auto-director-web.onrender.com'){throw 'Studio non autorisé.'};if(-not $studioToken -or $studioToken.Length -lt 20){throw 'Session Studio manquante.'}
  $headers=@{Authorization="Bearer $studioToken"};$body=@{label=$env:COMPUTERNAME}|ConvertTo-Json -Compress;$session=Invoke-RestMethod -Method Post -Uri ($studioUrl.TrimEnd('/')+'/api/local-worker/session') -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 20;if(-not $session.workerToken){throw 'Le Studio n a pas fourni de jeton worker.'}
  New-Item -ItemType Directory -Force -Path $InstallRoot|Out-Null;Send-StartingHeartbeat $studioUrl ([string]$session.workerToken)
  $psi=New-Object System.Diagnostics.ProcessStartInfo;$psi.FileName='powershell.exe';$psi.Arguments="-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -Launcher `"$Launcher`" -LogFile `"$LogFile`"";$psi.WorkingDirectory=$RepoRoot;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.EnvironmentVariables['STUDIO_URL']=$studioUrl.TrimEnd('/');$psi.EnvironmentVariables['WORKER_TOKEN']=[string]$session.workerToken;$psi.EnvironmentVariables['WORKER_KIND']='local';$psi.EnvironmentVariables['REMOTE_WORKER_MODE']='1';$pythonPath=[Environment]::GetEnvironmentVariable('AUTO_DIRECTOR_PYTHON','User');if($pythonPath){$psi.EnvironmentVariables['AUTO_DIRECTOR_PYTHON']=$pythonPath}
  $proc=[System.Diagnostics.Process]::Start($psi);if(-not $proc){throw 'Impossible de démarrer le worker.'};$script:WorkerPid=$proc.Id;Start-Sleep -Milliseconds 1700
  if(-not(Worker-IsRunning)){$tail=Get-LogTail;$script:LastStartError=if($tail){$tail}else{'Le processus worker s est arrêté immédiatement.'};throw $script:LastStartError}
  return @{pid=$proc.Id;started=$true;transport='https';workerId=[string]$session.workerId;logFile=$LogFile}
}

$listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$Port);try{$listener.Start()}catch{exit 0}
while($true){$client=$null;try{$client=$listener.AcceptTcpClient();$client.ReceiveTimeout=5000;$client.SendTimeout=5000;$stream=$client.GetStream();$reader=New-Object System.IO.StreamReader($stream,[Text.Encoding]::UTF8,$false,4096,$true);$requestLine=$reader.ReadLine();if(-not $requestLine){$client.Close();continue};$parts=$requestLine.Split(' ');if($parts.Count -lt 2){Write-Response $stream 400 (Json-Response $false @{error='bad request'}) '';$client.Close();continue};$method=$parts[0].ToUpperInvariant();$path=$parts[1].Split('?')[0];$headers=@{};while($true){$line=$reader.ReadLine();if($null -eq $line -or $line -eq ''){break};$idx=$line.IndexOf(':');if($idx -gt 0){$headers[$line.Substring(0,$idx).Trim().ToLowerInvariant()]=$line.Substring($idx+1).Trim()}};$origin=if($headers.ContainsKey('origin')){[string]$headers['origin']}else{''};if($origin -and $origin -ne $AllowedOrigin){Write-Response $stream 403 (Json-Response $false @{error='origin forbidden'}) '';$client.Close();continue};if($method -eq 'OPTIONS'){Write-Response $stream 204 '' $origin;$client.Close();continue};$body='';if($headers.ContainsKey('content-length')){$length=[int]$headers['content-length'];if($length -gt 65536){Write-Response $stream 400 (Json-Response $false @{error='body too large'}) $origin;$client.Close();continue};if($length -gt 0){$chars=New-Object char[] $length;$total=0;while($total -lt $length){$n=$reader.Read($chars,$total,$length-$total);if($n -le 0){break};$total+=$n};$body=New-Object string($chars,0,$total)}};if($method -eq 'GET' -and $path -eq '/status'){Write-Response $stream 200 (Json-Response $true @{installRoot=$InstallRoot;transport='https';logFile=$LogFile}) $origin}elseif($method -eq 'POST' -and $path -eq '/start'){try{$data=if($body){$body|ConvertFrom-Json}else{$null};if(-not $data){throw 'Requête vide.'};$result=Start-Worker ([string]$data.studioUrl) ([string]$data.token);Write-Response $stream 200 (Json-Response $true $result) $origin}catch{$script:LastStartError=$_.Exception.Message;Write-Response $stream 500 (Json-Response $false @{error=$_.Exception.Message}) $origin}}elseif($method -eq 'POST' -and $path -eq '/stop'){Stop-Worker;Write-Response $stream 200 (Json-Response $true @{stopped=$true}) $origin}else{Write-Response $stream 404 (Json-Response $false @{error='not found'}) $origin}}catch{try{if($client){$client.Close()}}catch{}}finally{try{if($client){$client.Close()}}catch{}}}
