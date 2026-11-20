# crea_msix.ps1 - costruisce il pacchetto MSIX di Argo per il Microsoft Store (x64, gira anche su Windows ARM).
#
# Il pacchetto e' autonomo e offline: Python 3.12, le librerie di requisiti.lock (con hash), FFmpeg LGPL
# e la cartella app. Non scarica niente al primo avvio, salvo i modelli (con conferma) e Ollama, che resta a parte.
#
#   pwsh strumenti/msix/crea_msix.ps1 [-Uscita dist] [-FirmaDiProva]
#
# -FirmaDiProva firma il pacchetto con un certificato autofirmato (stesso Publisher del manifesto) e salva
# il .cer accanto: serve solo per installarlo sul proprio PC. Il pacchetto per lo Store NON va firmato:
# lo firma Microsoft dopo la certificazione.
param(
    [string]$Uscita = "dist",
    [switch]$FirmaDiProva
)
$ErrorActionPreference = "Stop"
$Radice = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Lavoro = Join-Path ([IO.Path]::GetTempPath()) "argo-msix"
$Pkg = Join-Path $Lavoro "pacchetto"
$ModelloFfmpeg = "^ffmpeg-n8\.\d+-latest-win64-lgpl-shared-8\.\d+\.zip$"  # FFmpeg 8.x LGPL condiviso (BtbN)

function Passo($testo) { Write-Host "`n== $testo" -ForegroundColor Cyan }

if (Test-Path $Lavoro) { Remove-Item $Lavoro -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Pkg, $Uscita | Out-Null
$Uscita = (Resolve-Path $Uscita).Path

Passo "Python 3.12 x64 (python-build-standalone, tramite uv)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv non trovato" }
$dirPy = Join-Path $Lavoro "pythons"
uv python install 3.12 --install-dir $dirPy --no-bin | Out-Host
$sorgPy = Get-ChildItem $dirPy -Directory | Where-Object { $_.Name -like "cpython-3.12*-windows-x86_64-*" } | Select-Object -First 1
if (-not $sorgPy) { throw "Python 3.12 x64 non trovato in $dirPy" }
Copy-Item $sorgPy.FullName (Join-Path $Pkg "python") -Recurse
$Py = Join-Path $Pkg "python\python.exe"
& $Py -c "import sys, sysconfig; print(sys.version, sysconfig.get_platform())"

