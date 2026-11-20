"""secondo_cervello.py - Secondo cervello (metodo CODE), Fase A: locale e personale.

Questo primo blocco è la parte «Organizza» del metodo: con chi si parla in ogni incontro.
    - Interruttore, spento di base; criterio IT «secondo_cervello»: false lo vieta.
    - Catalogo aziende: settore, dimensione, tipo di attività, area geografica, note. Si compila a mano o con la
      ricerca web (come la pagina Clienti) e un modello che sceglie le categorie.
    - Catalogo funzioni: le persone si catalogano per FUNZIONE (ruolo, area, livello), mai per identità.
      Nessun nome, nessuna ricerca web sulle persone.
    - Interlocutori di ogni incontro (registrazione, Live, incontro dall'iPhone, file in coda): azienda + funzioni.
Tutto resta in APP_HOME/secondo_cervello/ su questo computer. La base anonimizzata per i suggerimenti
(«Distilla» ed «Esprimi») arriva nei blocchi successivi e non conterrà nomi di aziende o persone.
Solo libreria standard (più i moduli di Argo per la ricerca web e il modello).
"""
import json
import threading
import uuid
from datetime import datetime

import criteri
import voci_core as core

CARTELLA = core.APP_HOME / "secondo_cervello"
FILE_AZIENDE = CARTELLA / "aziende.json"
FILE_FUNZIONI = CARTELLA / "funzioni.json"
FILE_INCONTRI = CARTELLA / "incontri.json"

SETTORI = ["Manifatturiero", "Alimentare e bevande", "Agricoltura", "Edilizia e impianti", "Energia e utility",
           "Trasporti e logistica", "Commercio all'ingrosso", "Commercio al dettaglio", "Servizi alle imprese",
           "Informatica e telecomunicazioni", "Finanza e assicurazioni", "Sanità e farmaceutico",
           "Pubblica amministrazione", "Istruzione e formazione", "Turismo e ristorazione", "Studi professionali",
           "Terzo settore", "Altro"]
DIMENSIONI = ["Micro (meno di 10 addetti)", "Piccola (10-49)", "Media (50-249)", "Grande (250 e oltre)",
              "Non nota"]
TIPI_ATTIVITA = ["Produzione", "Servizi", "Distribuzione", "Vendita al dettaglio", "Progettazione e consulenza",
                 "Ente pubblico", "Altro"]
AREE_GEOGRAFICHE = ["Piemonte", "Valle d'Aosta", "Lombardia", "Liguria", "Trentino-Alto Adige", "Veneto",
                    "Friuli-Venezia Giulia", "Emilia-Romagna", "Toscana", "Umbria", "Marche", "Lazio", "Abruzzo",
                    "Molise", "Campania", "Puglia", "Basilicata", "Calabria", "Sicilia", "Sardegna",
                    "Più regioni italiane", "Estero (UE)", "Estero (fuori UE)", "Non nota"]
AREE_FUNZIONE = ["Direzione generale", "Informatica (IT)", "Amministrazione e finanza", "Acquisti",
                 "Commerciale e vendite", "Marketing e comunicazione", "Produzione", "Logistica",
                 "Qualità", "Ricerca e sviluppo", "Risorse umane", "Legale e compliance", "Assistenza clienti",
                 "Consulente esterno", "Altro"]
LIVELLI = ["Direzione", "Responsabile", "Operativo", "Non noto"]

_lock = threading.Lock()


# ---------------------------------------------------------------- attivazione
def vietato():
    """True se l'IT l'ha vietato con i criteri aziendali («secondo_cervello»: false)."""
    return criteri.carica().get("secondo_cervello") is False


def attivo():
    return bool(core.carica_impostazioni().get("secondo_cervello")) and not vietato()


def imposta(acceso):
    s = core.carica_impostazioni()
    s["secondo_cervello"] = bool(acceso) and not vietato()
    core.salva_impostazioni(s)


# ---------------------------------------------------------------- file
def _leggi(file):
    try:
        dati = json.loads(file.read_text(encoding="utf-8"))
        return dati if isinstance(dati, list) else []
    except Exception:
        return []


def _scrivi(file, dati):
    CARTELLA.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(file)


def _adesso():
    return datetime.now().isoformat(timespec="seconds")


def _salva_in(file, elemento, campi):
    """Aggiunge o aggiorna (per id) un elemento con i soli campi ammessi. Ritorna l'elemento salvato."""
    with _lock:
        elenco = _leggi(file)
        pulito = {k: (str(elemento.get(k) or "").strip()) for k in campi}
        esistente = next((e for e in elenco if e.get("id") and e.get("id") == elemento.get("id")), None)
        if esistente:
            esistente.update(pulito, aggiornato=_adesso())
            salvato = esistente
        else:
            salvato = dict(pulito, id=uuid.uuid4().hex[:12], creato=_adesso(), aggiornato=_adesso())
            elenco.append(salvato)
        _scrivi(file, elenco)
        return dict(salvato)


