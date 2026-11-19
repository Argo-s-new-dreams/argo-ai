#!/bin/bash
# Doppio clic (tasto destro > Apri) per disinstallare Argo da macOS. Lo script vero e' in app/disinstallatore/:
# lo stesso che parte dal pulsante «Disinstalla Argo…» nelle Impostazioni di Argo.
DIR="$(cd "$(dirname "$0")" && pwd)"
for s in "$DIR/app/disinstallatore/disinstalla_mac.sh" "$DIR/disinstalla_mac.sh"; do
  [ -f "$s" ] && exec bash "$s"
done
echo "Non trovo disinstalla_mac.sh: usa la cartella completa di Argo (argo-ai-main) oppure il pulsante"
echo "«Disinstalla Argo…» in Argo > Impostazioni > Aspetto e aggiornamenti."
read -r -p "Premi Invio per chiudere..."
