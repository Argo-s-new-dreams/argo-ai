"""relazione_incontro.py - relazione di un incontro ricevuto da Argo per iPhone, con Ollama in locale.

Passi
1. Foto: se è scelto un modello vision (es. gemma3, qwen2.5vl), ogni foto viene descritta; per biglietti da
   visita e documenti si estraggono anche i dati leggibili. Le descrizioni restano in cache nell'incontro.
2. Cronologia: frasi con chi parla e minuto, intercalate alle foto (testo letto sull'iPhone + descrizione).
3. Relazione strutturata (JSON con schema) pensata anche per il CRM: contatti, aziende, opportunità, azioni.

Tutto resta su questo computer: Ollama deve essere locale (llm_locale.e_locale).
Nell'incontro: argo-relazione.json (dati) e relazione-argo.md (testo modificabile).
"""
import base64
import json
import re
from datetime import datetime
from pathlib import Path

import cloud
import etica
import llm_locale as llm
import risorse
import template_relazione as tpl

FILE_DATI = "argo-relazione.json"
FILE_TESTO = "relazione-argo.md"
CARATTERI_PER_BLOCCO = 12_000

# Nomi tipici dei modelli vision in Ollama, se il server non dichiara le «capabilities»
INDIZI_VISION = ("vl", "vision", "llava", "gemma3", "minicpm-v", "moondream", "mistral-small3", "llama4", "granite3.2-vision")


class ErroreRelazione(RuntimeError):
    pass


# ---------------------------------------------------------------- Ollama
def _chiama(url, modello, messaggi, formato=None, contesto=16384, stop=None, motore=None):
    """Una richiesta al modello. `motore` = (fornitore, modello) cloud; None o ("locale", _) = Ollama locale."""
    if motore and motore[0] != cloud.LOCALE:
        if stop and stop():
            raise ErroreRelazione("Interrotto.")
        try:
            return cloud.chat(motore[0], motore[1], messaggi, temperatura=0.2, stop=stop, formato=formato)
        except cloud.ErroreCloud as e:
            raise ErroreRelazione(str(e)) from None
    payload = {"model": modello, "messages": messaggi, "stream": False,
               "options": risorse.opzioni_ollama({"temperature": 0.2, "num_ctx": contesto}),
               "keep_alive": risorse.keep_alive()}
    if formato:
        payload["format"] = formato
    with risorse.turno():  # profilo Leggero: aspetta che finisca un'eventuale trascrizione
        if stop and stop():
            raise ErroreRelazione("Interrotto.")
        with llm._req(url, "/api/chat", payload, timeout=1800) as r:
            dati = json.load(r)
    if dati.get("error"):
        raise ErroreRelazione(dati["error"])
    testo = dati.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>\s*", "", testo, flags=re.S).strip()


def modelli_vision(url):
    """Modelli installati in grado di guardare immagini."""
    chat, _emb = llm.elenco_modelli(url)
    trovati = []
    for nome in chat:
        capacita = None
        try:
            with llm._req(url, "/api/show", {"model": nome}, timeout=llm.TEMPO_BREVE) as r:
                capacita = json.load(r).get("capabilities")
        except Exception:
            pass
        if capacita is not None:
            if "vision" in capacita:
                trovati.append(nome)
        elif any(i in nome.lower() for i in INDIZI_VISION):
            trovati.append(nome)
    return trovati


