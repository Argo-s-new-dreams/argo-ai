"""criteri.py - criteri aziendali di Argo, impostati dall'IT (per esempio via Intune o Jamf).

Un file JSON in una cartella di sistema, scrivibile solo dall'amministratore, che ha la precedenza sulle
impostazioni dell'utente. Se il file non c'è, Argo si comporta come sempre.

    macOS    /Library/Application Support/Argo/criteri.json
    Windows  %ProgramData%\\Argo\\criteri.json
    Linux    /etc/argo/criteri.json
    (per le prove: variabile d'ambiente ARGO_CRITERI con il percorso del file)

Chiavi riconosciute (tutte facoltative):
    "canale_aggiornamenti":  "pro" | "lab"   blocca il canale e lo rende non modificabile
    "aggiornamenti_dall_app": false          Argo non controlla e non installa aggiornamenti da solo
                                             (li distribuisce l'IT)
"""
import json
import os
import sys
from pathlib import Path

CHIAVI = {"canale_aggiornamenti", "aggiornamenti_dall_app"}


def percorso():
    if os.environ.get("ARGO_CRITERI"):
        return Path(os.environ["ARGO_CRITERI"])
    if sys.platform == "darwin":
        return Path("/Library/Application Support/Argo/criteri.json")
    if os.name == "nt":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Argo" / "criteri.json"
    return Path("/etc/argo/criteri.json")


def carica():
    """Ritorna i criteri validi (dict, eventualmente vuoto). Un file illeggibile vale come assente."""
    try:
        dati = json.loads(percorso().read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(dati, dict):
        return {}
    criteri = {k: v for k, v in dati.items() if k in CHIAVI}
    if criteri.get("canale_aggiornamenti") not in (None, "lab", "pro"):
        criteri.pop("canale_aggiornamenti")
    if "aggiornamenti_dall_app" in criteri and not isinstance(criteri["aggiornamenti_dall_app"], bool):
        criteri.pop("aggiornamenti_dall_app")
    return criteri


def gestito():
    """True se c'è almeno un criterio aziendale attivo."""
    return bool(carica())
