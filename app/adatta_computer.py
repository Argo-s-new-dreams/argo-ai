"""adatta_computer.py - «Adatta a questo computer»: legge com'è fatto il computer e propone la configurazione giusta.

Guarda sistema, processore, core, RAM e scheda NVIDIA; poi confronta con le impostazioni e propone solo i cambi
utili, ciascuno con il motivo:
    - Uso del computer: Automatico, se la scelta manuale non va d'accordo con il computer;
    - Calcolo su: GPU NVIDIA solo se c'è la scheda e PyTorch è la versione per CUDA; CPU se la GPU non c'è;
    - Modello di trascrizione: large-v3-turbo invece di large-v3 sui computer leggeri (stessa lingua, molto più
      veloce); di nuovo large-v3-turbo se è scelto un modello piccolo su un computer che regge di più;
    - Modelli di Ollama (testi, foto, documenti): il migliore installato che sta nella RAM (risorse.modello_entra);
      se nessun modello per i testi ci sta, propone di scaricare quello consigliato.
Nessuna interfaccia (la usa trascrittore.py); le parti con Ollama fanno chiamate di rete: da un thread.
"""
import importlib.metadata
import platform
import shutil
import subprocess
import sys

import llm_locale as llm
import modelli_ollama
import risorse

PREFERITI_EMBED = ("bge-m3", "nomic-embed", "mxbai-embed")


def _chip():
    try:
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        return platform.processor() or platform.machine()
    except Exception:
        return platform.machine()


def _nvidia():
    """Nome della scheda NVIDIA, o ''."""
    if sys.platform == "darwin" or not shutil.which("nvidia-smi"):
        return ""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        riga = (r.stdout or "").strip().splitlines()
        return riga[0].split(":", 1)[1].split("(")[0].strip() if riga and ":" in riga[0] else ""
    except Exception:
        return ""


def _torch_cuda():
    try:
        return "+cu" in importlib.metadata.version("torch")
    except Exception:
        return False


def computer():
    """Com'è fatto il computer: dict con sistema, chip, core, ram, nvidia, torch_cuda, profilo_auto."""
    sistema = {"darwin": "macOS " + platform.mac_ver()[0], "win32": "Windows " + platform.release()}.get(
        sys.platform, platform.system())
    return {"sistema": sistema, "chip": _chip(), "core": risorse.core_logici(), "ram": risorse.ram_gb(),
            "nvidia": _nvidia(), "torch_cuda": _torch_cuda(), "profilo_auto": risorse.profilo_auto()}


def descrivi(pc):
    parti = [pc["sistema"], pc["chip"], f"{pc['core']} core", f"{pc['ram']:.0f} GB di RAM" if pc["ram"] else ""]
    if pc["nvidia"]:
        parti.append(f"GPU {pc['nvidia']}")
    return " · ".join(p for p in parti if p)


def leggero(pc):
    return pc["core"] <= 4 or (0 < pc["ram"] < 12)


def _proposta(chiave, ruolo, attuale, nuovo, motivo):
    return {"chiave": chiave, "ruolo": ruolo, "attuale": attuale, "nuovo": nuovo, "motivo": motivo}


def proposte(s, pc, ollama=None):
    """Elenco dei cambi consigliati. ollama = {"chat", "emb", "vision", "dim"} oppure None se non risponde."""
    out = []
    # uso del computer
    scelta = s.get("risorse", "auto")
    if scelta != "auto" and scelta != pc["profilo_auto"]:
        out.append(_proposta("risorse", "Uso del computer", risorse.NOMI.get(scelta, scelta), "auto",
                             f"con {pc['core']} core e {pc['ram']:.0f} GB Argo sceglierebbe "
                             f"«{risorse.NOMI.get(pc['profilo_auto'])}» e si adatta da solo se cambia qualcosa"))
    # calcolo su
    if s.get("device") == "cuda" and not pc["nvidia"]:
        out.append(_proposta("device", "Calcolo su", "GPU NVIDIA", "cpu", "su questo computer non c'è una GPU NVIDIA"))
    elif s.get("device") != "cuda" and pc["nvidia"] and pc["torch_cuda"]:
        out.append(_proposta("device", "Calcolo su", "CPU", "cuda",
                             f"c'è la GPU {pc['nvidia']} e PyTorch è la versione per CUDA: trascrizioni molto più veloci"))
    # modello di trascrizione
    modello = s.get("model", "large-v3")
    gpu = s.get("device") == "cuda" and pc["nvidia"]
    if modello == "large-v3" and leggero(pc) and not gpu:
        out.append(_proposta("model", "Modello di trascrizione", modello, "large-v3-turbo",
                             "su un computer con pochi core o poca RAM large-v3 è molto lento; turbo è più veloce "
                             "con una qualità di poco inferiore"))
    elif modello in ("medium", "small") and not leggero(pc):
        out.append(_proposta("model", "Modello di trascrizione", modello, "large-v3-turbo",
                             "questo computer regge un modello più preciso"))
    # modelli di Ollama
    if ollama and ollama.get("dim"):
        dim = ollama["dim"]
        for chiave, ruolo, candidati, preferiti in (
                ("modello_chat", "Modello per i testi", ollama.get("chat", []), modelli_ollama.PREFERITI),
                ("modello_vision", "Modello per le foto", ollama.get("vision", []), modelli_ollama.PREFERITI),
                ("modello_embed", "Modello per i documenti", ollama.get("emb", []), PREFERITI_EMBED)):
            attuale = s.get(chiave) or ""
            if chiave == "modello_vision" and s.get(chiave) == "":
                continue  # «solo il testo letto dall'iPhone»: scelta voluta
            nuovo = modelli_ollama.migliore(candidati, dim, preferiti)
            if not nuovo or nuovo == attuale:
                continue
            if attuale and dim.get(attuale) and not risorse.modello_entra(dim[attuale]):
                motivo = f"{attuale} è troppo grande per {pc['ram']:.0f} GB di RAM"
            elif attuale in candidati:
                if modelli_ollama.migliore([attuale, nuovo], dim, preferiti) != nuovo:
                    continue
                if risorse.profilo(s.get("risorse")) == "leggero" and dim.get(nuovo, 0) > dim.get(attuale, 0):
                    continue  # profilo Leggero: niente modelli più grandi, il computer deve restare libero
                motivo = f"è il migliore installato che sta nei {pc['ram']:.0f} GB di RAM"
            else:
                motivo = "nessun modello scelto (o non più installato)"
            out.append(_proposta(chiave, ruolo, attuale or "nessuno", nuovo, motivo))
        if modelli_ollama.troppo_grandi(ollama.get("chat", []), dim) or not ollama.get("chat"):
            out.append(_proposta("scarica", "Da scaricare", "", modelli_ollama.chat_consigliato(),
                                 "nessun modello per i testi installato sta in questa RAM"))
    return out


def leggi_ollama(url):
    """Modelli installati e dimensioni, solo se Ollama è su questo computer. None se non risponde."""
    if not llm.e_locale(url):
        return None
    try:
        chat, emb = llm.elenco_modelli(url)
    except llm.ErroreLLM:
        return None
    try:
        import relazione_incontro
        vision = relazione_incontro.modelli_vision(url)
    except Exception:
        vision = []
    return {"chat": chat, "emb": emb, "vision": vision, "dim": llm.dimensioni(url)}
