"""cervello_base.py - Secondo cervello, secondo blocco: «Distilla» e base anonimizzata.

Da un incontro catalogato (trascrizione, relazione, incontro dall'iPhone) il modello LOCALE estrae solo fatti utili
al lavoro: temi, esigenze, problemi, come lavorano oggi, decisioni, domande che hanno funzionato, punti aperti.
Poi l'anonimizzazione, in tre passi, perché nella base non resti nulla che riporti a persone o aziende:
    1. il modello scrive già al posto dei nomi le categorie del catalogo («un'azienda manifatturiera media del
       Piemonte», «il responsabile IT»);
    2. un controllo senza modello sostituisce i nomi che Argo conosce (azienda dell'incontro e tutte quelle del
       catalogo, parlanti della trascrizione, partecipanti, voci dell'anagrafe) e toglie mail, telefoni, siti,
       partite IVA;
    3. un secondo passaggio del modello cerca i nomi propri rimasti (persone, aziende, enti, località più piccole
       di una regione) e li toglie.
La voce della base porta solo: mese, categorie dell'azienda, funzioni delle persone e i contenuti. Nessun nome,
nessun percorso, nessun identificativo dell'incontro: è irreversibile. Il legame con l'incontro resta solo
nell'archivio locale (incontri.json), per sapere che è già stato distillato; chi cancella la scheda non tocca
la base. Gli embedding (bge-m3 o il modello dei Documenti) servono ai suggerimenti del prossimo blocco.
"""
import json
import re
import uuid
from pathlib import Path

import numpy as np

import etica
import secondo_cervello as sc
import voci_core as core

FILE_BASE = sc.CARTELLA / "base.json"
FILE_VETTORI = sc.CARTELLA / "base_vettori.npz"
VERSIONE_REGOLE = 1
CARATTERI_PER_BLOCCO = 12_000
MAX_VOCI = 8

SEZIONI = [("sintesi", "Sintesi"), ("temi", "Temi"), ("esigenze", "Esigenze"), ("problemi", "Problemi"),
           ("processi", "Come lavorano oggi"), ("decisioni", "Decisioni"),
           ("domande_efficaci", "Domande che hanno funzionato"), ("punti_aperti", "Punti aperti da approfondire")]
LISTE = [k for k, _t in SEZIONI if k != "sintesi"]

SCHEMA = {
    "type": "object",
    "properties": dict({"sintesi": {"type": "string"}},
                       **{k: {"type": "array", "items": {"type": "string"}} for k in LISTE}),
    "required": ["sintesi"] + LISTE,
}
SCHEMA_NOMI = {"type": "object", "properties": {"nomi": {"type": "array", "items": {"type": "string"}}},
               "required": ["nomi"]}

ISTRUZIONI = """Sei l'archivista del «Secondo cervello» di un consulente: da un incontro di lavoro estrai SOLO
conoscenza riutilizzabile in incontri futuri con aziende e funzioni simili.

Contesto (già anonimo): {contesto}

Cosa scrivere, in italiano, frasi brevi e concrete (al massimo {massimo} voci per elenco, elenchi vuoti se non c'è
nulla):
- sintesi: 2-3 frasi su di cosa si è parlato e con quale esito;
- temi: argomenti trattati;
- esigenze: cosa serve all'azienda o alla funzione;
- problemi: difficoltà, colli di bottiglia, rischi emersi;
- processi: come lavorano oggi (strumenti, flussi, abitudini), senza dettagli che identifichino l'azienda;
- decisioni: cosa è stato deciso o concordato;
- domande_efficaci: domande poste nell'incontro che hanno fatto emergere informazioni utili, riformulate in modo
  generale e riusabile («Come gestite oggi…?»);
- punti_aperti: cosa è rimasto senza risposta e conviene approfondire la prossima volta.

ANONIMIZZAZIONE (obbligatoria, irreversibile):
- MAI nomi di persone: usa la funzione («il responsabile IT», «il titolare», «il consulente»).
- MAI nomi di aziende, gruppi, marchi dell'azienda incontrata, clienti o fornitori: usa la categoria («l'azienda»,
  «un cliente del settore alimentare», «un fornitore»). Nomi di software, tecnologie e standard sono ammessi
  (per esempio Microsoft 365, SAP, ISO 9001).
- MAI località più precise della regione, indirizzi, mail, telefoni, siti, codici, cifre che identifichino
  l'azienda (fatturato esatto, numero esatto di dipendenti).
{regole}"""

