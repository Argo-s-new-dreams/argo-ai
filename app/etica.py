"""etica.py - filtro etico per relazioni, verbali e sunti.

Decisione di Luca (20/11/2026): relazioni, verbali e sunti riportano solo fatti utili al lavoro. Mai questioni
personali o private, giudizi sulle persone, pettegolezzi, parolacce, bestemmie, insulti o espressioni non
rispettose o discriminatorie, anche se nella conversazione ci sono stati.

Due livelli:
1. REGOLE: aggiunte alle istruzioni dei modelli (il filtro vero: il modello scrive già pulito);
2. pulisci(): rete di sicurezza sul testo prodotto, toglie le parolacce e le bestemmie più comuni rimaste.

Le traduzioni e la dettatura non passano di qui: sono testi dell'utente, da rendere fedelmente.
"""
import re

REGOLE = """
Regole di rispetto (valgono sempre, anche se la conversazione dice altro):
- riporta solo fatti utili al lavoro: esigenze, problemi, processi, prodotti, cifre, decisioni, azioni, prossimi passi;
- non riportare questioni personali o private delle persone (salute, famiglia, vita privata, opinioni politiche
  o religiose, situazioni economiche personali), né pettegolezzi;
- non esprimere giudizi o commenti sulle persone (carattere, aspetto, competenza, simpatia): descrivi cosa è
  stato detto o deciso, non come sono le persone;
- non riportare parolacce, bestemmie, insulti o espressioni offensive o discriminatorie: se ci sono, ometti la
  parte e riporta solo il contenuto di lavoro, con parole neutre;
- i recapiti di lavoro (biglietti da visita, mail e telefoni aziendali) si possono riportare."""

REGOLE_PERSONE = """
Delle persone riporta solo nome e ruolo professionale presi da fonti pubbliche: niente vita privata, niente
giudizi sulle persone, niente pettegolezzi."""

# Rete di sicurezza: parole che non hanno mai posto in un documento di lavoro. Elenco volutamente corto e
# inequivocabile, per non toccare parole normali (si confrontano parole intere, maiuscole e minuscole uguali).
_VOLGARI = [
    r"cazz(?!uol)\w*", r"incazz\w*", r"minchi\w*", r"merd\w*", r"stronz\w*", r"vaffancul\w*", r"fancul\w*",
    r"coglion\w*", r"rompicoglion\w*", r"puttan\w*", r"bastard[oaie]", r"figli[oa] di puttana",
    r"porc[oa] (?:dio|madonna|puttana)", r"dio (?:cane|porco|maiale|boia)", r"madonna puttana",
    r"fuck\w*", r"shit\w*", r"bullshit", r"asshole\w*", r"bitch\w*", r"motherfuck\w*",
]
_RE_VOLGARI = re.compile(r"(?<![\w])(?:" + "|".join(_VOLGARI) + r")(?![\w])", re.I)


def pulisci(testo):
    """Toglie dal testo prodotto le parole volgari rimaste. Ritorna il testo pulito."""
    if not isinstance(testo, str) or not testo:
        return testo
    nuovo, n = _RE_VOLGARI.subn("[…]", testo)
    if n:
        nuovo = re.sub(r"\[…\](?:\s*\[…\])+", "[…]", nuovo)
        try:
            import diagnostica
            diagnostica.log.info("filtro etico: %d espressioni volgari tolte da un testo generato", n)
        except Exception:
            pass
    return nuovo


def pulisci_dati(dati):
    """pulisci() su tutte le stringhe di una struttura (dizionari e liste), per le relazioni in JSON."""
    if isinstance(dati, str):
        return pulisci(dati)
    if isinstance(dati, list):
        return [pulisci_dati(v) for v in dati]
    if isinstance(dati, dict):
        return {k: pulisci_dati(v) for k, v in dati.items()}
    return dati
