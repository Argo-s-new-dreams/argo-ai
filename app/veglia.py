"""veglia.py - tiene sveglio il computer mentre Argo lavora e si accorge se è andato in sospensione.

Una trascrizione lunga, una registrazione o una relazione si interrompono se il computer va in sospensione
(il processo di WhisperX si ferma, l'audio si perde, la connessione a Ollama cade). Finché c'è almeno un
lavoro in corso, Argo chiede al sistema di non andare in sospensione da solo:
    - Mac: «caffeinate -i -m -s -w <pid di Argo>» (se Argo si chiude o si blocca, caffeinate si chiude da sé);
    - Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) da un thread dedicato.
Lo schermo può spegnersi lo stesso. Il coperchio chiuso o il tasto di accensione mandano comunque il computer
in sospensione: lì nessuna app può (né deve) opporsi. Per questo c'è anche un controllo che si accorge di una
sospensione avvenuta (l'orologio salta in avanti) e ne lascia traccia: chi gestisce il lavoro può dire
all'utente cosa è successo o rimetterlo in coda.

Uso:
    with veglia.tieni("trascrizione"):
        ...
    veglia.trattieni("registrazione") ... veglia.lascia("registrazione")
    veglia.sospeso_dal(t_inizio)  -> secondi di sospensione dopo t_inizio (0 se nessuna)
Solo libreria standard.
"""
import contextlib
import itertools
import logging
import os
import subprocess
import sys
import threading
import time

log = logging.getLogger("argo")

_lock = threading.Lock()
_motivi = {}             # chiave -> motivo
_contatore = itertools.count(1)
_mac = None              # processo caffeinate
_win = None              # (thread, evento) su Windows
_sospensioni = []        # (inizio, fine) in tempo di orologio, le ultime 20
_sorveglianza = None
_ultimo_controllo = None  # l'ultima volta che il controllo dell'orologio è passato

_PASSO = 5               # secondi tra un controllo dell'orologio e il successivo
_SALTO = 45              # oltre questo ritardo il computer ha dormito


# ---------------------------------------------------------------- blocco della sospensione
def _blocca():
    global _mac, _win
    if sys.platform == "darwin":
        try:
            _mac = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-m", "-s", "-w", str(os.getpid())],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except Exception as e:
            log.warning("veglia: caffeinate non avviato · %s", e)
            _mac = None
    elif os.name == "nt":
        evento = threading.Event()
        t = threading.Thread(target=_tieni_windows, args=(evento,), name="argo-veglia", daemon=True)
        t.start()
        _win = (t, evento)


def _sblocca():
    global _mac, _win
    if _mac is not None:
        try:
            _mac.terminate()
            _mac.wait(3)
        except Exception:
            with contextlib.suppress(Exception):
                _mac.kill()
        _mac = None
    if _win is not None:
        _win[1].set()
        _win = None


def _tieni_windows(evento):
    """Lo stato vale per il thread che lo imposta: questo thread resta vivo finché serve."""
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    kernel = ctypes.windll.kernel32
    kernel.SetThreadExecutionState.restype = ctypes.c_uint
    if not kernel.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
        log.warning("veglia: SetThreadExecutionState non accettato")
    evento.wait()
    kernel.SetThreadExecutionState(ES_CONTINUOUS)


def trattieni(chiave, motivo=None):
    """Inizia un lavoro che non deve essere interrotto dalla sospensione. Chiamarla due volte non fa danni."""
    _sorveglia()
    with _lock:
        if chiave in _motivi:
            return
        primo = not _motivi
        _motivi[chiave] = motivo or chiave
        if primo:
            _blocca()
    if primo:
        log.info("veglia: sospensione automatica bloccata · %s", motivo or chiave)


def lascia(chiave):
    """Fine del lavoro: quando non ne resta nessuno, il computer può di nuovo andare in sospensione."""
    with _lock:
        if _motivi.pop(chiave, None) is None:
            return
        ultimo = not _motivi
        if ultimo:
            _sblocca()
    if ultimo:
        log.info("veglia: sospensione automatica di nuovo consentita")


@contextlib.contextmanager
def tieni(motivo):
    chiave = f"{motivo}#{next(_contatore)}"
    trattieni(chiave, motivo)
    try:
        yield
    finally:
        lascia(chiave)


def attivi():
    with _lock:
        return sorted(set(_motivi.values()))


# ---------------------------------------------------------------- sospensioni avvenute
def _sorveglia():
    global _sorveglianza
    with _lock:
        if _sorveglianza is not None:
            return
        _sorveglianza = threading.Thread(target=_controlla_orologio, name="argo-sospensioni", daemon=True)
        _sorveglianza.start()


def _controlla_orologio():
    global _ultimo_controllo
    prima = _ultimo_controllo = time.time()
    while True:
        time.sleep(_PASSO)
        ora = time.time()
        if ora - prima > _SALTO:
            with _lock:
                _sospensioni.append((prima + _PASSO, ora))
                del _sospensioni[:-20]
                in_corso = sorted(set(_motivi.values()))
            log.warning("veglia: il computer è stato in sospensione per circa %d min%s", round((ora - prima) / 60),
                        f" durante: {', '.join(in_corso)}" if in_corso else "")
        prima = _ultimo_controllo = ora


def sospeso_dal(inizio):
    """Secondi passati in sospensione dopo «inizio» (time.time()); 0 se il computer non ha dormito."""
    ora = time.time()
    with _lock:
        totale = sum(fine - max(ini, inizio) for ini, fine in _sospensioni if fine > inizio)
        # appena risvegliato: il controllo dell'orologio non è ancora ripassato, ma il salto si vede già
        if _ultimo_controllo is not None and ora - _ultimo_controllo > _SALTO and ora > inizio:
            totale += ora - max(_ultimo_controllo + _PASSO, inizio)
    return totale