ISTRUZIONI_CONSOLIDA = """Unisci questi estratti parziali dello stesso incontro in un solo estratto con lo stesso
schema: togli i doppioni, tieni le voci più utili (al massimo {massimo} per elenco) e scrivi una sintesi unica di
2-3 frasi. Rispetta le stesse regole di anonimizzazione: nessun nome di persona, azienda o località sotto la
regione.
{regole}"""

ISTRUZIONI_NOMI = """Nel testo che segue trova i NOMI PROPRI ancora presenti di: persone, aziende, gruppi, marchi
di aziende, enti, scuole, località più piccole di una regione italiana (città, paesi, vie). NON elencare: regioni,
nazioni, nomi di software, tecnologie, standard, normative, mesi, parole comuni. Rispondi con l'elenco esatto come
compare nel testo; elenco vuoto se non ce ne sono."""


class ErroreDistilla(RuntimeError):
    pass


# ---------------------------------------------------------------- base su disco
def voci():
    try:
        dati = json.loads(FILE_BASE.read_text(encoding="utf-8"))
        return dati if isinstance(dati, list) else []
    except Exception:
        return []


def voce(id_):
    return next((v for v in voci() if v.get("id") == id_), None)


def _scrivi(elenco):
    sc.CARTELLA.mkdir(parents=True, exist_ok=True)
    tmp = FILE_BASE.with_suffix(".tmp")
    tmp.write_text(json.dumps(elenco, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE_BASE)


def vettori():
    """(ids, matrice) degli embedding; matrice vuota se non ce ne sono."""
    try:
        with np.load(FILE_VETTORI, allow_pickle=False) as d:
            return list(d["ids"]), d["m"]
    except Exception:
        return [], np.zeros((0, 0), dtype=np.float32)


def _salva_vettore(id_, v):
    ids, m = vettori()
    righe = {i: m[n] for n, i in enumerate(ids) if i != id_}
    if v is not None:
        righe[id_] = np.asarray(v, dtype=np.float32)
    if righe and len({r.shape for r in righe.values()}) > 1:  # cambiato modello: si tengono solo i nuovi
        righe = {i: r for i, r in righe.items() if r.shape == np.asarray(v).shape} if v is not None else {}
    sc.CARTELLA.mkdir(parents=True, exist_ok=True)
    if righe:
        np.savez(FILE_VETTORI, ids=np.array(list(righe)), m=np.stack(list(righe.values())))
    else:
        FILE_VETTORI.unlink(missing_ok=True)


def salva_voce(v, sostituisci=None):
    """Aggiunge (o rimpiazza) una voce già anonimizzata. Ritorna l'id."""
    with sc._lock:
        elenco = [x for x in voci() if x.get("id") not in (v.get("id"), sostituisci)]
        elenco.append(v)
        _scrivi(elenco)
    return v["id"]


def elimina_voce(id_):
    with sc._lock:
        _scrivi([v for v in voci() if v.get("id") != id_])
    _salva_vettore(id_, None)
    _scollega_incontri(id_)


def _scollega_incontri(id_):
    with sc._lock:
        elenco = sc._leggi(sc.FILE_INCONTRI)
        for i in elenco:
            if i.get("base") == id_:
                i.pop("base", None)
        sc._scrivi(sc.FILE_INCONTRI, elenco)


def svuota():
    with sc._lock:
        FILE_BASE.unlink(missing_ok=True)
        FILE_VETTORI.unlink(missing_ok=True)


# ---------------------------------------------------------------- testo dell'incontro
def testo_incontro(scheda):
    """Il testo da distillare: relazione + trascrizione per gli incontri dall'iPhone, la trascrizione con i nomi per
    i file. Ritorna (testo, nomi_dei_parlanti)."""
    rif = Path(scheda.get("riferimento") or "")
    parti, nomi = [], set()
    if rif.is_dir() and (rif / "sessione.json").exists():
        import relazione_incontro as rel
        sessione = json.loads((rif / "sessione.json").read_text(encoding="utf-8"))
        nomi.update(p.get("nome", "") for p in sessione.get("partecipanti", []))
        relazione = rif / rel.FILE_TESTO
        if relazione.exists():
            parti.append("RELAZIONE DELL'INCONTRO\n" + relazione.read_text(encoding="utf-8"))
        parti.append("TRASCRIZIONE\n" + rel.cronologia(rif, sessione))
    else:
        candidati = [rif] if rif.suffix.lower() in (".txt", ".md") else []
        candidati.append(rif.with_name(rif.stem + "_nomi.txt"))
        file = next((c for c in candidati if c.is_file()), None)
        if file is None:
            raise ErroreDistilla("Trascrizione non trovata: trascrivi prima il file (pagina Trascrivi).")
        parti.append("TRASCRIZIONE\n" + file.read_text(encoding="utf-8", errors="replace"))
    testo = "\n\n".join(p for p in parti if p.strip())
    nomi.update(m.group(1) for m in re.finditer(r"^\[[\d:]+\]\s*([^:\n]{2,60}):", testo, flags=re.M))
    nomi = {n.strip() for n in nomi if n and n.strip() and not re.match(r"(?i)(parlante|speaker|non attribuito)\b", n.strip())}
    if not testo.strip():
        raise ErroreDistilla("L'incontro non contiene testo da distillare.")
    return testo, nomi


# ---------------------------------------------------------------- anonimizzazione senza modello
GENERICHE = {"srl", "s.r.l", "spa", "s.p.a", "snc", "sas", "group", "gruppo", "italia", "italy", "the", "and",
             "società", "azienda", "industria", "industrie", "servizi", "service", "services", "sistemi",
             "consulting", "solutions", "studio", "international", "holding", "company", "nord", "sud"}
_RE_FISSI = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[mail]"),
    (re.compile(r"(?i)\b(https?://|www\.)\S+"), "[sito]"),
    (re.compile(r"(?i)\b[\w-]+\.(it|com|eu|net|org|biz|info|de|fr|ch)\b"), "[sito]"),
    (re.compile(r"(?i)\b(p\.?\s?iva|partita iva|c\.?f\.?)\s*:?\s*[A-Z0-9]{11,16}\b"), "[codice]"),
    (re.compile(r"\b\d{11}\b"), "[codice]"),
]
_RE_TELEFONO = re.compile(r"(?<![\w\d])\+?\d[\d\s./-]{7,}\d(?![\w\d])")


