# Installer del Trascrittore per Windows (x64 e ARM).
# Avviato da "Installa-Trascrittore.bat". Non servono diritti di amministratore.
$ErrorActionPreference = "Stop"
$App = Join-Path $HOME "whisperx-env"
$Src = Join-Path (Split-Path $PSScriptRoot -Parent) "app"

function Passo($n, $testo) { Write-Host "`n[$n/6] $testo" -ForegroundColor Cyan }
function Aggiorna-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Installa-Se-Manca($comando, $id) {
    if (Get-Command $comando -ErrorAction SilentlyContinue) {
        Write-Host "  $comando gia' presente."
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget non trovato. Installa 'Programma di installazione app' dal Microsoft Store e riprova."
    }
    Write-Host "  Installo $comando..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements | Out-Host
    Aggiorna-Path
    if (-not (Get-Command $comando -ErrorAction SilentlyContinue)) {
        throw "$comando installato ma non ancora visibile: chiudi questa finestra e rilancia l'installer."
    }
}

try {
    Write-Host "=== Installazione Argo - Cassetta degli attrezzi AI ===" -ForegroundColor Green
    Write-Host "Cartella: $App"

    Passo 1 "Strumenti di base (FFmpeg e uv)"
    Installa-Se-Manca "ffmpeg" "Gyan.FFmpeg"
    Installa-Se-Manca "uv" "astral-sh.uv"

    Passo 2 "Ambiente Python"
    $py = Join-Path $App "Scripts\python.exe"
    # chiude eventuali Python di questo ambiente ancora aperti (bloccano i file)
    Get-Process python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($App, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    if (Test-Path $py) {
        # sysconfig indica l'architettura dell'interprete (platform.machine() su ARM mente in emulazione)
        $plat = ""
        try { $plat = (& $py -c "import sysconfig; print(sysconfig.get_platform())" 2>$null) } catch {}
        $sano = $false
        try { & $py -c "import encodings" 2>$null; $sano = ($LASTEXITCODE -eq 0) } catch {}
        if ($plat -eq "win-amd64" -and $sano) {
            Write-Host "  Ambiente esistente (x64) riutilizzato: voci e token restano."
        } else {
            Write-Host "  Ambiente esistente non utilizzabile ($plat): lo ricreo in x64." -ForegroundColor Yellow
            Get-ChildItem $App -Force -Exclude "voci", ".hf_token", "trascrittore_*.json" | Remove-Item -Recurse -Force
        }
    }
    if (-not (Test-Path $py)) {
        # x64 sempre: su PC ARM gira in emulazione, perche' ctranslate2 non esiste per ARM Windows
        uv venv $App --python cpython-3.12-windows-x86_64-none --allow-existing | Out-Host
    }

    Passo 3 "WhisperX e interfaccia grafica (10-15 minuti la prima volta)"
    uv pip install --python $py -r (Join-Path $Src "requisiti.txt") | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Installazione dei pacchetti non riuscita (vedi messaggi sopra)." }

    Passo 4 "Copia dell'applicazione"
    $Dest = Join-Path $App "app"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item (Join-Path $Src "*") $Dest -Recurse -Force

    Passo 5 "Collegamenti su Desktop e menu Start"
    $ws = New-Object -ComObject WScript.Shell
    $dove = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
    foreach ($cartella in $dove) {
        $vecchio = Join-Path $cartella "Trascrittore.lnk"
        if (Test-Path $vecchio) { Remove-Item $vecchio -Force }
        $lnk = $ws.CreateShortcut((Join-Path $cartella "Argo AI.lnk"))
        $lnk.TargetPath = Join-Path $App "Scripts\pythonw.exe"
        $lnk.Arguments = '"' + (Join-Path $Dest "trascrittore.py") + '"'
        $lnk.WorkingDirectory = $Dest
        $lnk.IconLocation = Join-Path $Dest "icon.ico"
        $lnk.Description = "Argo - Cassetta degli attrezzi AI (tutto in locale)"
        $lnk.Save()
    }
    # Argo tra le app installate (Impostazioni > App) e "Disinstalla Argo" nel menu Start, solo per questo utente
    & $py (Join-Path $Dest "disinstalla.py") registra | Out-Host

    Passo 6 "Ollama (modelli linguistici locali: Verbale, Documenti, Traduzione, Incontri)"
    # Non blocca mai l'installazione di Argo: se qualcosa va storto spiega come installarlo a mano.
    $OllamaNota = ""
    $OllamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if ((Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path $OllamaExe)) {
        Write-Host "  Ollama gia' presente."
    } else {
        $r = Read-Host "  Ollama non e' installato. Lo installo adesso (circa 1,5 GB, i modelli dopo, da Argo)? [S/n]"
        if ($r -match '^[nN]') {
            $OllamaNota = "Ollama non installato: quando vuoi, scaricalo da https://ollama.com/download"
        } else {
            try {
                winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements | Out-Host
                Aggiorna-Path
                if ((Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path $OllamaExe)) {
                    Write-Host "  Ollama installato (icona del lama vicino all'orologio)."
                } else {
                    $OllamaNota = "installazione di Ollama non confermata: scaricalo da https://ollama.com/download"
                }
            } catch {
                $OllamaNota = "installazione di Ollama non riuscita ($($_.Exception.Message)): scaricalo da https://ollama.com/download"
            }
        }
    }

    Write-Host "`nINSTALLAZIONE COMPLETATA" -ForegroundColor Green
    Write-Host "Apri 'Argo AI' dal Desktop o dal menu Start."
    if ($OllamaNota) {
        Write-Host "NOTA: $OllamaNota" -ForegroundColor Yellow
        Write-Host "      Senza Ollama funzionano trascrizione e voci; Ollama serve per Verbale, Documenti, Dettatura, Traduzione e Incontri." -ForegroundColor Yellow
    } else {
        Write-Host "Al primo avvio Argo propone di scaricare i modelli consigliati di Ollama."
    }
    Write-Host "Al primo avvio inserisci il token Hugging Face nelle Impostazioni."
}
catch {
    Write-Host "`nERRORE: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Copia questo messaggio e mandalo a chi ti assiste."
    exit 1
}
