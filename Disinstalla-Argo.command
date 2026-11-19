#!/bin/bash
# Doppio clic per disinstallare Argo · Cassetta degli attrezzi AI da macOS.
# Toglie l'app e la cartella whisperx-env (programma e dati). Prima propone un backup.
# Non tocca Ollama, i suoi modelli, uv, FFmpeg e le cache dei modelli condivise con altri programmi.
APP="$HOME/whisperx-env"
BUNDLE="$HOME/Applications/Argo AI.app"
VECCHIO="$HOME/Applications/Trascrittore.app"
REGISTRAZIONI="$HOME/Documents/Argo"

fine() { echo; read -r -p "Premi Invio per chiudere..."; exit "${1:-0}"; }
si() { local r; read -r -p "$1 " r; [[ "$r" =~ ^[sS] ]]; }

echo "=== Disinstallazione di Argo · Cassetta degli attrezzi AI ==="
echo
echo "Verranno eliminati:"
[ -d "$BUNDLE" ] && echo "  - l'app: $BUNDLE"
[ -d "$VECCHIO" ] && echo "  - la vecchia app: $VECCHIO"
[ -d "$APP" ] && echo "  - programma e dati: $APP (impronte vocali, incontri, clienti, impostazioni, chiavi e token)"
if [ ! -d "$APP" ] && [ ! -d "$BUNDLE" ] && [ ! -d "$VECCHIO" ]; then
  echo "  niente: Argo non risulta installato per questo utente."
  fine 0
fi
echo
echo "Restano: Ollama e i suoi modelli, uv, FFmpeg, le cache ~/.cache/huggingface e ~/.cache/torch."
echo

si "Vuoi davvero disinstallare Argo? [s/N]" || { echo "Nessuna modifica."; fine 0; }

if [ -d "$APP" ] && si "Faccio prima un backup di voci, incontri, clienti e impostazioni sulla Scrivania? [s/N]"; then
  BACKUP="$HOME/Desktop/Argo-backup-$(date +%Y%m%d-%H%M)"
  mkdir -p "$BACKUP" || { echo "ERRORE: non riesco a creare $BACKUP. Mi fermo, non ho cancellato niente."; fine 1; }
  for cosa in voci incontri clienti glossario.csv documenti_indice.json documenti_indice.npy trascrittore_impostazioni.json; do
    [ -e "$APP/$cosa" ] && cp -R "$APP/$cosa" "$BACKUP/"
  done
  echo "  Backup in: $BACKUP"
  echo "  (token e chiavi API non sono nel backup: andranno reinseriti)"
fi

echo
echo "Chiudo Argo se è aperto..."
pkill -f "$APP/" 2>/dev/null
sleep 1

[ -d "$BUNDLE" ] && rm -rf "$BUNDLE" && echo "  Eliminata l'app Argo AI"
[ -d "$VECCHIO" ] && rm -rf "$VECCHIO" && echo "  Eliminata la vecchia app Trascrittore"
if [ -d "$APP" ]; then
  rm -rf "$APP" && echo "  Eliminata la cartella whisperx-env" || echo "  ATTENZIONE: non sono riuscito a eliminare tutto $APP"
fi

if [ -d "$REGISTRAZIONI" ] && si "Elimino anche le registrazioni archiviate in $REGISTRAZIONI? [s/N]"; then
  rm -rf "$REGISTRAZIONI" && echo "  Eliminate le registrazioni archiviate"
fi

echo
echo "Argo è stato disinstallato."
echo "Se vuoi liberare altro spazio, a mano:"
echo "  - modelli di Ollama: 'ollama list' per vederli, 'ollama rm <nome>' per toglierli"
echo "  - cache dei modelli di trascrizione: ~/.cache/huggingface e ~/.cache/torch (se nessun altro programma le usa)"
fine 0