Passo "Librerie da requisiti.lock (versioni fisse, hash verificati)"
uv pip install --python $Py --system --break-system-packages --require-hashes --no-cache `
    -r (Join-Path $Radice "app\requisiti.lock") | Out-Host
if ($LASTEXITCODE -ne 0) { throw "installazione delle librerie non riuscita" }

Passo "Cartella app"
Copy-Item (Join-Path $Radice "app") (Join-Path $Pkg "app") -Recurse
Get-ChildItem (Join-Path $Pkg "app") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item (Join-Path $Radice "LICENSE"), (Join-Path $Radice "THIRD_PARTY_LICENSES.md") $Pkg

Passo "FFmpeg LGPL (build condivisa: serve anche a torchcodec)"
$zip = Join-Path $Lavoro "ffmpeg.zip"
$intest = @{}
if ($env:GH_TOKEN) { $intest["Authorization"] = "Bearer $env:GH_TOKEN" }  # sui runner condivisi senza token si supera il limite
$rel = Invoke-RestMethod "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest" -Headers $intest
$asset = $rel.assets | Where-Object { $_.name -match $ModelloFfmpeg } | Sort-Object name | Select-Object -Last 1
if (-not $asset) {
    $rel.assets.name | Where-Object { $_ -like "*win64-lgpl-shared*" } | ForEach-Object { Write-Host "  disponibile: $_" }
    throw "FFmpeg 8.x LGPL condiviso non trovato tra i file di BtbN/FFmpeg-Builds"
}
Write-Host "  $($asset.name)"
Invoke-WebRequest $asset.browser_download_url -OutFile $zip
Write-Host "  SHA-256 FFmpeg: $((Get-FileHash $zip -Algorithm SHA256).Hash)"
Expand-Archive $zip (Join-Path $Lavoro "ffmpeg")
$sorgFf = Get-ChildItem (Join-Path $Lavoro "ffmpeg") -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path (Join-Path $Pkg "strumenti") | Out-Null
Copy-Item $sorgFf.FullName (Join-Path $Pkg "strumenti\ffmpeg") -Recurse
Remove-Item (Join-Path $Pkg "strumenti\ffmpeg\doc"), (Join-Path $Pkg "strumenti\ffmpeg\include"), (Join-Path $Pkg "strumenti\ffmpeg\lib") -Recurse -Force -ErrorAction SilentlyContinue

Passo "Manifesto, icone e collegamento della cartella app"
uv pip install --python $Py --system --break-system-packages --no-cache pillow | Out-Host
& $Py (Join-Path $Radice "strumenti\msix\prepara_msix.py") $Pkg
if ($LASTEXITCODE -ne 0) { throw "preparazione del manifesto non riuscita" }
uv pip uninstall --python $Py --system --break-system-packages pillow | Out-Host

Passo "Byte-code precompilato (la cartella del pacchetto e' in sola lettura)"
& $Py -m compileall -q -j 0 (Join-Path $Pkg "app") (Join-Path $Pkg "python\Lib") | Out-Null

Passo "Prova: Argo si importa da un'altra cartella, con FFmpeg del pacchetto"
Push-Location $env:TEMP
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:ARGO_STORE = "1"
    & $Py -c @"
import store, sys
import torch, whisperx, PySide6.QtWidgets
import trascrittore, aggiornamenti
import shutil, subprocess
ff = shutil.which('ffmpeg')
assert ff and 'strumenti' in ff, ff
subprocess.run([ff, '-hide_banner', '-version'], check=True, capture_output=True)
assert aggiornamenti.canale_effettivo({}) == 'store'
try:
    import torchcodec.decoders  # carica le DLL di FFmpeg: serve a pyannote quando legge i file
    tc = 'ok'
except Exception as e:
    tc = 'NON disponibile (%s)' % str(e)[:120]
print('OK Argo', trascrittore.VERSIONE, '| torch', torch.__version__, '| ffmpeg', ff, '| torchcodec', tc)
"@
    if ($LASTEXITCODE -ne 0) { throw "la prova di importazione non e' riuscita" }
} finally {
    Remove-Item Env:QT_QPA_PLATFORM, Env:ARGO_STORE -ErrorAction SilentlyContinue
    Pop-Location
}

Passo "Cartelle superflue che MSIX non accetta"
# python-docx: la cartella sorgente del modello contiene [Content_Types].xml, nome riservato in MSIX.
# A Argo serve solo templates\default.docx, che resta.
Remove-Item (Join-Path $Pkg "python\Lib\site-packages\docx\templates\default-docx-template") -Recurse -Force -ErrorAction SilentlyContinue

Passo "Nomi di file che MSIX non accetta (CON, AUX, NUL, COM1..., spazi o punti finali, caratteri riservati)"
& $Py -c @"
import os, re, sys
riservati = re.compile(r'^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$', re.I)
vietati = re.compile(r'[<>:"|?*%]')
radice = sys.argv[1]; trovati = []
for cart, dirs, files in os.walk(radice):
    for n in dirs + files:
        if (riservati.match(n) or n.endswith((' ', '.')) or vietati.search(n)
                or n.lower() in ('[content_types].xml', 'appxblockmap.xml', 'appxsignature.p7x', 'appxmetadata')
                or (n.lower() == 'appxmanifest.xml' and cart != radice)):
            trovati.append(os.path.relpath(os.path.join(cart, n), radice))
for t in trovati:
    print('  ', t)
sys.exit(1 if trovati else 0)
"@ $Pkg
if ($LASTEXITCODE -ne 0) { throw "ci sono file con nomi non validi per MSIX (elenco sopra)" }

Passo "Pacchetto MSIX"
$kit = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" | Sort-Object FullName | Select-Object -Last 1
if (-not $kit) { throw "makeappx.exe non trovato: serve il Windows SDK" }
$versione = (Select-String -Path (Join-Path $Radice "app\trascrittore.py") -Pattern '^VERSIONE = "([^"]+)"').Matches[0].Groups[1].Value
$msix = Join-Path $Uscita "Argo-AI-$versione-x64.msix"
$log = & $kit.FullName pack /d $Pkg /p $msix /o 2>&1
$esito = $LASTEXITCODE
$log | Where-Object { $_ -notmatch "^Processing |^\s*$" } | Out-Host
if ($esito -ne 0) {
    Write-Host "  Ultimi file elaborati:"
    $log | Where-Object { $_ -match "^Processing " } | Select-Object -Last 12 | ForEach-Object { "   $_".Substring(0, [Math]::Min(220, "   $_".Length)) } | Out-Host
    & $Py -c @"
import os, sys
r = sys.argv[1]; lunghi = []; strani = []
for c, d, f in os.walk(r):
    for n in d + f:
        rel = os.path.relpath(os.path.join(c, n), r)
        if len(rel) > 200: lunghi.append(rel)
        if not n.isascii() or any(ch in n for ch in '[]#{}~;,=+&@^$!\'`'): strani.append(rel)
print('  percorsi > 200 caratteri:', len(lunghi)); [print('   ', x) for x in lunghi[:10]]
print('  nomi con caratteri particolari:', len(strani)); [print('   ', x) for x in strani[:30]]
"@ $Pkg
    throw "makeappx non riuscito"
}
Write-Host ("  {0}  ({1:N0} MB)" -f $msix, ((Get-Item $msix).Length / 1MB))

if ($FirmaDiProva) {
    Passo "Firma di prova (solo per installarlo sul proprio PC)"
    [xml]$man = Get-Content (Join-Path $Pkg "AppxManifest.xml")
    $editore = $man.Package.Identity.Publisher
    $cert = New-SelfSignedCertificate -Type Custom -Subject $editore -KeyUsage DigitalSignature `
        -FriendlyName "Argo AI - firma di prova" -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
    $pwd = ConvertTo-SecureString -String ([guid]::NewGuid().ToString()) -Force -AsPlainText
    $pfx = Join-Path $Lavoro "prova.pfx"
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pwd | Out-Null
    Export-Certificate -Cert $cert -FilePath (Join-Path $Uscita "Argo-AI-firma-di-prova.cer") | Out-Null
    $signtool = Join-Path $kit.DirectoryName "signtool.exe"
    $chiaro = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd))
    $msixProva = $msix -replace "\.msix$", "-prova.msix"
    Copy-Item $msix $msixProva
    & $signtool sign /fd SHA256 /f $pfx /p $chiaro $msixProva | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "firma di prova non riuscita" }
    Remove-Item $pfx -Force
}

Write-Host "`nFatto. Pacchetti in $Uscita" -ForegroundColor Green
