"""lingua.py - lingua dell'interfaccia di Argo: italiano (base), inglese, spagnolo, tedesco.

Ogni testo dell'interfaccia passa da tr("testo in italiano", campo=valore). La chiave è il testo italiano;
le traduzioni stanno in app/traduzioni/<lingua>.json. Un testo senza traduzione resta in italiano.
I segnaposto sono quelli di str.format con nome: tr("Incontro di {nome}", nome=n).

La lingua si sceglie in Impostazioni › Aspetto (lingua_interfaccia: auto | it | en | es | de) e vale dal
prossimo avvio. È separata dalla lingua delle trascrizioni e delle relazioni.
Il controllo strumenti/controlla_traduzioni.py verifica che ogni tr(...) abbia la traduzione nelle tre lingue.
"""
import json
from pathlib import Path

LINGUE = {"it": "Italiano", "en": "English", "es": "Español", "de": "Deutsch"}
CARTELLA = Path(__file__).resolve().parent / "traduzioni"

_corrente = "it"
_catalogo: dict[str, str] = {}


def corrente() -> str:
    return _corrente


def lingua_di_sistema() -> str:
    """Lingua del sistema operativo, se è una delle quattro; altrimenti italiano."""
    try:
        from PySide6.QtCore import QLocale
        codice = QLocale.system().name()[:2].lower()
    except Exception:
        codice = "it"
    return codice if codice in LINGUE else "it"


def scegli(impostazioni: dict) -> str:
    """Lingua da usare secondo le impostazioni (auto = come il sistema)."""
    scelta = (impostazioni or {}).get("lingua_interfaccia", "auto")
    return scelta if scelta in LINGUE else lingua_di_sistema()


def imposta(codice: str) -> None:
    """Carica le traduzioni della lingua indicata (it = nessuna traduzione)."""
    global _corrente, _catalogo
    _corrente = codice if codice in LINGUE else "it"
    _catalogo = {}
    if _corrente != "it":
        try:
            _catalogo = json.loads((CARTELLA / f"{_corrente}.json").read_text(encoding="utf-8"))
        except Exception:
            _catalogo = {}


def tr(testo: str, **campi) -> str:
    """Il testo nella lingua dell'interfaccia, con i campi già inseriti."""
    tradotto = _catalogo.get(testo) or testo
    if not campi:
        return tradotto
    try:
        return tradotto.format(**campi)
    except (KeyError, IndexError, ValueError):
        return testo.format(**campi)


def installa_qt(app) -> None:
    """Pulsanti e finestre standard di Qt (OK, Annulla, Sì, No…) nella lingua dell'interfaccia."""
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
        traduttore = QTranslator(app)
        percorso = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if traduttore.load(QLocale(_corrente), "qtbase", "_", percorso):
            app.installTranslator(traduttore)
            app._traduttore_argo = traduttore  # resta vivo quanto l'app
    except Exception:
        pass
