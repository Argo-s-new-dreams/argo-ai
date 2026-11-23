"""Screenshot per il manuale d'uso sul blog: Argo appena installato, senza dati reali.

  python strumenti/screenshot_manuale.py [cartella di uscita]

Avvia Argo senza schermo (offscreen) con una cartella dati nuova e vuota, un token finto e
aggiornamenti e Ollama spenti, poi fotografa le pagine principali e le categorie delle
Impostazioni. Nessun dato personale: è un'installazione nuova.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
APP = RADICE / "app"
USCITA = Path(sys.argv[1] if len(sys.argv) > 1 else RADICE / "docs/manuale").resolve()
LATO = (1440, 900)


def _nome(testo):
    import re
    import unicodedata
    testo = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", testo.lower()).strip("-")


def figlio():
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    import trascrittore as t
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    t.Finestra.prepara_ollama = lambda self: None  # niente Ollama né finestre di proposta
    t.Finestra.controlla_aggiornamenti = lambda self, *a, **k: None

    def scatta():
        app = QApplication.instance()
        f = next(w for w in app.topLevelWidgets() if isinstance(w, t.Finestra))
        f.resize(*LATO)
        USCITA.mkdir(parents=True, exist_ok=True)
        fatte = []

        def foto(nome):
            for _ in range(5):
                app.processEvents()
            f.grab().save(str(USCITA / f"{nome}.png"))
            fatte.append(nome)

        for i in range(f.tabs.count()):
            f.tabs.setCurrentIndex(i)
            foto(f"pagina-{i + 1:02d}-" + _nome(f.tabs.tabText(i)))
        f.tabs.setCurrentWidget(f.tab_imp)
        for n in range(f.nav_imp.count()):
            f.nav_imp.setCurrentRow(n)
            foto(f"impostazioni-{n + 1}")
        print("FATTE " + " ".join(fatte), flush=True)
        app.quit()

    mostra = t.Finestra.show

    def show(self):  # il timer va creato dopo QApplication, cioè dentro main()
        mostra(self)
        QTimer.singleShot(4000, scatta)

    t.Finestra.show = show
    t.main()


def main():
    if os.environ.get("ARGO_SCREENSHOT_FIGLIO"):
        return figlio()
    # Cartella utente finta, nuova e vuota: nei percorsi mostrati nessun dato vero.
    # ARGO_UTENTE_FINTO=/Users/utente dà percorsi da Mac (la cartella non deve esistere).
    utente = Path(os.environ.get("ARGO_UTENTE_FINTO") or Path(tempfile.mkdtemp(prefix="argo-manuale-")) / "utente")
    casa = utente / "whisperx-env"
    casa.mkdir(parents=True)
    env = dict(os.environ, HOME=str(utente), USERPROFILE=str(utente), TRASCRITTORE_HOME=str(casa), QT_QPA_PLATFORM="offscreen", ARGO_SCREENSHOT_FIGLIO="1",
               PYTHONUTF8="1")
    prepara = ("import voci_core as c; c.salva_token('hf_prova_automatica'); s = c.carica_impostazioni(); "
               "s['controlla_aggiornamenti'] = False; c.salva_impostazioni(s)")
    subprocess.run([sys.executable, "-c", prepara], cwd=APP, env=env, check=True)
    r = subprocess.run([sys.executable, __file__, str(USCITA)], env=env, timeout=600)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
