"""prova_avvio.py - avvia Argo davvero (come lo avvia l'utente) e controlla che arrivi alla finestra.

Usata dalla GitHub Action «Prova di avvio» su macOS e Windows, si può lanciare anche a mano:

    python strumenti/prova_avvio.py

Argo parte senza schermo (Qt offscreen), con una cartella dati vuota e temporanea, il controllo degli
aggiornamenti spento e un token finto; si chiude da solo dopo ARGO_PROVA_AVVIO secondi. La prova riesce se:
- il processo esce con codice 0 entro il tempo massimo;
- il registro di Argo (log/argo.log) dice «finestra aperta»;
- il registro non contiene «errore non gestito».
In ogni caso stampa il registro, così nel log della Action si vede cosa è successo.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
APP = RADICE / "app"
SECONDI_APERTA = 12
TEMPO_MASSIMO = 600  # il primo import di torch e WhisperX su un runner può essere lento


def main():
    for flusso in (sys.stdout, sys.stderr):  # Windows: la console della Action non è UTF-8
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    casa = Path(tempfile.mkdtemp(prefix="argo-prova-"))
    env = dict(os.environ, TRASCRITTORE_HOME=str(casa), QT_QPA_PLATFORM="offscreen",
               ARGO_PROVA_AVVIO=str(SECONDI_APERTA), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    # Impostazioni di partenza: token finto (niente finestra «Primo avvio»), aggiornamenti spenti
    prepara = ("import voci_core as c; c.salva_token('hf_prova_automatica'); s = c.carica_impostazioni(); "
               "s['controlla_aggiornamenti'] = False; c.salva_impostazioni(s)")
    subprocess.run([sys.executable, "-c", prepara], cwd=APP, env=env, check=True)

    print(f"Avvio di Argo ({sys.platform}, Python {sys.version.split()[0]}), cartella dati {casa}", flush=True)
    try:
        r = subprocess.run([sys.executable, str(APP / "trascrittore.py")], cwd=APP, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TEMPO_MASSIMO)
        codice, uscita = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        codice = None
        uscita = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
                 ((e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))

    registro = casa / "log" / "argo.log"
    testo = registro.read_text(encoding="utf-8", errors="replace") if registro.exists() else ""
    print("----- registro di Argo (log/argo.log) -----\n" + (testo or "(vuoto o assente)"))
    crash = casa / "log" / "crash.log"
    if crash.exists() and crash.stat().st_size:
        print("----- crash.log -----\n" + crash.read_text(encoding="utf-8", errors="replace"))
    if uscita.strip():
        print("----- uscita del processo (ultime 60 righe) -----\n" + "\n".join(uscita.splitlines()[-60:]))

    errori = []
    if codice is None:
        errori.append(f"Argo non si è chiuso entro {TEMPO_MASSIMO} s: forse aspetta una finestra modale")
    elif codice != 0:
        errori.append(f"Argo è uscito con codice {codice}")
    if "finestra aperta" not in testo:
        errori.append("il registro non dice «finestra aperta»: Argo non è arrivato alla finestra")
    if "errore non gestito" in testo:
        errori.append("il registro contiene un errore non gestito")
    if errori:
        print("\nPROVA NON RIUSCITA:\n- " + "\n- ".join(errori))
        return 1
    print("\nPROVA RIUSCITA: Argo arriva alla finestra e si chiude senza errori.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