# ---------------------------------------------------------------- dati dell'incontro
def _durata(secondi):
    s = int(secondi or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def carica(cartella):
    p = Path(cartella) / FILE_DATI
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salva(cartella, dati):
    (Path(cartella) / FILE_DATI).write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")


def cronologia(cartella, sessione, descrizioni=None):
    """Testo dell'incontro: parole con chi parla, foto con testo letto e descrizione, in ordine di tempo."""
    descrizioni = descrizioni or {}
    nomi = {p["id"]: p.get("nome") or p["id"] for p in sessione.get("partecipanti", [])}
    voci = []
    for s in sessione.get("segmenti", []):
        chi = nomi.get(s.get("parlante"), s.get("parlante"))
        voci.append((float(s.get("inizio", 0)), f"[{_durata(s.get('inizio'))}] " + (f"{chi}: " if chi else "") + s.get("testo", "")))
    for i, f in enumerate(sessione.get("foto", []), 1):
        parti = []
        if f.get("testo"):
            parti.append("testo letto: " + f["testo"].replace("\n", " · "))
        if descrizioni.get(f.get("file")):
            parti.append("descrizione: " + descrizioni[f["file"]].replace("\n", " "))
        dettaglio = " | ".join(parti) or "nessun testo leggibile"
        voci.append((float(f.get("secondo", 0)), f"[{_durata(f.get('secondo'))}] 📷 FOTO {i}: {dettaglio}"))
    for a in sessione.get("allegati", []):  # documenti aggiunti sul computer (PDF, Word, testo)
        corpo = (a.get("testo") or "").strip() or "nessun testo leggibile"
        voci.append((float(a.get("secondo", 0)), f"[{_durata(a.get('secondo'))}] 📎 ALLEGATO «{a.get('nome', a.get('file', ''))}»:\n{corpo}"))
    if not voci and sessione.get("trascrizioneLegacy"):
        return sessione["trascrizioneLegacy"]
    return "\n".join(t for _s, t in sorted(voci, key=lambda x: x[0]))


# ---------------------------------------------------------------- 1 · foto con il modello vision
PROMPT_FOTO = (
    "Questa foto è stata scattata durante un incontro di lavoro (fiera o visita a un cliente). "
    "Rispondi in italiano, al massimo 6 righe, senza inventare. "
    "Se è un biglietto da visita: nome e cognome, ruolo, azienda, email, telefoni, sito, indirizzo. "
    "Se è un prodotto, uno stand, una brochure, un listino o un documento: cosa mostra e i dati leggibili "
    "(marchi, modelli, prezzi, quantità). Se non si capisce, dillo."
)


def foto_da_descrivere(cartella, sessione, modello):
    cache = carica(cartella).get("foto", {})
    return [f for f in sessione.get("foto", [])
            if (Path(cartella) / f.get("file", "")).exists() and (cache.get(f.get("file")) or {}).get("modello") != modello]


def descrivi_foto(cartella, sessione, url, modello, stato=lambda _t: None, stop=None, fatta=lambda: None,
                  motore=None):
    """Descrive le foto non ancora descritte con quel modello. Ritorna {file: descrizione}.
    `fatta()` viene chiamata dopo ogni foto (per la barra di avanzamento)."""
    cartella = Path(cartella)
    dati = carica(cartella)
    cache = dati.setdefault("foto", {})
    foto = sessione.get("foto", [])
    for i, f in enumerate(foto, 1):
        nome = f.get("file")
        voce = cache.get(nome)
        if voce and voce.get("modello") == modello:
            continue
        percorso = cartella / nome
        if not percorso.exists():
            continue
        stato(f"Guardo la foto {i} di {len(foto)} con {modello}…")
        immagine = base64.b64encode(percorso.read_bytes()).decode("ascii")
        aiuto = f" Il telefono vi ha già letto questo testo: {f['testo']}" if f.get("testo") else ""
        testo = _chiama(url, modello, [{"role": "user", "content": PROMPT_FOTO + aiuto, "images": [immagine]}],
                        contesto=8192, stop=stop, motore=motore)
        cache[nome] = {"modello": modello, "descrizione": testo}
        _salva(cartella, dati)
        fatta()
    return {k: v["descrizione"] for k, v in cache.items()}


# ---------------------------------------------------------------- 2-3 · relazione strutturata
ISTRUZIONI = """Sei l'assistente che scrive la relazione di un incontro di lavoro (fiera, visita a un cliente, riunione, intervista).
Il testo ha righe «[minuto] Nome: frase». Le righe «📷 FOTO» sono foto scattate in quel momento, con il testo letto
e una descrizione: usale per identificare persone, aziende, recapiti e prodotti, e collegale a ciò che si dice.
Le righe «📎 ALLEGATO» sono documenti aggiunti all'incontro (offerte, listini, presentazioni): usali come fonte
di dati e cita il documento quando ne riprendi cifre o nomi.
Chi registra è la persona indicata come «Io» (o con il nome dell'utente): non è un contatto.
Regole: usa solo informazioni presenti; nessun nome, recapito, cifra o data inventati; campi sconosciuti vuoti.
Scrivi in italiano, in modo concreto e professionale.""" + etica.REGOLE

SCHEMA = {
    "type": "object",
    "properties": {
        "titolo": {"type": "string"},
        "tipo": {"type": "string", "enum": ["fiera", "visita cliente", "riunione", "altro"]},
        "riassunto": {"type": "string"},
        "contatti": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "cognome": {"type": "string"}, "ruolo": {"type": "string"},
            "azienda": {"type": "string"}, "email": {"type": "string"}, "telefono": {"type": "string"},
            "cellulare": {"type": "string"}, "sito": {"type": "string"}, "note": {"type": "string"}},
            "required": ["nome"]}},
        "aziende": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "settore": {"type": "string"}, "sito": {"type": "string"},
            "citta": {"type": "string"}, "note": {"type": "string"}}, "required": ["nome"]}},
        "interessi": {"type": "array", "items": {"type": "string"}},
        "opportunita": {"type": "object", "properties": {
            "descrizione": {"type": "string"}, "prodotti": {"type": "array", "items": {"type": "string"}},
            "budget": {"type": "string"}, "tempistica": {"type": "string"},
            "decisori": {"type": "string"}, "concorrenti": {"type": "string"}, "prossimo_passo": {"type": "string"}}},
        "punti_chiave": {"type": "array", "items": {"type": "string"}},
        "azioni": {"type": "array", "items": {"type": "object", "properties": {
            "descrizione": {"type": "string"}, "responsabile": {"type": "string"}, "scadenza": {"type": "string"}},
            "required": ["descrizione"]}},
        # sezioni usate dai template (vedi template_relazione.py)
        "esigenze": {"type": "array", "items": {"type": "string"}},
        "temi": {"type": "array", "items": {"type": "object", "properties": {
            "tema": {"type": "string"}, "sintesi": {"type": "string"}, "citazione": {"type": "string"}},
            "required": ["tema", "sintesi"]}},
        "decisioni": {"type": "array", "items": {"type": "string"}},
        "punti_aperti": {"type": "array", "items": {"type": "string"}},
        "rischi": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titolo", "tipo", "riassunto", "contatti", "aziende", "interessi", "opportunita",
                 "punti_chiave", "azioni", "esigenze", "temi", "decisioni", "punti_aperti", "rischi"],
}


