"""uscite.py - che cosa esce da questo computer, verso dove, quando.

Parte della promessa di Argo: di base la conversazione non lascia il computer; escono solo i dati che decidi tu
(un modello cloud scelto per un attrezzo, una ricerca web, una bozza in Outlook, un record nel CRM). Ogni uscita:
- compare per qualche secondo nella barra in basso («☁️ Uscito ora: …»);
- resta nell'elenco *Impostazioni › 🛟 Supporto › Cosa è uscito da questo computer*.

Si registrano solo la destinazione e il tipo di dato, mai il contenuto. File: APP_HOME/log/uscite.jsonl, al massimo
500 righe; le uscite uguali e ravvicinate (entro un minuto) diventano una riga con il numero di volte.
Non sono uscite, e non si registrano: il Ponte verso il tuo iPhone (rete locale), i download di modelli e
aggiornamenti (non portano dati tuoi), le letture da Microsoft 365 e Dynamics (calendario, posta, record).
"""
import json
import os
import threading
import time
from pathlib import Path

APP_HOME = Path(os.environ.get("TRASCRITTORE_HOME", Path.home() / "whisperx-env"))
FILE = APP_HOME / "log" / "uscite.jsonl"
MASSIMO = 500
UNIONE_SECONDI = 60
_blocco = threading.Lock()
_avvisa = None  # funzione(testo) impostata dall'interfaccia, chiamabile da qualunque thread


def _leggi():
    try:
        return [json.loads(r) for r in FILE.read_text(encoding="utf-8").splitlines() if r.strip()]
    except Exception:
        return []


def registra(verso, cosa):
    """Una uscita: `verso` = destinazione (es. «Claude · Anthropic»), `cosa` = tipo di dato, mai il contenuto."""
    adesso = time.time()
    with _blocco:
        righe = _leggi()
        ultima = righe[-1] if righe else None
        if ultima and ultima.get("verso") == verso and ultima.get("cosa") == cosa \
                and adesso - ultima.get("t", 0) < UNIONE_SECONDI:
            ultima["volte"] = ultima.get("volte", 1) + 1
            ultima["t"] = adesso
            nuova = False
        else:
            righe.append({"t": adesso, "quando": time.strftime("%Y-%m-%d %H:%M:%S"), "verso": verso, "cosa": cosa,
                          "volte": 1})
            nuova = True
        try:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            FILE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe[-MASSIMO:]),
                            encoding="utf-8")
        except Exception:
            pass
    try:
        import diagnostica
        diagnostica.log.info("uscita verso %s · %s", verso, cosa)
    except Exception:
        pass
    if nuova and _avvisa:
        try:
            _avvisa(f"☁️ Uscito ora: {cosa} → {verso}")
        except Exception:
            pass


def elenco(quante=200):
    """Le uscite più recenti per prime."""
    return list(reversed(_leggi()))[:quante]


def svuota():
    with _blocco:
        try:
            FILE.unlink()
        except FileNotFoundError:
            pass
