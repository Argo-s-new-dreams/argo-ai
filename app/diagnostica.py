"""diagnostica.py - registro locale di Argo, modalità trace, avvio protetto e ritorno alla versione precedente.

Regole (vedi docs/MANUALE.md, «Supporto e diagnostica»):
- i log restano su questo computer, in APP_HOME/log/, e non escono mai da soli: solo se l'utente li manda
  con «Chiedi supporto», dopo averli visti;
- non contengono contenuti: niente audio, testi trascritti, prompt e risposte dei modelli, nomi dei file degli
  utenti (solo estensione e dimensione). Prima di scrivere, un filtro («mascheratura») toglie anche mail, numeri di
  telefono, chiavi e token e i percorsi della cartella utente, nel caso finiscano in un messaggio d'errore.

    argo.log      Argo desktop (5 file da 2 MB a rotazione)
    processi.log  WhisperX e gli altri processi figli, solo righe tecniche (5 file da 2 MB)
    crash.log     arresti gravi dell'interprete (faulthandler)
    avvii.json    avvio protetto: quanti avvii di fila non sono arrivati alla finestra
    trace.json    modalità trace attiva e fino a quando
"""
import faulthandler
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

APP_HOME = Path(os.environ.get("TRASCRITTORE_HOME", Path.home() / "whisperx-env"))
CARTELLA = APP_HOME / "log"
FILE_APP = CARTELLA / "argo.log"
FILE_PROCESSI = CARTELLA / "processi.log"
FILE_CRASH = CARTELLA / "crash.log"
FILE_AVVII = CARTELLA / "avvii.json"
FILE_TRACE = CARTELLA / "trace.json"
DIMENSIONE, COPIE = 2 * 1024 * 1024, 4  # 5 file da 2 MB
DURATA_TRACE = 24 * 3600
AVVII_PRIMA_DELLA_SICURA = 2  # dopo 2 avvii di fila non riusciti, il terzo propone la modalità sicura
CARTELLA_APP = Path(__file__).resolve().parent
CARTELLA_PRECEDENTE = CARTELLA_APP.parent / "app_precedente"

log = logging.getLogger("argo")
log_processi = logging.getLogger("argo.processi")
log.addHandler(logging.NullHandler())  # nei processi figli e nelle prove, senza inizia(): nessuna scritta
log_processi.propagate = False
log_processi.addHandler(logging.NullHandler())

SESSIONE = uuid.uuid4().hex[:8]
MODALITA_SICURA = False
TRACE_DA_RIGA = False
_crash_file = None
_avviato = False
_iniziato = False
_mostra_errore = None  # impostato da Qt: funzione(tipo, testo, traccia) che mostra la finestra d'errore


# ------------------------------------------------------------------ mascheratura
_HOME = str(Path.home())
_RE_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_CHIAVI = [
    re.compile(r"sk-ant-[\w-]+"), re.compile(r"\bsk-[\w-]{16,}"), re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), re.compile(r"\bgithub_pat_[\w]{20,}"),
    re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+"),  # token JWT (Microsoft 365)
    re.compile(r"(?i)\bbearer\s+[^\s\"',;]{6,}"),
    re.compile(r"(?i)(x-api-key|authorization|api[_-]?key|access_token|refresh_token|token|password|segreto|chiave)"
               r"([\"']?\s*[:=]\s*[\"']?)[^\s\"',;]{6,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),  # stringhe lunghe e casuali: chiavi, hash, codici
]
_RE_TELEFONO = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?\d[\d\s.-]{6,}\d|(?:3\d{2}|0\d{1,3})[\s.-]?\d{3,4}[\s.-]?\d{3,4})(?![\w.])")
_RE_UTENTE = re.compile(r"(?i)([A-Z]:\\Users\\|/Users/|/home/)[^\\/\s\"']+")
_RE_PERCORSO_UTENTE = re.compile(r"~[\\/][^\"'\n]*?(?=[\"'\n]|$|\s(?=[\w-]+:))")


def _nascondi_percorso(m):
    p = m.group(0)
    if re.search(r"whisperx-env|site-packages|Library[\\/]Application Support|AppData[\\/]Local[\\/]Programs", p):
        return p  # codice e programmi di Argo: utili e senza dati dell'utente
    est = re.findall(r"\.(\w{1,6})\b", p.split("/")[-1].split("\\")[-1])
    return "~/…/<file>" + ("." + est[0] if est else "")


