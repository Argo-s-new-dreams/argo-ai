#!/bin/bash
# Doppio clic per installare Argo · Cassetta degli attrezzi AI su macOS (Apple Silicon M1 o successivi).
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/whisperx-env"
BUNDLE="$HOME/Applications/Argo AI.app"
VECCHIO="$HOME/Applications/Trascrittore.app"

errore() { echo; echo "ERRORE: $1"; echo "Copia questo messaggio e mandalo a chi ti assiste."; read -r -p "Premi Invio per chiudere..."; exit 1; }
passo() { echo; echo "[$1/5] $2"; }

echo "=== Installazione Argo · Cassetta degli attrezzi AI ==="
echo "Cartella: $APP"

[ "$(uname -m)" = "arm64" ] || errore "Serve un Mac Apple Silicon (M1 o successivi): PyTorch non esiste piu' per i Mac Intel."
passo 1 "Strumenti di base (Homebrew, FFmpeg, uv)"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew "$HOME/.homebrew/bin/brew"; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
command -v brew >/dev/null || errore "Homebrew non trovato. Installalo da https://brew.sh e rilancia l'installer."
command -v ffmpeg >/dev/null || brew install ffmpeg || errore "installazione di ffmpeg non riuscita"
command -v uv >/dev/null || brew install uv || errore "installazione di uv non riuscita"
BREW_BIN="$(dirname "$(command -v brew)")"

passo 2 "Ambiente Python"
if [ -x "$APP/bin/python" ]; then
  echo "  Ambiente esistente riutilizzato (voci e token restano)."
else
  uv venv "$APP" --python 3.12 --allow-existing || errore "creazione dell'ambiente Python non riuscita"
fi

passo 3 "WhisperX e interfaccia grafica (5-15 minuti la prima volta)"
uv pip install --python "$APP/bin/python" whisperx hf_xet PySide6 pypdf python-docx sounddevice || errore "installazione dei pacchetti non riuscita"

passo 4 "Copia dell'applicazione"
mkdir -p "$APP/app"
cp -R "$DIR/app/." "$APP/app/" || errore "copia dei file non riuscita"

passo 5 "Creazione di Argo AI.app in ~/Applications"
[ -d "$VECCHIO" ] && rm -rf "$VECCHIO" && echo "  Rimossa la vecchia Trascrittore.app"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cat > "$BUNDLE/Contents/MacOS/ArgoAI" <<EOF
#!/bin/bash
# Le app aperte dal Finder non vedono il PATH del Terminale: aggiungo Homebrew per ffmpeg.
export PATH="$BREW_BIN:/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$APP/bin/python" "$APP/app/trascrittore.py"
EOF
chmod +x "$BUNDLE/Contents/MacOS/ArgoAI"
cat > "$BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Argo AI</string>
  <key>CFBundleDisplayName</key><string>Argo AI</string>
  <key>CFBundleIdentifier</key><string>blog.argosnewdreams.trascrittore</string>
  <key>CFBundleVersion</key><string>20261114.1500</string>
  <key>CFBundleExecutable</key><string>ArgoAI</string>
  <key>NSMicrophoneUsageDescription</key><string>Argo usa il microfono solo per la dettatura, elaborata interamente su questo Mac.</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
iconutil -c icns "$APP/app/icon.iconset" -o "$BUNDLE/Contents/Resources/icon.icns" 2>/dev/null || echo "  (icona non creata, nessun problema)"
touch "$BUNDLE"

echo
echo "INSTALLAZIONE COMPLETATA"
echo "Apri 'Argo AI' da Finder > Applicazioni (cartella Inizio) o con Spotlight."
if ! command -v ollama >/dev/null && [ ! -d /Applications/Ollama.app ]; then
  echo
  echo "NOTA: per Verbale, Documenti, Dettatura e Traduzione serve Ollama: scaricalo da https://ollama.com"
fi
echo "Al primo avvio inserisci il token Hugging Face nelle Impostazioni."
open -R "$BUNDLE"
read -r -p "Premi Invio per chiudere..."
