"""cervello_dal_vivo.py - Secondo cervello, quarto blocco: suggerimenti dal vivo durante la trascrizione Live.

Mentre la Live trascrive, accanto al testo c'è la scaletta presa dalla Base (domande e temi dagli incontri simili,
come nella scheda «Prepara»). Senza modello, a ogni blocco trascritto Argo segna come «toccati» i temi e le
domande di cui si è già parlato, confrontando le parole importanti con la trascrizione: così restano in vista
solo quelli ancora da fare.

A richiesta (o ogni pochi minuti, se l'utente lo sceglie e il computer non è nel profilo Leggero) il modello locale
legge gli ultimi minuti di trascrizione, già anonimizzati, e propone le due o tre domande da fare adesso.
Solo modello locale: niente esce dal computer.
"""
import re

import cervello_base as base
import cervello_suggerimenti as sug
import etica

MAX_DOMANDE_ORA = 3
CARATTERI_RECENTI = 5000  # circa gli ultimi 4-5 minuti di parlato
MINUTI_AUTOMATICI = 5

PAROLE_VUOTE = set("""
abbiamo alcuni alcune allora altro altri anche ancora avete come cosa cose della delle dello degli dalla dalle
dagli dopo dove essere fare fatto gestite gestisce hanno loro molto nella nelle nello negli nostro nostra oggi
ogni perché però poco prima quale quali quando quanto quella quelle quello questo questa questi queste sempre
siete sono state stato sulla sulle sullo sugli tutti tutto tutte tutta vostro vostra vostri vostre caso casi
simile simili emerso rimasto aperto punto domanda domande tema temi about there their these those which what
where when would could should with from have this that your dass sind eine einen oder nicht desde sobre para
como cuando están tienen
""".split())

SCHEMA = {
    "type": "object",
    "properties": {"domande": {"type": "array", "items": {"type": "string"}}},
    "required": ["domande"],
}

ISTRUZIONI = """Aiuti un consulente durante un incontro di lavoro, in tempo reale. Hai:
- gli ultimi minuti della trascrizione (anonima: «Persona 1, 2…», «[azienda]»);
- i temi e le domande della scaletta non ancora toccati;
- appunti anonimi di incontri simili.
Contesto dell'incontro: {contesto}

Proponi al massimo {massimo} domande da fare ADESSO, in {lingua}: brevi, aperte, legate a ciò che si sta dicendo
(per approfondire un punto appena emerso) o a un tema importante della scaletta non ancora toccato.
Non ripetere domande già fatte nella trascrizione. Non inventare fatti. Nessun nome di persona o azienda.
{regole}"""


# ---------------------------------------------------------------- scaletta e temi toccati
def _radice(parola):
    return parola[:6]  # «magazzino», «magazzini», «magazziniere» → «magazz»


def parole_chiave(testo):
    """Le parole importanti di un tema o di una domanda (radici di 6 lettere), senza le parole vuote."""
    out = []
    for p in re.findall(r"[^\W\d_]{5,}", (testo or "").lower()):
        if p not in PAROLE_VUOTE:
            r = _radice(p)
            if r not in out:
                out.append(r)
    return out


def _radici_testo(testo):
    return {_radice(p) for p in re.findall(r"[^\W\d_]{5,}", (testo or "").lower())}


def toccato(voce, radici_trascrizione):
    """Vero se nella trascrizione ci sono abbastanza parole importanti della voce (almeno metà, minimo 2;
    1 se la voce ne ha una sola)."""
    chiavi = parole_chiave(voce)
    if not chiavi:
        return False
    trovate = sum(1 for c in chiavi if c in radici_trascrizione)
    return trovate >= (1 if len(chiavi) == 1 else max(2, (len(chiavi) + 1) // 2))


class Scaletta:
    """Temi e domande per l'incontro in corso, con quelli già toccati."""

    def __init__(self, azienda_id="", funzioni_id=(), argomento=""):
        self.categoria, self.funzioni = sug.contesto_da_scelta(azienda_id, funzioni_id)
        self.trovati = sug.simili(self.categoria, self.funzioni, argomento)
        raccolti = sug.raccogli(self.trovati) if self.trovati else {k: [] for k, _t in sug.SEZIONI}
        self.voci = [{"tipo": "tema", "testo": t, "toccato": False} for t in raccolti.get("temi", [])]
        self.voci += [{"tipo": "domanda", "testo": d, "toccato": False} for d in raccolti.get("domande", [])]
        self.emerso = raccolti.get("emerso", [])
        self.trascrizione = ""

    def vuota(self):
        return not self.voci

    def aggiungi(self, testo):
        """Nuovo testo trascritto. Ritorna gli indici delle voci appena diventate «toccate»."""
        self.trascrizione += "\n" + (testo or "")
        radici = _radici_testo(self.trascrizione)
        nuovi = []
        for i, v in enumerate(self.voci):
            if not v["toccato"] and toccato(v["testo"], radici):
                v["toccato"] = True
                nuovi.append(i)
        return nuovi

    def da_fare(self):
        return [v for v in self.voci if not v["toccato"]]

    # ------------------------------------------------------------ con il modello locale
    def domande_ora(self, stop=None):
        """Le domande da fare adesso, dal modello locale. Solo testo anonimizzato e solo modello locale."""
        url, modello = base._modello()  # rifiuta un Ollama non locale
        aziende, persone, siti = base.nomi_noti()
        recente = base.anonimizza_testo(self.trascrizione[-CARATTERI_RECENTI:], aziende, persone, siti, numera=True)
        scaletta = "\n".join(f"- ({v['tipo']}) {v['testo']}" for v in self.da_fare()) or "- (tutto già toccato)"
        appunti = "\n\n".join(base.in_testo(v) for _p, v in self.trovati[:3])
        sistema = ISTRUZIONI.format(contesto=base._descrivi_contesto(self.categoria, self.funzioni) or "non indicato",
                                    massimo=MAX_DOMANDE_ORA, lingua=sug._lingua(), regole=etica.REGOLE)
        utente = (f"## Ultimi minuti della trascrizione\n{recente.strip() or '(ancora niente)'}\n\n"
                  f"## Scaletta non ancora toccata\n{scaletta}\n\n## Appunti di incontri simili\n{appunti or '(nessuno)'}")
        dati = base._chiedi(url, modello, sistema, utente, SCHEMA, stop)
        valori = dati.get("domande") if isinstance(dati.get("domande"), list) else []
        domande = [str(x).strip() for x in valori if str(x).strip()][:MAX_DOMANDE_ORA]
        domande = [base.anonimizza_testo(d, aziende, persone, siti) for d in domande]
        return etica.pulisci_dati({"domande": domande})["domande"]


def automatico_consentito():
    """Le domande automatiche ogni pochi minuti non si offrono sui computer nel profilo Leggero."""
    import risorse
    return risorse.profilo() != "leggero"