def maschera(testo):
    """Toglie da un testo i dati che non devono finire nei log. Il risultato si può mostrare e inviare."""
    if not testo:
        return testo
    s = str(testo)
    if _HOME and len(_HOME) > 3:
        s = s.replace(_HOME, "~")
        if os.name == "nt":
            s = re.sub(re.escape(_HOME), "~", s, flags=re.I)
    s = _RE_UTENTE.sub("~", s)  # anche la cartella di un altro utente
    s = _RE_PERCORSO_UTENTE.sub(_nascondi_percorso, s)
    s = _RE_MAIL.sub("<mail>", s)
    for r in _RE_CHIAVI:
        s = r.sub(lambda m: (m.group(1) + m.group(2) + "<chiave>") if m.re.groups == 2 else "<chiave>", s)
    s = _RE_TELEFONO.sub("<telefono>", s)
    return s


def descrivi_file(percorso):
    """Di un file dell'utente nel log si scrive solo estensione e dimensione, mai il nome."""
    try:
        p = Path(percorso)
        mb = p.stat().st_size / 1e6
        return f"{p.suffix.lower() or 'senza estensione'} · {mb:.1f} MB"
    except Exception:
        return "file non leggibile"


class _Formattatore(logging.Formatter):
    def format(self, record):
        return maschera(super().format(record))


def _gestore(file):
    g = logging.handlers.RotatingFileHandler(file, maxBytes=DIMENSIONE, backupCount=COPIE, encoding="utf-8",
                                             delay=True)
    g.setFormatter(_Formattatore("%(asctime)s %(levelname)-7s %(name)s · %(message)s", "%Y-%m-%d %H:%M:%S"))
    return g


# ------------------------------------------------------------------ righe dei processi figli
# Si tengono solo righe tecniche: fasi, avanzamento, avvisi ed errori. Il resto (segmenti trascritti, nomi dei
# parlanti, impronte) non viene scritto, nemmeno in trace.
_RE_RIGA_TECNICA = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|Progress:|Performing |Ricalcolo dei parlanti|ERRORE|Error|Exception|"
    r"Traceback|Warning|warn|File \"|^\s+\^|line \d+|Killed|MemoryError|CUDA|MPS|torch|Lightning|Model was trained",
    re.I)
_RE_CONTENUTO = re.compile(r"-->|Transcript|Impronta di|Trascrizione con i nomi|^\s*SPEAKER_\d+|\s(->|~)\s")


def riga_tecnica(riga):
    return bool(riga) and bool(_RE_RIGA_TECNICA.search(riga)) and not _RE_CONTENUTO.search(riga)


def riga_processo(riga, processo="whisperx"):
    """Riga di un processo figlio: nel registro solo in trace e solo se tecnica."""
    if log_processi.isEnabledFor(logging.DEBUG) and riga_tecnica(riga):
        log_processi.debug("%s | %s", processo, riga[:500])


def coda_processo(righe, processo="whisperx", motivo="errore"):
    """Ultime righe tecniche di un processo finito male: si scrivono sempre, servono per capire l'errore."""
    tecniche = [r for r in righe if riga_tecnica(r)][-30:]
    if tecniche:
        log_processi.warning("%s | %s, ultime righe tecniche:\n%s", processo, motivo, "\n".join(tecniche))


# ------------------------------------------------------------------ misure
@contextmanager
def misura(cosa, **dettagli):
    """Scrive durata ed esito di un'operazione. I dettagli devono essere tecnici (fornitore, modello, durata…)."""
    t = time.monotonic()
    extra = " ".join(f"{k}={v}" for k, v in dettagli.items() if v not in (None, ""))
    log.debug("inizio %s %s", cosa, extra)
    try:
        yield
    except Exception as e:
        log.warning("%s non riuscito dopo %.1f s %s · %s: %s", cosa, time.monotonic() - t, extra,
                    type(e).__name__, str(e)[:200])
        raise
    else:
        log.info("%s finito in %.1f s %s", cosa, time.monotonic() - t, extra)


def http(metodo, url, codice, inizio):
    """Una richiesta HTTP, solo in trace: metodo, indirizzo senza parametri, codice e tempo."""
    if log.isEnabledFor(logging.DEBUG):
        log.debug("http %s %s → %s in %.2f s", metodo, url.split("?")[0], codice, time.monotonic() - inizio)


# ------------------------------------------------------------------ modalità trace
def _leggi(file):
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _scrivi(file, dati):
    try:
        CARTELLA.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dati), encoding="utf-8")
    except Exception:
        pass


