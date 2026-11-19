# Disinstallazione di Argo - Cassetta degli attrezzi AI su Windows.
# Avviato da Impostazioni > App installate, dal menu Start ("Disinstalla Argo"), dal pulsante nelle
# Impostazioni di Argo oppure da "Disinstalla-Argo.bat". Non servono diritti di amministratore.
# Toglie collegamenti, registrazione tra le app installate e la cartella whisperx-env (programma e dati).
# Prima propone un backup. Non tocca Ollama, i suoi modelli, uv, FFmpeg e le cache dei modelli condivise.
param([switch]$DaTemp)
$App = Join-Path $HOME "whisperx-env"
$Chiave = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgoAI"

# Lanciato da dentro whisperx-env: mi copio nella cartella temporanea e riparto da li',
# altrimenti non potrei cancellare la cartella in cui mi trovo.
if (-not $DaTemp -and $PSCommandPath -and $PSCommandPath.StartsWith($App, [StringComparison]::OrdinalIgnoreCase)) {
    $copia = Join-Path $env:TEMP "argo-disinstalla.ps1"
    Copy-Item -LiteralPath $PSCommandPath -Destination $copia -Force
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$copia`"", "-DaTemp")
    exit
}
$Registrazioni = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Argo"
$Collegamenti = @()
foreach ($cartella in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    foreach ($nome in @("Argo AI.lnk", "Trascrittore.lnk", "Disinstalla Argo.lnk")) {
        $p = Join-Path $cartella $nome
        if (Test-Path $p) { $Collegamenti += $p }
    }
}

function Si($domanda) { (Read-Host $domanda) -match '^[sS]' }

Write-Host "=== Disinstallazione di Argo - Cassetta degli attrezzi AI ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verranno eliminati:"
foreach ($c in $Collegamenti) { Write-Host "  - il collegamento: $c" }
if (Test-Path $App) { Write-Host "  - programma e dati: $App (impronte vocali, incontri, clienti, impostazioni, chiavi e token)" }
if (Test-Path $Chiave) { Write-Host "  - la voce 'Argo AI' in Impostazioni > App installate" }
if (-not (Test-Path $App) -and $Collegamenti.Count -eq 0 -and -not (Test-Path $Chiave)) {
    Write-Host "  niente: Argo non risulta installato per questo utente."
    if ($DaTemp) { Read-Host "Premi Invio per chiudere" | Out-Null }
    return
}
Write-Host ""
Write-Host "Restano: Ollama e i suoi modelli, uv, FFmpeg, le cache in $HOME\.cache."
Write-Host ""

if (-not (Si "Vuoi davvero disinstallare Argo? [s/N]")) {
    Write-Host "Nessuna modifica."
    if ($DaTemp) { Read-Host "Premi Invio per chiudere" | Out-Null }
    return
}

if ((Test-Path $App) -and (Si "Faccio prima un backup di voci, incontri, clienti e impostazioni sul Desktop? [s/N]")) {
    $Backup = Join-Path ([Environment]::GetFolderPath("Desktop")) ("Argo-backup-" + (Get-Date -Format "yyyyMMdd-HHmm"))
    try {
        New-Item -ItemType Directory -Force $Backup | Out-Null
    } catch {
        Write-Host "ERRORE: non riesco a creare $Backup. Mi fermo, non ho cancellato niente." -ForegroundColor Red
        if ($DaTemp) { Read-Host "Premi Invio per chiudere" | Out-Null }
        return
    }
    foreach ($cosa in @("voci", "incontri", "clienti", "glossario.csv", "documenti_indice.json",
                        "documenti_indice.npy", "trascrittore_impostazioni.json")) {
        $p = Join-Path $App $cosa
        if (Test-Path $p) { Copy-Item $p $Backup -Recurse -Force }
    }
    Write-Host "  Backup in: $Backup"
    Write-Host "  (token e chiavi API non sono nel backup: andranno reinseriti)"
}

Write-Host ""
Write-Host "Chiudo Argo se e' aperto..."
Get-Process python, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like "$App\*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

foreach ($c in $Collegamenti) { Remove-Item $c -Force -ErrorAction SilentlyContinue; Write-Host "  Eliminato $c" }
if (Test-Path $Chiave) {
    Remove-Item $Chiave -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  Tolta la voce 'Argo AI' da Impostazioni > App installate"
}
if (Test-Path $App) {
    Remove-Item $App -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $App) {
        Write-Host "  ATTENZIONE: non sono riuscito a eliminare tutto $App (un file e' ancora in uso?). Riavvia e rilancia." -ForegroundColor Yellow
    } else {
        Write-Host "  Eliminata la cartella whisperx-env"
    }
}

if ((Test-Path $Registrazioni) -and (Si "Elimino anche le registrazioni archiviate in ${Registrazioni}? [s/N]")) {
    Remove-Item $Registrazioni -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  Eliminate le registrazioni archiviate"
}

Write-Host ""
Write-Host "Argo e' stato disinstallato." -ForegroundColor Green
Write-Host "Se vuoi liberare altro spazio, a mano:"
Write-Host "  - modelli di Ollama: 'ollama list' per vederli, 'ollama rm <nome>' per toglierli"
Write-Host "  - cache dei modelli di trascrizione: $HOME\.cache\huggingface e $HOME\.cache\torch (se nessun altro programma le usa)"
Write-Host "  - FFmpeg e uv, se li aveva installati Argo: 'winget uninstall Gyan.FFmpeg' e 'winget uninstall astral-sh.uv'"
if ($DaTemp) { Write-Host ""; Read-Host "Premi Invio per chiudere" | Out-Null }
