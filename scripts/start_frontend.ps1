<#
Avvia (se non gia' in ascolto) il frontend ACTELYA 3 (React dev server, CRA/craco).
Idempotente: se la porta 3000 risponde gia', non avvia un secondo processo.
#>

$ErrorActionPreference = "Stop"

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RepoRoot "frontend"
$LogDir      = Join-Path $RepoRoot "logs"
$Port        = 3000

function Test-Port($p) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1", $p); return $true } catch { return $false } finally { $tcp.Close() }
}

if (Test-Port $Port) {
    Write-Output "Frontend ACTELYA 3 gia' in ascolto su 127.0.0.1:$Port. Nessun nuovo processo avviato."
    exit 0
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Error "node_modules mancante in frontend\. Eseguire 'yarn install --frozen-lockfile' prima di avviare."
    exit 1
}

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outLog = Join-Path $LogDir "frontend-$stamp.out.log"
$errLog = Join-Path $LogDir "frontend-$stamp.err.log"

Write-Output "Avvio frontend ACTELYA 3 su porta $Port (log: $outLog) ..."
# cmd.exe /c invece di invocare craco.cmd/yarn.cmd/npm.cmd direttamente:
# Start-Process non sa eseguire uno script .cmd/.ps1 come file diretto
# (serve un host che lo interpreti), qualunque sia il gestore pacchetti
# disponibile sulla macchina.
Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "node_modules\.bin\craco.cmd start") `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden

Start-Sleep -Seconds 8
if (Test-Port $Port) {
    Write-Output "OK: frontend ACTELYA 3 in ascolto su 127.0.0.1:$Port."
} else {
    Write-Output "Il frontend non risulta ancora in ascolto (il primo avvio di CRA puo' richiedere piu' tempo): controllare $outLog tra qualche secondo."
}
