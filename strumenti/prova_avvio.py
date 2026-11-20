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
    # Modelli di allineamento con licenza commerciale (whisperx_argo.py) sul WhisperX vero
    controllo = ("import whisperx_argo as w; w.applica(); import whisperx.alignment as a; "
                 "assert all(l not in a.DEFAULT_ALIGN_MODELS_TORCH for l in w.MODELLI_ALLINEAMENTO), "
                 "'VoxPopuli ancora tra i predefiniti'; "
                 "assert all(a.DEFAULT_ALIGN_MODELS_HF.get(l) == m for l, m in w.MODELLI_ALLINEAMENTO.items()); "
                 "print('allineamento: ' + ', '.join(l + ' = ' + m for l, m in w.MODELLI_ALLINEAMENTO.items()))")
    r2 = subprocess.run([sys.executable, "-c", controllo], cwd=APP, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    print("----- modelli di allineamento -----\n" + (r2.stdout + r2.stderr).strip())
    if r2.returncode != 0:
        errori.append("i modelli di allineamento non sono quelli con licenza commerciale")
    r3 = subprocess.run([sys.executable, str(APP / "whisperx_argo.py"), "--help"], cwd=APP, env=env,
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r3.returncode != 0 or "--align_model" not in r3.stdout:
        errori.append("whisperx_argo.py non avvia la riga di comando di WhisperX")
        print((r3.stdout + r3.stderr)[-2000:])
    # Blocco della sospensione durante i lavori (veglia.py): caffeinate sul Mac, SetThreadExecutionState su Windows
    controllo_veglia = (
        "import sys, time, veglia\n"
        "with veglia.tieni('prova'):\n"
        "    time.sleep(1)\n"
        "    if sys.platform == 'darwin':\n"
        "        assert veglia._mac is not None and veglia._mac.poll() is None, 'caffeinate non attivo'\n"
        "    elif sys.platform == 'win32':\n"
        "        assert veglia._win is not None and veglia._win[0].is_alive(), 'thread di veglia non attivo'\n"
        "assert veglia._mac is None and veglia._win is None and not veglia.attivi(), 'blocco non rilasciato'\n"
        "print('veglia: blocco della sospensione preso e rilasciato')\n")
    r4 = subprocess.run([sys.executable, "-c", controllo_veglia], cwd=APP, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=60)
    print("----- veglia -----\n" + (r4.stdout + r4.stderr).strip())
    if r4.returncode != 0:
        errori.append("il blocco della sospensione durante i lavori non funziona")
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
