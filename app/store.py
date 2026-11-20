"""store.py - Argo installato dal Microsoft Store (pacchetto MSIX).

Nel pacchetto MSIX la cartella del programma è in sola lettura e gli aggiornamenti li porta lo Store:
qui si capisce se Argo gira da lì e si preparano gli strumenti inclusi nel pacchetto (FFmpeg).

    DA_STORE      True se Argo è stato avviato da un pacchetto MSIX (Store o installazione di prova)
    prepara()     da chiamare all'avvio: mette sul PATH le cartelle degli strumenti inclusi

Per provare il comportamento senza pacchetto: variabile d'ambiente ARGO_STORE=1.
"""
import os
from pathlib import Path

QUI = Path(__file__).resolve().parent
RADICE_PACCHETTO = QUI.parent          # nel pacchetto: <radice>\app, <radice>\python, <radice>\strumenti
CARTELLE_STRUMENTI = ("strumenti\\ffmpeg\\bin",)
APPMODEL_ERROR_NO_PACKAGE = 15700
ERROR_INSUFFICIENT_BUFFER = 122


def _nome_pacchetto():
    """Nome completo del pacchetto MSIX in cui gira il processo, o None se non è impacchettato."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        lunghezza = ctypes.c_uint32(0)
        funz = ctypes.windll.kernel32.GetCurrentPackageFullName
        r = funz(ctypes.byref(lunghezza), None)
        if r == APPMODEL_ERROR_NO_PACKAGE or r != ERROR_INSUFFICIENT_BUFFER:
            return None
        buf = ctypes.create_unicode_buffer(lunghezza.value)
        if funz(ctypes.byref(lunghezza), buf) != 0:
            return None
        return buf.value or None
    except Exception:  # Windows vecchio o API assente: non è un pacchetto MSIX
        return None


NOME_PACCHETTO = _nome_pacchetto()
DA_STORE = bool(NOME_PACCHETTO) or os.environ.get("ARGO_STORE") == "1"

MESSAGGIO_AGGIORNAMENTI = ("Argo arriva dal Microsoft Store: gli aggiornamenti li installa lo Store "
                           "(Microsoft Store › Raccolta › Ottieni aggiornamenti).")
MESSAGGIO_DISINSTALLA = ("Argo arriva dal Microsoft Store: si disinstalla da Impostazioni di Windows › App › "
                         "App installate › Argo AI › Disinstalla. Voci, impostazioni e documenti nella cartella "
                         "whisperx-env restano finché non li cancelli tu.")


def prepara():
    """Mette sul PATH (solo per Argo e i suoi processi) gli strumenti inclusi nel pacchetto."""
    if not DA_STORE:
        return
    aggiunte = [str(RADICE_PACCHETTO / c) for c in CARTELLE_STRUMENTI if (RADICE_PACCHETTO / c).is_dir()]
    if aggiunte:
        os.environ["PATH"] = os.pathsep.join(aggiunte + [os.environ.get("PATH", "")])
