"""modelli_ollama.py - Ollama pronto all'avvio di Argo: acceso, con i modelli consigliati, già scelti.

Al primo avvio (o quando mancano) Argo propone di scaricare:
    - un modello per i testi che guarda anche le foto (gemma3: 4b sui PC leggeri, 12b con 16 GB di RAM o più);
    - un modello per i documenti (bge-m3, embedding).
Dopo il download li sceglie nelle Impostazioni; l'utente può cambiarli quando vuole.
Solo libreria standard; nessuna interfaccia (la usa trascrittore.py).
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import llm_locale as llm
import risorse

EMBED_CONSIGLIATO = "bge-m3"
DIMENSIONI_GB = {"gemma3:4b": 3.3, "gemma3:12b": 8.1, "bge-m3": 1.2}  # circa, come da ollama.com


def chat_consigliato():
    """gemma3:12b se il PC ha almeno 16 GB e non è in profilo Leggero, altrimenti gemma3:4b."""
    if risorse.profilo() != "leggero" and risorse.ram_gb() >= 15.5:
        return "gemma3:12b"
    return "gemma3:4b"


def _uguale(nome, voluto):
    """«gemma3:4b» installato come «gemma3:4b» o «gemma3:4b-it-qat»…; «bge-m3» come «bge-m3:latest»."""
    nome, voluto = nome.lower(), voluto.lower()
    return nome == voluto or nome.startswith(voluto + ":") or nome.startswith(voluto + "-") \
        or (":" not in voluto and nome.split(":")[0] == voluto)


PREFERITI = ("gemma3", "qwen3", "qwen2.5", "llama3", "mistral", "phi")


def troppo_grandi(chat, dim):
    """True se ci sono modelli per i testi ma nessuno sta nella RAM di questo computer."""
    return bool(chat) and bool(dim) and not any(risorse.modello_entra(dim.get(n, 0)) for n in chat)


def mancanti(chat, emb, dim=None):
    """Modelli consigliati da scaricare: per i ruoli senza alcun modello installato, e un modello per i testi
    adatto alla RAM quando quelli installati sono tutti troppo grandi."""
    da_scaricare = []
    if not chat or (troppo_grandi(chat, dim or {}) and not any(_uguale(n, chat_consigliato()) for n in chat)):
        da_scaricare.append(chat_consigliato())
    if not emb:
        da_scaricare.append(EMBED_CONSIGLIATO)
    return da_scaricare


def adatta(s, chat, vision, dim):
    """Legge com'è fatto il computer: se il modello scelto per i testi o per le foto non sta nella RAM, passa al
    migliore installato che ci sta (ordine di preferenza, poi il più grande). Modifica s; ritorna cosa ha cambiato."""
    cambiati = []

    def migliore(candidati):
        adatti = [n for n in candidati if dim.get(n) and risorse.modello_entra(dim[n])]
        rango = lambda n: (next((i for i, p in enumerate(PREFERITI) if n.lower().startswith(p)), len(PREFERITI)),
                           -dim.get(n, 0))
        return min(adatti, key=rango) if adatti else None

    for campo, candidati, ruolo in (("modello_chat", chat, "testi"), ("modello_vision", vision, "foto")):
        attuale = s.get(campo)
        if not attuale or not dim.get(attuale) or risorse.modello_entra(dim[attuale]):
            continue
        nuovo = migliore([c for c in candidati if c != attuale])
        if nuovo:
            s[campo] = nuovo
            cambiati.append(f"{ruolo}: {nuovo} al posto di {attuale}, troppo grande per {risorse.ram_gb():.0f} GB di RAM")
    return cambiati


def peso(nomi):
    return sum(DIMENSIONI_GB.get(n, 0) for n in nomi)


# ---------------------------------------------------------------- Ollama acceso
def _app_mac():
    """Ollama.app in /Applications o in ~/Applications (dove lo mette l'installer di Argo se serve)."""
    for base in (Path("/Applications"), Path.home() / "Applications"):
        if (base / "Ollama.app").exists():
            return base / "Ollama.app"
    return None


def _eseguibile():
    trovato = shutil.which("ollama")
    if trovato:
        return trovato
    candidati = []
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
        candidati = [base / "ollama.exe"]
    elif sys.platform == "darwin":
        candidati = [Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama"),
                     Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                     Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama"]
    else:
        candidati = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((str(c) for c in candidati if c.exists()), None)


def installato():
    return bool(_eseguibile()) or (sys.platform == "darwin" and _app_mac() is not None)


def avvia():
    """Prova ad accendere Ollama (l'app con l'icona, se c'è; altrimenti «ollama serve»). True se ha lanciato qualcosa."""
    nulla = subprocess.DEVNULL
    try:
        if sys.platform == "darwin" and _app_mac() is not None:
            subprocess.Popen(["/usr/bin/open", "-g", "-a", str(_app_mac())], stdin=nulla, stdout=nulla, stderr=nulla)
            return True
        exe = _eseguibile()
        if not exe:
            return False
        if os.name == "nt":
            app = Path(exe).with_name("ollama app.exe")  # l'icona nella barra: avvia anche il server
            cmd = [str(app)] if app.exists() else [exe, "serve"]
            subprocess.Popen(cmd, stdin=nulla, stdout=nulla, stderr=nulla, close_fds=True,
                             creationflags=0x00000008 | 0x00000200 | 0x08000000)  # staccato, senza finestra
        else:
            subprocess.Popen([exe, "serve"], stdin=nulla, stdout=nulla, stderr=nulla, start_new_session=True)
        return True
    except Exception:
        return False


def controlla(url, stato=lambda _t: None, attesa=30, stop=None):
    """Ollama acceso? Se è spento prova ad avviarlo e aspetta fino a `attesa` secondi.

    Ritorna {"esito": "ok" | "assente" | "spento", "chat": [...], "emb": [...]}.
    """
    try:
        chat, emb = llm.elenco_modelli(url)
        return {"esito": "ok", "chat": chat, "emb": emb}
    except llm.ErroreLLM:
        pass
    if not llm.e_locale(url):  # server Ollama su un altro computer: non tocca a noi accenderlo
        return {"esito": "spento", "chat": [], "emb": []}
    if not installato():
        return {"esito": "assente", "chat": [], "emb": []}
    stato("Avvio Ollama…")
    if not avvia():
        return {"esito": "spento", "chat": [], "emb": []}
    fine = time.time() + attesa
    while time.time() < fine:
        if stop and stop():
            break
        time.sleep(1)
        try:
            chat, emb = llm.elenco_modelli(url)
            return {"esito": "ok", "chat": chat, "emb": emb}
        except llm.ErroreLLM:
            continue
    return {"esito": "spento", "chat": [], "emb": []}


def scarica(nomi, url, stato=lambda _t: None, stop=None):
    """Scarica i modelli uno dopo l'altro. Ritorna l'elenco di quelli scaricati."""
    fatti = []
    for i, nome in enumerate(nomi, 1):
        if stop and stop():
            break
        prefisso = f"Scarico {nome} ({i} di {len(nomi)}"
        prefisso += f", circa {DIMENSIONI_GB[nome]:.1f} GB): " if nome in DIMENSIONI_GB else "): "
        if llm.scarica_modello(nome, url, on_stato=lambda t, p=prefisso: stato(p + t), stop=stop):
            fatti.append(nome)
    return fatti
