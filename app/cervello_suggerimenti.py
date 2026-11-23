"""cervello_suggerimenti.py - Secondo cervello, terzo blocco: «Esprimi» prima dell'incontro.

Prima di un incontro Argo cerca nella Base (anonima) gli incontri simili e propone:
    - domande da fare (le «domande che hanno funzionato» e i punti rimasti aperti in casi simili);
    - temi da toccare;
    - cosa è emerso in casi simili (esigenze e problemi ricorrenti).

Come si trovano i casi simili, senza modello:
    - categoria dell'azienda: stesso settore (peso 3), stessa dimensione, tipo di attività e area (peso 1 ciascuno);
    - funzioni delle persone: stessa area di funzione (peso 2), stesso livello (peso 1);
    - se c'è un argomento e un modello per i documenti: somiglianza del testo (peso fino a 4).
Il risultato senza modello è già utile (elenchi uniti e senza doppioni). Con il modello locale, a richiesta,
Argo li riordina in una scaletta breve. Si usa solo la Base, che non contiene nomi: nulla esce dal computer.
"""
import json
import re

import numpy as np

import cervello_base as base
import etica
import voci_core as core

MAX_SIMILI = 6
MAX_PER_ELENCO = 8
SOGLIA = 2  # punteggio minimo per considerare simile un incontro (senza argomento)

SEZIONI = [("domande", "Domande da fare"), ("temi", "Temi da toccare"), ("emerso", "Cosa è emerso in casi simili")]

SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "array", "items": {"type": "string"}} for k, _t in SEZIONI},
    "required": [k for k, _t in SEZIONI],
}

ISTRUZIONI = """Prepari un consulente a un incontro di lavoro. Hai SOLO appunti anonimi di incontri simili
(stesso tipo di azienda o stesse funzioni). Contesto del prossimo incontro: {contesto}{argomento}

Scrivi in {lingua}, frasi brevi e concrete, al massimo {massimo} voci per elenco:
- domande: domande aperte da fare in questo incontro, riformulate per questo contesto («Come gestite oggi…?»),
  partendo dalle domande che hanno funzionato e dai punti rimasti aperti;
- temi: argomenti da toccare;
- emerso: esigenze e problemi ricorrenti nei casi simili, da verificare («In casi simili è emerso che…»).
Non inventare fatti che non sono negli appunti. Nessun nome di persona, azienda o località sotto la regione.
{regole}"""


# ---------------------------------------------------------------- somiglianza
def _noto(x):
    return bool(x) and not str(x).startswith("Non not")


def _punteggio(voce, categoria, funzioni):
    p = 0
    az = voce.get("azienda") or {}
    if _noto(categoria.get("settore")) and az.get("settore") == categoria.get("settore"):
        p += 3
    for k in ("dimensione", "tipo_attivita", "area"):
        if _noto(categoria.get(k)) and az.get(k) == categoria.get(k):
            p += 1
    aree = {f.get("area") for f in funzioni if _noto(f.get("area"))}
    livelli = {f.get("livello") for f in funzioni if _noto(f.get("livello"))}
    for f in voce.get("funzioni") or []:
        if f.get("area") in aree:
            p += 2
            aree.discard(f.get("area"))
        if f.get("livello") in livelli:
            p += 1
            livelli.discard(f.get("livello"))
    return p


def _somiglianze_testo(argomento):
    """{id voce: somiglianza 0..1} con l'argomento, se c'è un modello per i documenti locale. {} altrimenti."""
    if not argomento.strip():
        return {}
    import llm_locale as llm
    s = core.carica_impostazioni()
    url, modello = s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_embed")
    ids, m = base.vettori()
    if not modello or not llm.e_locale(url) or not ids or m.size == 0:
        return {}
    try:
        q = llm.embed([argomento], modello, url)[0]
    except Exception:
        return {}
    if q.shape[0] != m.shape[1]:
        return {}
    sim = m @ np.asarray(q, dtype=np.float32)
    return {i: float(max(0.0, s_)) for i, s_ in zip(ids, sim)}


def simili(categoria, funzioni, argomento="", massimo=MAX_SIMILI):
    """Le voci della Base più vicine al prossimo incontro: [(punteggio, voce)], dal più simile."""
    testo = _somiglianze_testo(argomento)
    risultati = []
    for v in base.voci():
        p = _punteggio(v, categoria, funzioni) + 4 * testo.get(v.get("id"), 0.0)
        if p >= (SOGLIA if not testo else 1.5):
            risultati.append((round(p, 2), v))
    risultati.sort(key=lambda x: (x[0], x[1].get("mese", "")), reverse=True)
    return risultati[:massimo]