def _trace_da_criteri():
    try:
        import criteri
        return criteri.carica().get("trace") is True
    except Exception:
        return False


def stato_trace():
    """(attiva, motivo, fino) - motivo: 'criteri' | 'riga_di_comando' | 'utente' | ''; fino: epoch o None."""
    if _trace_da_criteri():
        return True, "criteri", None
    if TRACE_DA_RIGA:
        return True, "riga_di_comando", None
    d = _leggi(FILE_TRACE)
    if d.get("fino", 0) > time.time() and not (d.get("al_riavvio") and d.get("sessione") != SESSIONE):
        return True, "utente", d["fino"]
    return False, "", None


def trace_attiva():
    return stato_trace()[0]


def imposta_trace(attiva, al_riavvio=False):
    """Accende la trace per 24 ore (o fino al prossimo riavvio, se prima) oppure la spegne."""
    if attiva:
        _scrivi(FILE_TRACE, {"fino": time.time() + DURATA_TRACE, "al_riavvio": bool(al_riavvio),
                             "sessione": SESSIONE})
    else:
        try:
            FILE_TRACE.unlink()
        except Exception:
            pass
    _applica_livello()
    log.info("modalità trace %s%s", "accesa" if attiva else "spenta",
             " fino al riavvio (al massimo 24 ore)" if attiva and al_riavvio else " per 24 ore" if attiva else "")


def _applica_livello():
    livello = logging.DEBUG if trace_attiva() else logging.INFO
    log.setLevel(livello)
    log_processi.setLevel(livello)


# ------------------------------------------------------------------ avvio protetto
def avvii_non_riusciti():
    return int(_leggi(FILE_AVVII).get("non_riusciti", 0))


def _segna_avvio(versione):
    d = _leggi(FILE_AVVII)
    n = int(d.get("non_riusciti", 0))
    _scrivi(FILE_AVVII, {"non_riusciti": n + 1, "versione": versione, "quando": time.strftime("%Y-%m-%d %H:%M"),
                         "ultimo_errore": d.get("ultimo_errore", "")})
    return n


def avvio_riuscito():
    """La finestra è comparsa ed è rimasta aperta: il contatore torna a zero."""
    global _avviato
    if _avviato:
        return
    _avviato = True
    d = _leggi(FILE_AVVII)
    # In modalità sicura il problema non è detto che sia risolto: al prossimo avvio normale che non riesce,
    # Argo ripropone subito la modalità sicura.
    resta = AVVII_PRIMA_DELLA_SICURA - 1 if MODALITA_SICURA else 0
    if d.get("non_riusciti", 0) != resta:
        _scrivi(FILE_AVVII, {"non_riusciti": resta, "versione": d.get("versione", ""),
                             "quando": time.strftime("%Y-%m-%d %H:%M")})
    log.info("finestra aperta%s", " in modalità sicura" if MODALITA_SICURA else "")


def ultimo_errore():
    return _leggi(FILE_AVVII).get("ultimo_errore", "")