def _blocchi(testo, massimo):
    righe, blocchi, corrente = testo.split("\n"), [], ""
    for r in righe:
        if corrente and len(corrente) + len(r) + 1 > massimo:
            blocchi.append(corrente)
            corrente = ""
        corrente += ("\n" if corrente else "") + r
    if corrente:
        blocchi.append(corrente)
    return blocchi


def scrivi_relazione(cartella, sessione, url, modello_testo, modello_vision=None, stato=lambda _t: None, stop=None,
                     avanzamento=lambda _p: None, attrezzo="incontri", template=None):
    """Genera la relazione e la salva nell'incontro. Ritorna (dati_relazione, markdown).
    `template`: id o dizionario di template_relazione (None = il predefinito delle Impostazioni).
    `avanzamento(percento)` riceve 0-100: foto e blocchi pesano 1 ciascuno, la relazione finale 3.
    `attrezzo` decide, dalle Impostazioni › Modelli cloud, se testo e foto vanno a un modello cloud."""
    m_testo = cloud.motore(attrezzo)
    m_foto = cloud.motore(attrezzo + "_foto") if attrezzo == "incontri" else m_testo
    if m_testo[0] != cloud.LOCALE:
        modello_testo = cloud.etichetta(*m_testo)
        stato(cloud.avviso(attrezzo))
    if m_foto[0] != cloud.LOCALE and (modello_vision or attrezzo == "incontri"):  # foto al cloud scelto
        modello_vision = cloud.etichetta(*m_foto)
        stato(cloud.avviso(attrezzo + "_foto") if attrezzo == "incontri" else cloud.avviso(attrezzo))
    if (m_testo[0] == cloud.LOCALE or (modello_vision and m_foto[0] == cloud.LOCALE)) and not llm.e_locale(url):
        raise ErroreRelazione("L'indirizzo di Ollama non è locale: per gli incontri si usa solo un modello su questo computer.")
    if not modello_testo:
        raise ErroreRelazione("Scegli un modello per i testi in Impostazioni › Modelli.")
    if isinstance(template, str):
        template = tpl.trova(template)
    template = template or tpl.predefinito()
    istruzioni = ISTRUZIONI + "\n\n" + tpl.guida(template)
    cartella = Path(cartella)
    # Stima del lavoro, per una barra che avanza in modo onesto
    da_guardare = len(foto_da_descrivere(cartella, sessione, modello_vision)) if modello_vision else 0
    testo_stimato = cronologia(cartella, sessione)
    stima_blocchi = len(_blocchi(testo_stimato, CARATTERI_PER_BLOCCO)) if len(testo_stimato) > CARATTERI_PER_BLOCCO else 0
    totale = da_guardare + stima_blocchi + 3
    fatto = {"n": 0}

    def passo(unita=1):
        fatto["n"] += unita
        avanzamento(min(99, int(fatto["n"] * 100 / max(totale, 1))))

    avanzamento(1)
    descrizioni = {}
    if modello_vision and sessione.get("foto"):
        descrizioni = descrivi_foto(cartella, sessione, url, modello_vision, stato, stop, fatta=passo, motore=m_foto)
    testo = cronologia(cartella, sessione, descrizioni)
    if not testo.strip():
        raise ErroreRelazione("L'incontro non ha né trascrizione né foto.")

    # Incontri lunghi: appunti a blocchi, poi la relazione sugli appunti
    giro = 0
    while len(testo) > CARATTERI_PER_BLOCCO and giro < 3:
        blocchi = _blocchi(testo, CARATTERI_PER_BLOCCO)
        appunti = []
        for i, b in enumerate(blocchi, 1):
            stato(f"Prendo appunti · parte {i} di {len(blocchi)}…")
            appunti.append(_chiama(url, modello_testo, [
                {"role": "system", "content": istruzioni},
                {"role": "user", "content": "Scrivi appunti fedeli e sintetici di questa parte (chi è chi, aziende, "
                                            "prodotti, richieste, cifre, decisioni, azioni). Conserva nomi e recapiti "
                                            "delle righe FOTO.\n\n" + b}], stop=stop, motore=m_testo))
            passo()
        testo = "\n\n".join(appunti)
        giro += 1

    stato(f"Scrivo la relazione «{template['nome']}» con {modello_testo}…")
    intestazione = (f"Titolo provvisorio: {sessione.get('titolo', '')}\n"
                    f"Data: {(sessione.get('creata') or '')[:16].replace('T', ' ')} · durata {_durata(sessione.get('durata'))}\n"
                    f"Partecipanti: {', '.join(p.get('nome', p['id']) for p in sessione.get('partecipanti', [])) or 'non indicati'}\n\n")
    risposta = _chiama(url, modello_testo, [
        {"role": "system", "content": istruzioni},
        {"role": "user", "content": intestazione + testo}], formato=SCHEMA, stop=stop, motore=m_testo)
    try:
        relazione = json.loads(risposta)
    except json.JSONDecodeError:
        raise ErroreRelazione(f"Il modello {modello_testo} non ha restituito una relazione strutturata: prova un altro modello.") from None

    relazione = etica.pulisci_dati(relazione)  # rete di sicurezza del filtro etico
    dati = carica(cartella)
    dati.update({
        "relazione": relazione,
        "modello_testo": modello_testo,
        "modello_vision": modello_vision or None,
        "generata": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "template": {"id": template["id"], "nome": template["nome"], "sezioni": template["sezioni"]},
    })
    _salva(cartella, dati)
    md = in_markdown(relazione, sessione, dati)
    (cartella / FILE_TESTO).write_text(md, encoding="utf-8")
    avanzamento(100)
    return relazione, md


