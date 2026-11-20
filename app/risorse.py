"""risorse.py - quanto computer può usare Argo (core, priorità, memoria).

Sui PC con poca CPU o poca RAM, WhisperX e Ollama di base prendono tutti i core e il sistema si blocca.
Qui si decide un profilo (Leggero, Bilanciato, Massima velocità; «Automatico» lo sceglie in base al computer)
e se ne ricavano:
    - quanti thread usare (WhisperX/PyTorch, faster-whisper, Ollama);
    - la priorità dei processi di calcolo (sotto il normale: mouse, Teams e Office restano reattivi);
    - nel profilo Leggero, un lavoro pesante alla volta (trascrizione O modello linguistico, mai insieme)
      e il modello di Ollama tolto dalla memoria prima di una trascrizione.
Solo libreria standard.
"""
import contextlib
import ctypes
import json
import os
import sys
import threading
import urllib.request

PROFILI = [
    ("auto", "Automatico (consigliato)"),
    ("leggero", "Leggero · il PC resta libero, Argo è più lento"),
    ("bilanciato", "Bilanciato"),
    ("massimo", "Massima velocità · Argo usa quasi tutto il PC"),
]
NOMI = {"leggero": "Leggero", "bilanciato": "Bilanciato", "massimo": "Massima velocità"}

# Windows: classi di priorità (i processi figli le ereditano)
_WIN_SOTTO_NORMALE = 0x00004000
_WIN_NORMALE = 0x00000020
_NICE = {"leggero": 15, "bilanciato": 8, "massimo": 0}

_turno = threading.RLock()


# ---------------------------------------------------------------- il computer
def core_logici():
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        n = os.cpu_count() or 2
    return max(1, n)