def _telefono(m):
    """Un numero con almeno 9 cifre è un telefono; date e importi più corti restano."""
    return "[telefono]" if sum(ch.isdigit() for ch in m.group(0)) >= 9 else m.group(0)


def _forme(nome, azienda=False):
    """Le forme da cercare: il nome intero e, per le aziende, le parole distintive (Rossi Srl → «Rossi»)."""
    nome = (nome or "").strip()
    if len(nome) < 2:
        return []
    forme = {nome}
    if azienda:
        for parola in re.split(r"[\s,&'’\-/]+", nome):
            p = parola.strip(".()")
            if len(p) >= 4 and p.lower() not in GENERICHE:
                forme.add(p)
    else:
        parti = [p for p in nome.split() if len(p) >= 3]
        forme.update(parti)
    return sorted(forme, key=len, reverse=True)


def anonimizza_testo(testo, aziende=(), persone=(), siti=(), numera=False):
    """Toglie mail, siti, codici e telefoni, poi i nomi noti: le aziende diventano «[azienda]», le persone «[persona]»
    oppure, con numera=True (testo che legge il modello), «Persona 1, 2…» per distinguere ancora chi dice cosa."""
    if not testo:
        return testo
    for regola, sostituto in _RE_FISSI:
        testo = regola.sub(sostituto, testo)
    testo = _RE_TELEFONO.sub(_telefono, testo)
    for s in siti:
        dominio = re.sub(r"(?i)^(https?://)?(www\.)?", "", s or "").split("/")[0]
        if dominio:
            testo = re.sub(re.escape(dominio), "[sito]", testo, flags=re.I)
    for nome in aziende:
        for f in _forme(nome, azienda=True):
            testo = re.sub(rf"(?i)(?<!\w){re.escape(f)}(?!\w)", "[azienda]", testo)
    testo = re.sub(r"\[azienda\](?:[\s,]*\[azienda\])+", "[azienda]", testo)
    for n, nome in enumerate(sorted(set(persone), key=len, reverse=True), 1):
        sostituto = f"Persona {n}" if numera else "[persona]"
        for f in _forme(nome):
            testo = re.sub(rf"(?i)(?<!\w){re.escape(f)}(?!\w)", sostituto, testo)
    if not numera:
        testo = re.sub(r"\[persona\](?:\s*\[persona\])+", "[persona]", testo)
    return testo


def _applica(contenuti, funzione):
    out = {"sintesi": funzione(contenuti.get("sintesi", ""))}
    for k in LISTE:
        out[k] = [funzione(x) for x in contenuti.get(k, []) if str(x).strip()][:MAX_VOCI]
    return out


def nomi_noti(persone=()):
    """Tutti i nomi che Argo conosce: aziende del catalogo (e siti), voci dell'anagrafe, persone dell'incontro."""
    catalogo = sc.aziende()
    aziende = [a.get("nome", "") for a in catalogo]
    siti = [a.get("sito", "") for a in catalogo if a.get("sito")]
    try:
        voci_note = [n for n, _c in core.elenco_voci()]
    except Exception:
        voci_note = []
    return aziende, list(dict.fromkeys(list(persone) + voci_note)), siti


