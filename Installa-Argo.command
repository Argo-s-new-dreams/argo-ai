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
passo 1 "Strumenti di base (uv, FFmpeg)"
# Homebrew non e' piu' obbligatorio: se c'e' lo uso, altrimenti scarico uv dal sito ufficiale
# e prendo FFmpeg da un pacchetto Python (imageio-ffmpeg) dentro l'ambiente di Argo.
for b in /opt/homebrew/bin/brew /usr/local/bin/brew "$HOME/.homebrew/bin/brew"; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
export PATH="$HOME/.local/bin:$PATH"
if command -v brew >/dev/null; then
  echo "  Homebrew trovato: lo uso per FFmpeg e uv."
  command -v ffmpeg >/dev/null || brew install ffmpeg || echo "  (ffmpeg via Homebrew non riuscito: uso il pacchetto Python)"
  command -v uv >/dev/null || brew install uv || echo "  (uv via Homebrew non riuscito: provo il sito ufficiale)"
fi
if ! command -v uv >/dev/null; then
  echo "  Scarico uv da astral.sh (installer ufficiale, nella tua cartella utente)..."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh || errore "installazione di uv non riuscita (serve la connessione a Internet)"
fi
command -v uv >/dev/null || errore "uv non trovato dopo l'installazione"

passo 2 "Ambiente Python"
if [ -x "$APP/bin/python" ]; then
  echo "  Ambiente esistente riutilizzato (voci e token restano)."
else
  uv venv "$APP" --python 3.12 --allow-existing || errore "creazione dell'ambiente Python non riuscita"
fi

passo 3 "WhisperX e interfaccia grafica (5-15 minuti la prima volta)"
uv pip install --python "$APP/bin/python" whisperx hf_xet PySide6 pypdf python-docx sounddevice || errore "installazione dei pacchetti non riuscita"
if ! command -v ffmpeg >/dev/null; then
  echo "  FFmpeg non presente: lo prendo dal pacchetto imageio-ffmpeg"
  uv pip install --python "$APP/bin/python" imageio-ffmpeg || errore "installazione di FFmpeg non riuscita"
  FF="$("$APP/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" || errore "FFmpeg non trovato nel pacchetto"
  ln -sf "$FF" "$APP/bin/ffmpeg" || errore "collegamento a FFmpeg non riuscito"
fi
PATH="$APP/bin:$PATH" ffmpeg -version >/dev/null 2>&1 || errore "FFmpeg non funziona"
echo "  FFmpeg pronto: $(PATH="$APP/bin:$PATH" command -v ffmpeg)"

passo 4 "Copia dell'applicazione"
mkdir -p "$APP/app"
cp -R "$DIR/app/." "$APP/app/" || errore "copia dei file non riuscita"

passo 5 "Creazione di Argo AI.app in ~/Applications"
VERSIONE="$(sed -n 's/^VERSIONE = "\(.*\)"/\1/p' "$APP/app/trascrittore.py")"
[ -d "$VECCHIO" ] && rm -rf "$VECCHIO" && echo "  Rimossa la vecchia Trascrittore.app"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cat > "$BUNDLE/Contents/MacOS/ArgoAI" <<EOF
#!/bin/bash
# Le app aperte dal Finder non vedono il PATH del Terminale: aggiungo l'ambiente di Argo (ffmpeg) e Homebrew.
export PATH="$APP/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
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
  <key>CFBundleVersion</key><string>$VERSIONE</string>
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