def _togli_da(file, id_):
    with _lock:
        elenco = _leggi(file)
        _scrivi(file, [e for e in elenco if e.get("id") != id_])


# ---------------------------------------------------------------- catalogo aziende
CAMPI_AZIENDA = ("nome", "sito", "settore", "dimensione", "tipo_attivita", "area", "note", "fonte")


def aziende():
    return sorted(_leggi(FILE_AZIENDE), key=lambda a: a.get("nome", "").lower())


def azienda(id_):
    return next((a for a in _leggi(FILE_AZIENDE) if a.get("id") == id_), None)


def salva_azienda(a):
    if not str(a.get("nome") or "").strip():
        raise ValueError("Serve il nome dell'azienda.")
    return _salva_in(FILE_AZIENDE, a, CAMPI_AZIENDA)


def elimina_azienda(id_):
    _togli_da(FILE_AZIENDE, id_)
    _scollega("azienda", id_)


def descrivi_azienda(a, con_nome=True):
    """«Rossi Srl · Manifatturiero, Media (50-249), Piemonte». Senza nome: solo la categoria."""
    if not a:
        return ""
    parti = [a.get(k) for k in ("settore", "dimensione", "area") if a.get(k) and not a[k].startswith("Non not")]
    categoria = ", ".join(parti) or "categoria da completare"
    return f"{a.get('nome', '')} · {categoria}" if con_nome else categoria


# ---------------------------------------------------------------- catalogo funzioni (mai persone)
CAMPI_FUNZIONE = ("ruolo", "area", "livello")


def funzioni():
    return sorted(_leggi(FILE_FUNZIONI), key=lambda f: (f.get("area", ""), f.get("ruolo", "").lower()))


def funzione(id_):
    return next((f for f in _leggi(FILE_FUNZIONI) if f.get("id") == id_), None)


def salva_funzione(f):
    if not str(f.get("ruolo") or "").strip() and not str(f.get("area") or "").strip():
        raise ValueError("Serve almeno il ruolo o l'area.")
    simile = next((x for x in _leggi(FILE_FUNZIONI) if not f.get("id")
                   and all(x.get(k, "").lower() == str(f.get(k) or "").strip().lower() for k in CAMPI_FUNZIONE)), None)
    return dict(simile) if simile else _salva_in(FILE_FUNZIONI, f, CAMPI_FUNZIONE)


def elimina_funzione(id_):
    _togli_da(FILE_FUNZIONI, id_)
    _scollega("funzione", id_)


def descrivi_funzione(f):
    """«Responsabile IT (Informatica (IT), Responsabile)»"""
    if not f:
        return ""
    dettagli = ", ".join(x for x in (f.get("area"), f.get("livello")) if x and not x.startswith("Non not"))
    ruolo = f.get("ruolo") or f.get("area") or "Funzione"
    return f"{ruolo} ({dettagli})" if dettagli and dettagli != ruolo else ruolo


# ---------------------------------------------------------------- interlocutori degli incontri
ORIGINI = {"live": "Registra · Live", "archivio": "Registra · archivio", "incontro": "Incontro dall'iPhone",
           "file": "Trascrivi"}


def incontri():
    return sorted(_leggi(FILE_INCONTRI), key=lambda i: i.get("quando", ""), reverse=True)


def interlocutori_di(riferimento):
    """La scheda «con chi» collegata a un incontro (cartella, file o id), o None."""
    rif = str(riferimento)
    return next((i for i in _leggi(FILE_INCONTRI) if rif in (i.get("riferimento"), i.get("id"))), None)


def salva_interlocutori(riferimento, titolo, origine, azienda_id, funzioni_id, id_=None):
    """Collega a un incontro l'azienda e le funzioni delle persone. Ritorna l'id della scheda."""
    with _lock:
        elenco = _leggi(FILE_INCONTRI)
        rif = str(riferimento) if riferimento else ""
        voce = next((i for i in elenco if (id_ and i.get("id") == id_) or (rif and i.get("riferimento") == rif)), None)
        if voce is None:
            voce = {"id": id_ or uuid.uuid4().hex[:12], "quando": _adesso()}
            elenco.append(voce)
        voce.update(riferimento=rif or voce.get("riferimento", ""), titolo=(titolo or "").strip(),
                    origine=origine if origine in ORIGINI else "file", azienda=azienda_id or "",
                    funzioni=[f for f in funzioni_id if f], aggiornato=_adesso())
        _scrivi(FILE_INCONTRI, elenco)
        return voce["id"]


def aggiorna_riferimento(id_, riferimento):
    """Quando un incontro cambia posto (Live conclusa, registrazione salvata), la scheda lo segue."""
    with _lock:
        elenco = _leggi(FILE_INCONTRI)
        for i in elenco:
            if i.get("id") == id_:
                i["riferimento"] = str(riferimento)
                _scrivi(FILE_INCONTRI, elenco)
                return