def ram_gb():
    """RAM installata in GB (0 se non si riesce a leggerla)."""
    try:
        if os.name == "nt":
            class Stato(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = Stato()
            st.dwLength = ctypes.sizeof(Stato)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 ** 3
    except Exception:
        return 0


def limite_modello_gb(margine=0.75):
    """Dimensione massima (GB sul disco) di un modello di Ollama che sta nella RAM di questo computer insieme al
    sistema e ad Argo; 0 se la RAM non si legge. 8 GB → 6 GB (gemma3:4b sì, gemma3:12b no); 16 GB → 12 GB."""
    ram = ram_gb()
    return ram * margine if ram else 0


def modello_entra(byte, margine=0.75):
    """True se un modello di quella dimensione sul disco sta nella RAM (o se non si sa)."""
    limite = limite_modello_gb(margine)
    return not limite or not byte or byte / 1e9 <= limite


# ---------------------------------------------------------------- il profilo
def _impostazione():
    try:
        import voci_core
        return voci_core.carica_impostazioni().get("risorse", "auto")
    except Exception:
        return "auto"


def profilo_auto():
    """Leggero sui computer con 4 core logici o meno, o con 8 GB di RAM o meno; altrimenti Bilanciato."""
    ram = ram_gb()
    if core_logici() <= 4 or (0 < ram <= 8.5):
        return "leggero"
    return "bilanciato"


def profilo(scelta=None):
    scelta = scelta or _impostazione()
    return scelta if scelta in NOMI else profilo_auto()


def thread_lavoro(prof=None):
    """Quanti thread dare ai calcoli pesanti, lasciando core liberi al resto del sistema."""
    n = core_logici()
    prof = prof or profilo()
    if prof == "massimo":
        return max(1, n - 1)
    if prof == "bilanciato":
        return max(1, min(n - 1, n // 2))
    return max(1, min(n - 2, max(2, n // 3)))  # leggero: 4 core -> 2, 8 -> 2, 12 -> 4


def batch_whisper(prof=None):
    """Blocchi di audio elaborati insieme da WhisperX: meno = meno RAM."""
    return 4 if (prof or profilo()) == "leggero" else 8


def descrizione(scelta=None):
    """Frase per le Impostazioni: cosa ha visto Argo e cosa farà."""
    prof = profilo(scelta)
    ram = ram_gb()
    pc = f"{core_logici()} core" + (f", {ram:.0f} GB di RAM" if ram else "")
    origine = "scelto in automatico" if (scelta or _impostazione()) == "auto" else "scelto da te"
    cosa = f"Argo usa al massimo {thread_lavoro(prof)} core"
    if prof != "massimo":
        cosa += " con priorità bassa"
    if prof == "leggero":
        cosa += ", un lavoro pesante alla volta e libera la memoria di Ollama prima di trascrivere"
    return f"Questo computer: {pc}. Profilo {NOMI[prof]} ({origine}): {cosa}."


# ---------------------------------------------------------------- processi
def env_limiti(env=None, prof=None):
    """Variabili che limitano i thread delle librerie numeriche nei processi figli."""
    env = dict(os.environ if env is None else env)
    n = str(thread_lavoro(prof))
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
              "NUMEXPR_NUM_THREADS"):
        env[k] = n
    env["TOKENIZERS_PARALLELISM"] = "false"
    return env


def flag_windows(prof=None):
    """creationflags da aggiungere a subprocess.Popen su Windows (0 altrove)."""
    if os.name != "nt":
        return 0
    return _WIN_NORMALE if (prof or profilo()) == "massimo" else _WIN_SOTTO_NORMALE


def abbassa_priorita(pid, prof=None):
    """Mette un processo già avviato sotto la priorità normale. Non solleva mai errori."""
    prof = prof or profilo()
    if not pid or prof == "massimo":
        return
    try:
        if os.name == "nt":
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x0200, False, int(pid))  # PROCESS_SET_INFORMATION
            if h:
                k32.SetPriorityClass(h, _WIN_SOTTO_NORMALE)
                k32.CloseHandle(h)
        else:
            os.setpriority(os.PRIO_PROCESS, int(pid), _NICE[prof])
    except Exception:
        pass


def limita_questo_processo(prof=None):
    """Da chiamare all'inizio di un processo di calcolo (es. il motore Live): thread e priorità."""
    prof = prof or profilo()
    n = thread_lavoro(prof)
    for k, v in env_limiti({}, prof).items():
        os.environ[k] = v
    try:
        import torch
        torch.set_num_threads(n)
    except Exception:
        pass
    abbassa_priorita(os.getpid(), prof)
    return n


# ---------------------------------------------------------------- Ollama
def opzioni_ollama(opzioni=None, prof=None):
    """Aggiunge num_thread alle opzioni di una richiesta a Ollama (conta per la parte su CPU)."""
    opzioni = dict(opzioni or {})
    opzioni.setdefault("num_thread", thread_lavoro(prof))
    return opzioni


def keep_alive(prof=None):
    """Quanto Ollama tiene il modello in memoria dopo l'ultima richiesta."""
    return "1m" if (prof or profilo()) == "leggero" else "5m"


def libera_ollama(url=None):
    """Toglie dalla memoria i modelli caricati in Ollama (prima di una trascrizione pesante)."""
    if url is None:
        try:
            import voci_core
            url = voci_core.carica_impostazioni().get("ollama_url") or "http://localhost:11434"
        except Exception:
            url = "http://localhost:11434"
    base = url.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=2) as r:
            modelli = [m.get("name") for m in json.load(r).get("models", []) if m.get("name")]
        for nome in modelli:
            dati = json.dumps({"model": nome, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(base + "/api/generate", data=dati,
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).close()
    except Exception:
        pass  # Ollama spento o non raggiungibile: niente da liberare


# ---------------------------------------------------------------- un lavoro pesante alla volta
@contextlib.contextmanager
def turno(on_attesa=None, prof=None):
    """Nel profilo Leggero fa aspettare il proprio turno ai lavori pesanti (trascrizione, modello linguistico).

    Negli altri profili non fa nulla. Rientrante: lo stesso thread può annidare più turni.
    """
    if (prof or profilo()) != "leggero":
        yield
        return
    if not _turno.acquire(blocking=False):
        if on_attesa:
            try:
                on_attesa("In attesa: c'è già un'altra elaborazione AI in corso (profilo Leggero)…")
            except Exception:
                pass
        _turno.acquire()
    try:
        yield
    finally:
        _turno.release()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print(descrizione())