def _riga(*parti):
    return " · ".join(p for p in parti if p)


def _contatti(r):
    out = []
    for c in r.get("contatti") or []:
        nome = _riga(" ".join(x for x in (c.get("nome"), c.get("cognome")) if x))
        out.append(f"- **{nome}** — " + _riga(c.get("ruolo"), c.get("azienda"), c.get("email"),
                                               c.get("telefono"), c.get("cellulare"), c.get("sito")))
        if c.get("note"):
            out.append(f"    - {c['note']}")
    return out


def _opportunita(r):
    o = r.get("opportunita") or {}
    if not any(o.get(k) for k in ("descrizione", "prodotti", "budget", "tempistica", "prossimo_passo")):
        return []
    out = []
    for etichetta, chiave in (("Descrizione", "descrizione"), ("Budget", "budget"), ("Tempistica", "tempistica"),
                              ("Decisori", "decisori"), ("Concorrenti", "concorrenti"), ("Prossimo passo", "prossimo_passo")):
        if o.get(chiave):
            out.append(f"- **{etichetta}:** {o[chiave]}")
    if o.get("prodotti"):
        out.append("- **Prodotti/servizi:** " + ", ".join(o["prodotti"]))
    return out


def _temi(r):
    out = []
    for x in r.get("temi") or []:
        out += [f"### {x.get('tema', '')}", "", x.get("sintesi", "")]
        if x.get("citazione"):
            out += ["", f"> «{x['citazione']}»"]
        out.append("")
    return out[:-1] if out else out


