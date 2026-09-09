<#
Avvia (se non gia' in ascolto) il backend ACTELYA 3 (FastAPI/uvicorn).
Legge TUTTA la configurazione da backend\.env (nessuna credenziale
hardcoded qui). Vedi scripts/README-DB.md per il database in uso.

Idempotente: se la porta 8001 risponde gia', non avvia un secondo processo.
Non chiama mai /tick ne' approva/genera nulla: si limita ad avviare il
processo, che a sua volta (vedi server.py::startup) riprende SOLO i task
IN_ESECUZIONE interrotti da un riavvio, mai la coda storica IN_CODA.
#>

$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LogDir     = Join-Path $RepoRoot "logs"
$Port       = 8001

function Test-Port($p) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1", $p); return $true } catch { return $false } finally { $tcp.Close() }
}

if (Test-Port $Port) {
    Write-Output "Backend ACTELYA 3 gia' in ascolto su 127.0.0.1:$Port. Nessun nuovo processo avviato."
    exit 0
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtualenv non trovato in $VenvPython. Installare le dipendenze (vedi README.md, sezione Installazione e avvio)."
    exit 1
}

# Preflight non bloccante: avvisa se il MONGO_URL dichiarato in .env non e'
# raggiungibile ORA, cosi' un fallimento all'avvio del backend e' gia'
# spiegato invece di apparire come un errore generico.
$envFile = Join-Path $BackendDir ".env"
if (Test-Path $envFile) {
    $mongoLine = Select-String -Path $envFile -Pattern '^MONGO_URL=' | Select-Object -First 1
    if ($mongoLine -and ($mongoLine.Line -match ':(\d+)"?\s*$')) {
        $mongoPort = [int]$Matches[1]
        if (-not (Test-Port $mongoPort)) {
            Write-Warning "MONGO_URL in backend\.env punta alla porta $mongoPort, non raggiungibile ora. Avviare prima scripts\start_mongo.ps1."
        }
    }
}

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outLog = Join-Path $LogDir "backend-$stamp.out.log"
$errLog = Join-Path $LogDir "backend-$stamp.err.log"

Write-Output "Avvio backend ACTELYA 3 su porta $Port (log: $outLog) ..."
Start-Process -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", $Port) `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden

Start-Sleep -Seconds 5
if (Test-Port $Port) {
    Write-Output "OK: backend ACTELYA 3 in ascolto su 127.0.0.1:$Port."
} else {
    Write-Error "Il backend non risulta in ascolto dopo l'avvio: controllare $errLog."
    exit 1
}