def versione_di(cartella):
    try:
        m = re.search(r'^VERSIONE\s*=\s*"([\d.]+)"', (Path(cartella) / "trascrittore.py").read_text(encoding="utf-8"),
                      re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def versione_precedente():
    """Versione salvata dall'ultimo aggiornamento in app_precedente, o None se non c'è."""
    return versione_di(CARTELLA_PRECEDENTE) if CARTELLA_PRECEDENTE.is_dir() else None


def torna_alla_precedente():
    """Rimette i file di app_precedente al posto di quelli attuali. Quelli attuali restano in app_scartata.
    Le librerie Python non cambiano. Ritorna la versione ripristinata."""
    v = versione_precedente()
    if not v:
        raise RuntimeError("non c'è una versione precedente salvata (si crea al primo aggiornamento dall'app)")
    attuale = versione_di(CARTELLA_APP)
    scartata = CARTELLA_APP.parent / "app_scartata"
    shutil.rmtree(scartata, ignore_errors=True)
    shutil.copytree(CARTELLA_APP, scartata, ignore=shutil.ignore_patterns("__pycache__"))
    for f in CARTELLA_PRECEDENTE.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            dest = CARTELLA_APP / f.relative_to(CARTELLA_PRECEDENTE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            os.utime(dest)  # data nuova: Python ricompila invece di usare la cache della versione scartata
    _scrivi(FILE_AVVII, {"non_riusciti": 0, "versione": v, "quando": time.strftime("%Y-%m-%d %H:%M"),
                         "tornata_da": attuale})
    log.warning("tornato dalla versione %s alla %s (la %s è in app_scartata)", attuale, v, attuale)
    return v


# ------------------------------------------------------------------ errori non intercettati
def _registra_errore(tipo, valore, traccia, dove):
    import traceback
    testo = "".join(traceback.format_exception(tipo, valore, traccia))
    log.error("errore non gestito (%s): %s", dove, testo)
    if not _avviato:
        d = _leggi(FILE_AVVII)
        d["ultimo_errore"] = maschera(f"{tipo.__name__}: {valore}")[:300]
        _scrivi(FILE_AVVII, d)
    mostra = _mostra_errore
    if mostra is None and not _avviato and dove == "programma":
        try:  # Argo non è ancora arrivato a Qt (per esempio un errore negli import): una finestra comunque
            import supporto
            mostra = supporto.finestra_emergenza
        except Exception:
            mostra = None
    if mostra:
        try:
            mostra(tipo.__name__, maschera(str(valore))[:300], maschera(testo))
        except Exception:
            pass


def _gancio(tipo, valore, traccia):
    if issubclass(tipo, KeyboardInterrupt):
        return sys.__excepthook__(tipo, valore, traccia)
    _registra_errore(tipo, valore, traccia, "programma")
    try:  # con pythonw (Windows) non c'è una console: sys.stderr è None
        if sys.stderr is not None:
            sys.__excepthook__(tipo, valore, traccia)
    except Exception:
        pass


def _gancio_thread(a):
    if a.exc_type is SystemExit:
        return
    _registra_errore(a.exc_type, a.exc_value, a.exc_traceback, f"thread {a.thread.name if a.thread else '?'}")


def descrizione_sistema(completa=False):
    """Dati tecnici del computer, senza nulla di personale."""
    d = {"sistema": platform.platform(), "macchina": platform.machine(), "python": platform.python_version(),
         "core": os.cpu_count()}
    try:
        import risorse
        d.update(ram_gb=round(risorse.ram_gb(), 1), profilo=risorse.profilo())
        if completa:
            d["uso_del_computer"] = risorse.descrizione()
    except Exception:
        pass
    return d


PRECEDENTI = 0


def inizia(versione, argv=None, canale=None):
    """Da chiamare per prima cosa all'avvio di Argo desktop. Ritorna gli avvii di fila non riusciti prima di questo.
    Si può chiamare più volte: conta solo la prima."""
    global _crash_file, TRACE_DA_RIGA, PRECEDENTI, _iniziato
    if _iniziato:
        return PRECEDENTI
    _iniziato = True
    argv = sys.argv if argv is None else argv
    TRACE_DA_RIGA = "--trace" in argv
    try:
        CARTELLA.mkdir(parents=True, exist_ok=True)
        log.addHandler(_gestore(FILE_APP))
        log_processi.addHandler(_gestore(FILE_PROCESSI))
        _crash_file = open(FILE_CRASH, "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        pass
    _applica_livello()
    sys.excepthook = _gancio
    threading.excepthook = _gancio_thread
    precedenti = PRECEDENTI = _segna_avvio(versione)
    attiva, motivo, _ = stato_trace()
    log.info("avvio Argo %s · canale %s · %s · trace %s · avvii non riusciti prima di questo: %d",
             versione, canale or "?", " · ".join(f"{k} {v}" for k, v in descrizione_sistema().items()),
             motivo if attiva else "spenta", precedenti)
    return precedenti


def collega_qt(mostra_errore=None):
    """Messaggi di Qt nel registro e, se data, la finestra d'errore per gli errori non gestiti."""
    global _mostra_errore
    _mostra_errore = mostra_errore
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def messaggio(tipo, _contesto, testo):
            if tipo in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                log.error("Qt: %s", testo)
            elif tipo == QtMsgType.QtWarningMsg:
                log.debug("Qt: %s", testo)
        qInstallMessageHandler(messaggio)
    except Exception:
        pass


def chiusura():
    log.info("chiusura di Argo")
    logging.shutdown()


def file_di_log(giorni=3):
    """File del registro modificati negli ultimi `giorni`, dal più recente."""
    limite = time.time() - giorni * 86400
    tutti = [f for f in CARTELLA.glob("*.log*") if f.is_file() and f.stat().st_mtime >= limite
             and f.stat().st_size > 0] if CARTELLA.is_dir() else []
    return sorted(tutti, key=lambda f: f.stat().st_mtime, reverse=True)