# ---------------------------------------------------------------- distillazione
def contesto(scheda):
    """Categorie dell'azienda e funzioni: anonime per costruzione."""
    a = sc.azienda(scheda.get("azienda")) or {}
    categoria = {k: a.get(k, "") for k in ("settore", "dimensione", "tipo_attivita", "area")}
    funzioni = [{k: f.get(k, "") for k in ("ruolo", "area", "livello")}
                for f in (sc.funzione(i) for i in scheda.get("funzioni", [])) if f]
    return categoria, funzioni


def _descrivi_contesto(categoria, funzioni):
    az = ", ".join(v for v in categoria.values() if v and not v.startswith("Non not")) or "non indicata"
    fz = "; ".join(sc.descrivi_funzione(f) for f in funzioni) or "non indicate"
    return f"azienda: {az}. Persone (funzioni): {fz}."


def _blocchi(testo):
    if len(testo) <= CARATTERI_PER_BLOCCO:
        return [testo]
    blocchi, corrente = [], ""
    for riga in testo.splitlines(keepends=True):
        if len(corrente) + len(riga) > CARATTERI_PER_BLOCCO and corrente:
            blocchi.append(corrente)
            corrente = ""
        corrente += riga
    return blocchi + ([corrente] if corrente.strip() else [])


def _modello():
    import llm_locale as llm
    s = core.carica_impostazioni()
    url, modello = s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_chat")
    if not llm.e_locale(url):
        raise ErroreDistilla("La distillazione si fa solo con il modello su questo computer: l'indirizzo di Ollama "
                             "nelle Impostazioni non è locale.")
    if not modello:
        raise ErroreDistilla("Nessun modello di Ollama scelto (Impostazioni › Modelli AI).")
    return url, modello


def _chiedi(url, modello, sistema, utente, schema, stop):
    import relazione_incontro as rel
    try:
        risposta = rel._chiama(url, modello, [{"role": "system", "content": sistema},
                                              {"role": "user", "content": utente}],
                               formato=schema, contesto=16384, stop=stop)
        return json.loads(risposta)
    except rel.ErroreRelazione as e:
        raise ErroreDistilla(str(e)) from None
    except json.JSONDecodeError:
        raise ErroreDistilla("Il modello non ha risposto nel formato atteso: riprova o scegli un altro modello.") from None


def _normalizza(dati):
    out = {"sintesi": str(dati.get("sintesi") or "").strip()}
    for k in LISTE:
        valori = dati.get(k) or []
        out[k] = [str(x).strip() for x in valori if str(x).strip()] if isinstance(valori, list) else []
    return out


def distilla(scheda, stato=lambda _t: None, stop=None):
    """Distilla e salva nella base l'incontro della scheda. Ritorna l'id della voce."""
    url, modello = _modello()
    testo, parlanti = testo_incontro(scheda)
    categoria, funzioni = contesto(scheda)
    aziende, persone, siti = nomi_noti(parlanti)
    # il modello non vede i nomi che Argo conosce già: li toglie prima il controllo senza modello
    # (i parlanti diventano «Persona 1, 2…», così si distingue ancora chi dice cosa)
    testo = anonimizza_testo(testo, aziende, persone, siti, numera=True)
    sistema = ISTRUZIONI.format(contesto=_descrivi_contesto(categoria, funzioni), massimo=MAX_VOCI,
                                regole=etica.REGOLE + etica.REGOLE_PERSONE)
    parziali = []
    blocchi = _blocchi(testo)
    for n, b in enumerate(blocchi, 1):
        if stop and stop():
            raise ErroreDistilla("Interrotto.")
        stato(f"Distillo l'incontro{f' ({n} di {len(blocchi)})' if len(blocchi) > 1 else ''}…")
        parziali.append(_normalizza(_chiedi(url, modello, sistema, b, SCHEMA, stop)))
    if len(parziali) > 1:
        stato("Unisco le parti…")
        contenuti = _normalizza(_chiedi(url, modello, ISTRUZIONI_CONSOLIDA.format(
            massimo=MAX_VOCI, regole=etica.REGOLE), json.dumps(parziali, ensure_ascii=False), SCHEMA, stop))
    else:
        contenuti = parziali[0]
    stato("Controllo che non restino nomi…")
    contenuti = _applica(contenuti, lambda t: anonimizza_testo(t, aziende, persone, siti))
    contenuti = controllo_finale(contenuti, url, modello, stop)
    contenuti = etica.pulisci_dati(contenuti)
    if not contenuti["sintesi"] and not any(contenuti[k] for k in LISTE):
        raise ErroreDistilla("Nessun fatto di lavoro da salvare in questo incontro.")
    v = {"id": uuid.uuid4().hex[:12], "mese": (scheda.get("quando") or "")[:7], "azienda": categoria,
         "funzioni": funzioni, "contenuti": contenuti, "modello": modello, "regole": VERSIONE_REGOLE}
    # irreversibile: nella voce non c'è nulla dell'incontro (né id, né percorso, né titolo, né nome)
    precedente = scheda.get("base")
    salva_voce(v, sostituisci=precedente)
    if precedente:
        _salva_vettore(precedente, None)
    _indicizza(v)
    with sc._lock:
        elenco = sc._leggi(sc.FILE_INCONTRI)
        for i in elenco:
            if i.get("id") == scheda.get("id"):
                i["base"] = v["id"]
        sc._scrivi(sc.FILE_INCONTRI, elenco)
    return v["id"]


