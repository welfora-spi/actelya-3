<#
Avvia (se non gia' in ascolto) l'istanza MongoDB DEDICATA di ACTELYA 3.
Vedi scripts/README-DB.md per l'architettura completa e la cronologia
della migrazione (2026-09-09).

Idempotente: se la porta risponde gia', non avvia una seconda istanza.
Nessuna credenziale: mongod locale senza autenticazione (dev), invariato
rispetto all'assetto precedente.
#>

$ErrorActionPreference = "Stop"

$MongodExe = "C:\Users\pata0\ActelyaRuntime\bin\mongod-7.0.14\mongod.exe"
$DbPath    = "C:\Users\pata0\ActelyaRuntime\data\actelya3_dev"
$LogPath   = "C:\Users\pata0\ActelyaRuntime\logs\mongod-27030-actelya3-dedicated.log"
$Port      = 27030

function Test-Port($p) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1", $p); return $true } catch { return $false } finally { $tcp.Close() }
}

if (Test-Port $Port) {
    Write-Output "MongoDB ACTELYA 3 gia' in ascolto su 127.0.0.1:$Port. Nessuna nuova istanza avviata."
    exit 0
}

if (-not (Test-Path $MongodExe)) {
    Write-Error "mongod.exe non trovato in $MongodExe. Vedi scripts/README-DB.md per come procurarlo (binario portable, non versionato in git)."
    exit 1
}
if (-not (Test-Path $DbPath)) {
    Write-Error "dbpath dedicata mancante: $DbPath. Non avviare mongod su una dbpath vuota per errore: rischio di ottenere un'app vuota invece della vera diagnosi di ambiente mancante. Vedi scripts/README-DB.md."
    exit 1
}

Write-Output "Avvio MongoDB ACTELYA 3 (dedicata, sola actelya3_dev) su porta $Port ..."
Start-Process -FilePath $MongodExe `
    -ArgumentList @("--port", $Port, "--bind_ip", "127.0.0.1", "--dbpath", $DbPath, "--logpath", $LogPath, "--logappend") `
    -WindowStyle Hidden

Start-Sleep -Seconds 3
if (Test-Port $Port) {
    Write-Output "OK: MongoDB ACTELYA 3 in ascolto su 127.0.0.1:$Port (log: $LogPath)."
} else {
    Write-Error "MongoDB non risulta in ascolto dopo l'avvio: controllare $LogPath."
    exit 1
}
