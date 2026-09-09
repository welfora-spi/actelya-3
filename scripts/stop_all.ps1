<#
Arresta in modo controllato l'ambiente ACTELYA 3 avviato con start_all.ps1:
frontend e backend (Stop-Process sul processo in ascolto sulla porta),
poi MongoDB (comando 'shutdown' nativo, mai un kill del processo — evita
uno shutdown non pulito che al riavvio richiederebbe il recovery WiredTiger).

Non tocca l'istanza condivisa 127.0.0.1:27020 (contiene anche actelya2_db,
fuori perimetro) ne' alcun altro processo estraneo ad ACTELYA 3.
#>
$ErrorActionPreference = "Stop"

function Stop-ByPort($port, $label) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Output "$label (porta $port): non in ascolto, nulla da fermare."
        return
    }
    foreach ($c in $conns) {
        Write-Output "$label (porta $port): arresto processo PID $($c.OwningProcess)."
        Stop-Process -Id $c.OwningProcess -Force -Confirm:$false -ErrorAction SilentlyContinue
    }
}

Stop-ByPort 3000 "Frontend"
Stop-ByPort 8001 "Backend"

# MongoDB dedicato (27030): shutdown pulito via comando amministrativo,
# NON Stop-Process (che lascerebbe mongod.lock sporco, forzando un
# recovery WiredTiger al prossimo avvio).
$mongoScript = @"
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
try:
    MongoClient('mongodb://127.0.0.1:27030', serverSelectionTimeoutMS=3000).admin.command({'shutdown': 1})
except AutoReconnect:
    pass
except Exception as e:
    print('mongo 27030: non raggiungibile o gia'' fermo (', e, ')')
"@
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $tmpPy = [System.IO.Path]::GetTempFileName() + ".py"
    Set-Content -Path $tmpPy -Value $mongoScript -Encoding utf8
    & $VenvPython $tmpPy
    Remove-Item $tmpPy -ErrorAction SilentlyContinue
    Write-Output "MongoDB ACTELYA 3 (27030): comando di shutdown pulito inviato."
} else {
    Write-Warning "Virtualenv non trovato: impossibile inviare lo shutdown pulito a MongoDB 27030. Non forzare un kill del processo manualmente senza necessita'."
}

Write-Output ""
Write-Output "Nota: l'istanza condivisa 127.0.0.1:27020 (contiene anche actelya2_db) NON viene toccata da questo script."