def _elenco(chiave):
    return lambda r: [f"- {v}" for v in r.get(chiave) or [] if v]


SCRITTORI = {
    "riassunto": lambda r: [r["riassunto"]] if r.get("riassunto") else [],
    "contatti": _contatti,
    "aziende": lambda r: [f"- **{a.get('nome')}** — " + _riga(a.get("settore"), a.get("citta"), a.get("sito"), a.get("note"))
                          for a in r.get("aziende") or []],
    "esigenze": _elenco("esigenze"),
    "interessi": _elenco("interessi"),
    "opportunita": _opportunita,
    "temi": _temi,
    "punti_chiave": _elenco("punti_chiave"),
    "decisioni": _elenco("decisioni"),
    "punti_aperti": _elenco("punti_aperti"),
    "rischi": _elenco("rischi"),
    "azioni": lambda r: [f"- [ ] {_riga(a.get('descrizione'), a.get('responsabile'), ('entro ' + a['scadenza']) if a.get('scadenza') else '')}"
                         for a in r.get("azioni") or []],
}
ORDINE_CLASSICO = ["riassunto", "contatti", "aziende", "opportunita", "interessi", "punti_chiave", "azioni"]


def in_markdown(r, sessione, meta=None):
    """Relazione impaginata: sezioni e ordine del template usato (le relazioni di prima: ordine classico)."""
    meta = meta or {}
    usato = meta.get("template") or {}
    sezioni = [k for k in usato.get("sezioni") or ORDINE_CLASSICO if k in SCRITTORI]
    out = [f"# {r.get('titolo') or sessione.get('titolo', 'Incontro')}", ""]
    quando = (sessione.get("creata") or "")[:16].replace("T", " ")
    out += [f"*{_riga(r.get('tipo', '').capitalize(), quando, 'durata ' + _durata(sessione.get('durata')))}*", ""]
    for k in sezioni:
        corpo = SCRITTORI[k](r)
        if corpo:
            out += [f"## {tpl.SEZIONI[k][0]}", ""] + corpo + [""]
    modelli = _riga(meta.get("modello_testo"), ("foto: " + meta["modello_vision"]) if meta.get("modello_vision") else "")
    dove = "modello cloud" if "☁️" in modelli else "AI locale"
    quale = f" · template «{usato['nome']}»" if usato.get("nome") else ""
    out += ["---", f"*Relazione generata con Argo · {dove} ({modelli}){quale}. Va riletta prima di usarla.*"]
    return "\n".join(out)
