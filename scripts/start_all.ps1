<#
Avvia l'intero ambiente ACTELYA 3 (mongo dedicato -> backend -> frontend),
ciascun passo idempotente (salta se gia' in ascolto). Nessuna azione di
generazione/approvazione: si limita ad avviare i processi.
#>
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

& (Join-Path $ScriptDir "start_mongo.ps1")
& (Join-Path $ScriptDir "start_backend.ps1")
& (Join-Path $ScriptDir "start_frontend.ps1")

Write-Output ""
Write-Output "Ambiente ACTELYA 3: mongo 127.0.0.1:27030, backend http://127.0.0.1:8001/api, frontend http://127.0.0.1:3000"
