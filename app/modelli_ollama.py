"""modelli_ollama.py - Ollama pronto all'avvio di Argo: acceso, con i modelli consigliati, già scelti.

Al primo avvio (o quando mancano) Argo propone di scaricare:
    - un modello per i testi che guarda anche le foto (gemma3: 4b sui PC leggeri, 12b con 16 GB di RAM o più);
    - un modello per i documenti (bge-m3, embedding).
Dopo il download li sceglie nelle Impostazioni; l'utente può cambiarli quando vuole.

Acceso e spento (richiesta di Luca, 22/11/2026): se Ollama è spento Argo lo avvia (Mac: Ollama.app, altrimenti
«ollama serve»; Windows: «ollama app.exe», l'icona nella barra, altrimenti «ollama serve») e se lo ricorda in
un segnalino (ollama_avviato.json) che vale fino al riavvio del computer. Alla chiusura di Argo, secondo
l'impostazione «ollama_alla_chiusura»:
    - "se_avviato" (predefinita): lo ferma solo se l'ha acceso Argo;
    - "sempre": lo ferma comunque;
    - "mai": lo lascia acceso, perché lo usano anche altri programmi; in questo caso Argo libera la memoria solo
      dei propri modelli (risorse.libera_ollama).
Mai un Ollama su un altro computer.
Solo libreria standard; nessuna interfaccia (la usa trascrittore.py).
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import llm_locale as llm
import risorse
import voci_core as core

log = logging.getLogger("argo")

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


def migliore(candidati, dim, preferiti=PREFERITI):
    """Il modello migliore che sta nella RAM: ordine di preferenza, poi il più grande. None se nessuno ci sta."""
    adatti = [n for n in candidati if dim.get(n) and risorse.modello_entra(dim[n])]

    def rango(n):
        return (next((i for i, p in enumerate(preferiti) if n.lower().startswith(p)), len(preferiti)), -dim.get(n, 0))
    return min(adatti, key=rango) if adatti else None


def adatta(s, chat, vision, dim):
    """Legge com'è fatto il computer: se il modello scelto per i testi o per le foto non sta nella RAM, passa al
    migliore installato che ci sta (ordine di preferenza, poi il più grande). Modifica s; ritorna cosa ha cambiato."""
    cambiati = []
    for campo, candidati, ruolo in (("modello_chat", chat, "testi"), ("modello_vision", vision, "foto")):
        attuale = s.get(campo)
        if not attuale or not dim.get(attuale) or risorse.modello_entra(dim[attuale]):
            continue
        nuovo = migliore([c for c in candidati if c != attuale], dim)
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


SENZA_FINESTRA = 0x08000000
SEGNALINO = core.APP_HOME / "ollama_avviato.json"
SCELTE_CHIUSURA = ("se_avviato", "sempre", "mai")
_processo = None  # «ollama serve» lanciato da questa sessione di Argo


def _avvio_sistema():
    """Ora (time.time) dell'ultimo avvio del computer, o 0 se non si sa."""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000
        if sys.platform == "darwin":
            r = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5)
            return float(r.stdout.split("sec =")[1].split(",")[0])
        return time.time() - float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return 0.0


def _segna(come):
    try:
        SEGNALINO.parent.mkdir(parents=True, exist_ok=True)
        SEGNALINO.write_text(json.dumps({"come": come, "quando": time.time()}), encoding="utf-8")
    except OSError:
        pass


def avviato_da_argo():
    """Come l'ha acceso Argo ("app" o "serve"), o "" se Ollama non l'ha acceso Argo (o il computer si è riavviato
    da allora, e quindi l'ha acceso qualcun altro)."""
    try:
        dati = json.loads(SEGNALINO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if dati.get("quando", 0) < _avvio_sistema() - 60:
        SEGNALINO.unlink(missing_ok=True)
        return ""
    return dati.get("come", "")


def avvia():
    """Prova ad accendere Ollama (l'app con l'icona, se c'è; altrimenti «ollama serve»). True se ha lanciato qualcosa."""
    global _processo
    nulla = subprocess.DEVNULL
    try:
        if sys.platform == "darwin" and _app_mac() is not None:
            subprocess.Popen(["/usr/bin/open", "-g", "-a", str(_app_mac())], stdin=nulla, stdout=nulla, stderr=nulla)
            _segna("app")
            return True
        exe = _eseguibile()
        if not exe:
            return False
        if os.name == "nt":
            app = Path(exe).with_name("ollama app.exe")  # l'icona nella barra: avvia anche il server
            cmd = [str(app)] if app.exists() else [exe, "serve"]
            processo = subprocess.Popen(cmd, stdin=nulla, stdout=nulla, stderr=nulla, close_fds=True,
                                        creationflags=0x00000008 | 0x00000200 | SENZA_FINESTRA)  # staccato
            _segna("app" if app.exists() else "serve")
        else:
            processo = subprocess.Popen([exe, "serve"], stdin=nulla, stdout=nulla, stderr=nulla, start_new_session=True)
            _segna("serve")
        _processo = processo
        log.info("Ollama avviato da Argo")
        return True
    except Exception as e:
        log.warning("Ollama non avviato: %s", e)
        return False


def _esegui(cmd):
    try:
        subprocess.run(cmd, capture_output=True, timeout=15, creationflags=SENZA_FINESTRA if os.name == "nt" else 0)
    except Exception:
        pass


def ferma():
    """Spegne Ollama su questo computer (app e server). True se dopo non risponde più."""
    global _processo
    if sys.platform == "darwin":
        if _app_mac() is not None:
            _esegui(["/usr/bin/osascript", "-e", 'tell application "Ollama" to quit'])
        _esegui(["/usr/bin/pkill", "-x", "ollama"])  # «ollama serve» lanciato da Argo o da un terminale
    elif os.name == "nt":
        _esegui(["taskkill", "/IM", "ollama app.exe", "/T", "/F"])
        _esegui(["taskkill", "/IM", "ollama.exe", "/T", "/F"])
    else:
        _esegui(["pkill", "-x", "ollama"])
    if _processo is not None:
        try:
            _processo.terminate()
            _processo.wait(5)
        except Exception:
            pass
        _processo = None
    url = core.carica_impostazioni().get("ollama_url") or llm.DEFAULT_URL
    for _ in range(10):
        try:
            llm.elenco_modelli(url)
        except llm.ErroreLLM:
            SEGNALINO.unlink(missing_ok=True)
            log.info("Ollama fermato alla chiusura di Argo")
            return True
        time.sleep(0.5)
    log.warning("Ollama ancora acceso dopo il tentativo di fermarlo")
    return False


def scelta_chiusura(s=None):
    v = (s or core.carica_impostazioni()).get("ollama_alla_chiusura", "se_avviato")
    return v if v in SCELTE_CHIUSURA else "se_avviato"


def condiviso(s=None):
    """True se l'utente ha detto che Ollama lo usano anche altri programmi."""
    return scelta_chiusura(s) == "mai"


def alla_chiusura():
    """Dalla chiusura di Argo: ferma Ollama secondo l'impostazione. Ritorna True se l'ha fermato."""
    s = core.carica_impostazioni()
    if not llm.e_locale(s.get("ollama_url") or llm.DEFAULT_URL):
        return False
    scelta = scelta_chiusura(s)
    if scelta == "mai" or (scelta == "se_avviato" and not avviato_da_argo()):
        return False
    try:
        llm.elenco_modelli(s.get("ollama_url") or llm.DEFAULT_URL)
    except llm.ErroreLLM:
        SEGNALINO.unlink(missing_ok=True)  # già spento
        return False
    return ferma()


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