def contesto_da_scelta(azienda_id, funzioni_id):
    """Categorie e funzioni (anonime) dalla scelta del dialogo «Con chi stai parlando?»."""
    return base.contesto({"azienda": azienda_id, "funzioni": list(funzioni_id or [])})


# ---------------------------------------------------------------- suggerimenti senza modello
def _chiave(testo):
    return re.sub(r"\W+", " ", testo.lower()).strip()


def _unisci(elenchi, massimo=MAX_PER_ELENCO):
    visti, out = set(), []
    for elenco in elenchi:
        for x in elenco:
            k = _chiave(x)
            if k and k not in visti:
                visti.add(k)
                out.append(x)
            if len(out) >= massimo:
                return out
    return out


def raccogli(trovati):
    """Domande, temi e cosa è emerso dalle voci simili (in ordine di somiglianza), senza modello."""
    cont = [(v.get("contenuti") or {}) for _p, v in trovati]
    return {
        "domande": _unisci([c.get("domande_efficaci", []) for c in cont]
                           + [[f"Punto rimasto aperto in un caso simile: {x}" for x in c.get("punti_aperti", [])]
                              for c in cont]),
        "temi": _unisci([c.get("temi", []) for c in cont]),
        "emerso": _unisci([c.get("esigenze", []) for c in cont] + [c.get("problemi", []) for c in cont]),
    }


# ---------------------------------------------------------------- scaletta con il modello locale
def _lingua():
    import lingua
    return {"it": "italiano", "en": "inglese", "es": "spagnolo", "de": "tedesco"}.get(lingua.corrente(), "italiano")


def riordina(trovati, categoria, funzioni, argomento="", stop=None):
    """Con il modello locale: una scaletta su misura a partire dalle voci simili. Solo modello locale."""
    url, modello = base._modello()
    appunti = "\n\n".join(f"### Caso simile ({base.descrivi(v) or 'contesto non indicato'}, {v.get('mese', '')})\n"
                          + base.in_testo(v) for _p, v in trovati)
    sistema = ISTRUZIONI.format(contesto=base._descrivi_contesto(categoria, funzioni),
                                argomento=f"\nArgomento previsto: {argomento.strip()}" if argomento.strip() else "",
                                lingua=_lingua(), massimo=MAX_PER_ELENCO, regole=etica.REGOLE)
    dati = base._chiedi(url, modello, sistema, appunti, SCHEMA, stop)
    out = {}
    for k, _t in SEZIONI:
        valori = dati.get(k) or []
        out[k] = [str(x).strip() for x in valori if str(x).strip()][:MAX_PER_ELENCO] if isinstance(valori, list) else []
    aziende, persone, siti = base.nomi_noti()
    out = {k: [base.anonimizza_testo(x, aziende, persone, siti) for x in v] for k, v in out.items()}
    return etica.pulisci_dati(out)


def in_markdown(suggerimenti, trovati, titoli=None):
    """Testo da mostrare o copiare. `titoli`: {chiave: titolo tradotto}."""
    titoli = titoli or dict(SEZIONI)
    righe = []
    for k, t in SEZIONI:
        if suggerimenti.get(k):
            righe += [f"## {titoli.get(k, t)}"] + [f"- {x}" for x in suggerimenti[k]] + [""]
    return "\n".join(righe).strip()


def prepara(azienda_id, funzioni_id, argomento="", con_modello=False, stop=None):
    """Tutto in una chiamata: (suggerimenti, voci simili). Suggerimenti vuoti se la Base non ha casi simili."""
    categoria, funzioni = contesto_da_scelta(azienda_id, funzioni_id)
    trovati = simili(categoria, funzioni, argomento)
    if not trovati:
        return {k: [] for k, _t in SEZIONI}, []
    if con_modello:
        return riordina(trovati, categoria, funzioni, argomento, stop), trovati
    return raccogli(trovati), trovati


def descrivi_contesto(azienda_id, funzioni_id):
    """«Manifatturiero, Media (50-249), Piemonte · Responsabile IT» per il titolo del dialogo."""
    categoria, funzioni = contesto_da_scelta(azienda_id, funzioni_id)
    return base.descrivi({"azienda": categoria, "funzioni": funzioni})


if __name__ == "__main__":  # prova veloce: python cervello_suggerimenti.py <id azienda> [id funzione…]
    import sys
    s, t = prepara(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:])
    print(json.dumps({"simili": [(p, v.get("id")) for p, v in t], "suggerimenti": s}, ensure_ascii=False, indent=1))