def controllo_finale(contenuti, url, modello, stop=None):
    """Terzo passo: il modello cerca i nomi propri rimasti e si tolgono."""
    testo = in_testo({"contenuti": contenuti})
    trovati = _chiedi(url, modello, ISTRUZIONI_NOMI, testo, SCHEMA_NOMI, stop).get("nomi") or []
    ammessi = {x.lower() for x in sc.AREE_GEOGRAFICHE + sc.SETTORI}
    da_togliere = [n.strip() for n in trovati if isinstance(n, str) and len(n.strip()) >= 2
                   and n.strip().lower() not in ammessi and n.strip().lower() in testo.lower()]
    if not da_togliere:
        return contenuti
    return _applica(contenuti, lambda t: _togli(t, da_togliere))


def _togli(testo, nomi):
    for n in sorted(nomi, key=len, reverse=True):
        testo = re.sub(rf"(?i)(?<!\w){re.escape(n)}(?!\w)", "[…]", testo)
    return testo


def _indicizza(v):
    """Embedding della voce, se c'è un modello per i documenti. Senza, la base funziona lo stesso."""
    import llm_locale as llm
    s = core.carica_impostazioni()
    url, modello = s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_embed")
    if not modello or not llm.e_locale(url):
        return False
    try:
        _salva_vettore(v["id"], llm.embed([in_testo(v)], modello, url)[0])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- testo leggibile e modificabile
def descrivi(v):
    """Riga di contesto anonima: «Manifatturiero, Media (50-249), Piemonte · Responsabile IT»."""
    az = ", ".join(x for k, x in (v.get("azienda") or {}).items() if x and k != "tipo_attivita"
                   and not x.startswith("Non not"))
    fz = ", ".join(f.get("ruolo") or f.get("area", "") for f in v.get("funzioni", []))
    return " · ".join(x for x in (az, fz) if x)


def in_testo(v):
    c = v.get("contenuti") or {}
    righe = []
    for k, titolo in SEZIONI:
        if k == "sintesi":
            if c.get("sintesi"):
                righe += [f"## {titolo}", c["sintesi"], ""]
        elif c.get(k):
            righe += [f"## {titolo}"] + [f"- {x}" for x in c[k]] + [""]
    return "\n".join(righe).strip()


def da_testo(testo):
    """Il contrario di in_testo: dal testo modificato dall'utente ai contenuti."""
    titoli = {t.lower(): k for k, t in SEZIONI}
    out, attuale = {"sintesi": ""}, None
    for k in LISTE:
        out[k] = []
    for riga in testo.splitlines():
        r = riga.strip()
        if r.startswith("## "):
            attuale = titoli.get(r[3:].strip().lower())
        elif attuale == "sintesi" and r:
            out["sintesi"] = (out["sintesi"] + " " + r).strip()
        elif attuale in LISTE and r.startswith(("-", "•", "*")):
            if r.lstrip("-•* ").strip():
                out[attuale].append(r.lstrip("-•* ").strip())
    return out


def modifica_voce(id_, testo):
    """Salva le modifiche dell'utente, ripassando l'anonimizzazione senza modello e il filtro etico."""
    v = voce(id_)
    if not v:
        return
    aziende, persone, siti = nomi_noti()
    contenuti = _applica(da_testo(testo), lambda t: anonimizza_testo(t, aziende, persone, siti))
    v["contenuti"] = etica.pulisci_dati(contenuti)
    salva_voce(v)
    _indicizza(v)