def elimina_interlocutori(id_):
    _togli_da(FILE_INCONTRI, id_)


def _scollega(campo, id_):
    with _lock:
        elenco = _leggi(FILE_INCONTRI)
        for i in elenco:
            if campo == "azienda" and i.get("azienda") == id_:
                i["azienda"] = ""
            elif campo == "funzione" and id_ in i.get("funzioni", []):
                i["funzioni"] = [f for f in i["funzioni"] if f != id_]
        _scrivi(FILE_INCONTRI, elenco)


def svuota():
    """Cancella cataloghi e schede degli incontri (gli incontri veri restano dove sono)."""
    with _lock:
        for f in (FILE_AZIENDE, FILE_FUNZIONI, FILE_INCONTRI):
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------- catalogazione automatica di un'azienda
SCHEMA_CATEGORIE = {
    "type": "object",
    "properties": {
        "settore": {"type": "string", "enum": SETTORI},
        "dimensione": {"type": "string", "enum": DIMENSIONI},
        "tipo_attivita": {"type": "string", "enum": TIPI_ATTIVITA},
        "area": {"type": "string", "enum": AREE_GEOGRAFICHE},
        "sito": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["settore", "dimensione", "tipo_attivita", "area", "sito", "note"],
}

ISTRUZIONI_CATEGORIE = """Classifichi un'azienda per un catalogo di lavoro, usando SOLO le fonti fornite.
- Scegli settore, dimensione, tipo di attività e area geografica tra i valori ammessi. Se le fonti non bastano per
  la dimensione o l'area, usa «Non nota»: non indovinare.
- «sito»: il sito ufficiale se compare nelle fonti, altrimenti stringa vuota.
- «note»: al massimo due frasi in italiano su cosa fa l'azienda (prodotti, servizi, mercati). Solo fatti
  aziendali: niente persone, niente giudizi, niente dati personali.
- Se le fonti parlano di aziende diverse con lo stesso nome, usa quella che corrisponde ai dettagli forniti e dillo
  nelle note."""


def cataloga_da_fonti(nome, testi, dettagli="", stato=lambda _t: None, stop=None):
    """Chiede al modello le categorie a partire dai testi delle fonti. Ritorna un dict con i CAMPI_AZIENDA."""
    import etica
    import llm_locale as llm
    import scheda_cliente as scheda
    s = core.carica_impostazioni()
    url, modello = s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_chat")
    fonti = "\n\n".join(f"### Fonte {n}\n{t[:4000]}" for n, t in enumerate(testi, 1) if t)
    if not fonti:
        raise RuntimeError("Nessuna informazione trovata su questa azienda.")
    stato("Il modello sceglie le categorie…")
    risposta = scheda._chiama(modello, url, ISTRUZIONI_CATEGORIE,
                              f"Azienda: {nome}\nDettagli forniti: {dettagli or 'nessuno'}\n\n{fonti}",
                              formato=SCHEMA_CATEGORIE, stop=stop)
    dati = json.loads(risposta)
    dati = {k: str(dati.get(k) or "") for k in SCHEMA_CATEGORIE["properties"]}
    dati["note"] = etica.pulisci(dati["note"])
    for campo, ammessi in (("settore", SETTORI), ("dimensione", DIMENSIONI), ("tipo_attivita", TIPI_ATTIVITA),
                           ("area", AREE_GEOGRAFICHE)):
        if dati[campo] not in ammessi:
            dati[campo] = ammessi[-1]
    return dict(dati, nome=nome, fonte="ricerca")


def cataloga(nome, dettagli="", stato=lambda _t: None, stop=None):
    """Catalogazione automatica: prima la scheda pubblica già fatta in Clienti, se c'è; altrimenti la ricerca web
    (uscita registrata in «Cosa è uscito» da ricerca_web)."""
    import ricerca_web as web
    import scheda_cliente as scheda
    salvate = scheda.schede_salvate(nome)
    if salvate:
        stato("Uso la scheda pubblica già preparata nella pagina Clienti…")
        return cataloga_da_fonti(nome, [salvate[0].read_text(encoding="utf-8")], dettagli, stato, stop)
    if web.vietata():
        raise RuntimeError("La ricerca web è disattivata dai criteri aziendali: compila le categorie a mano.")
    if not web.configurata():
        raise RuntimeError("Ricerca web non configurata (Impostazioni › Collegamenti › Ricerca web): "
                           "compila le categorie a mano.")
    stato("Cerco l'azienda sul web…")
    risultati = web.cerca(f"{nome} {dettagli} azienda".strip(), massimo=5)
    testi = [f"{r.get('title', '')} · {r.get('url', '')}\n{r.get('content', '')}" for r in risultati]
    return cataloga_da_fonti(nome, testi, dettagli, stato, stop)
