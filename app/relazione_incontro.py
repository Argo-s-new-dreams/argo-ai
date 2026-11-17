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

import llm_locale as llm

FILE_DATI = "argo-relazione.json"
FILE_TESTO = "relazione-argo.md"
CARATTERI_PER_BLOCCO = 12_000

# Nomi tipici dei modelli vision in Ollama, se il server non dichiara le «capabilities»
INDIZI_VISION = ("vl", "vision", "llava", "gemma3", "minicpm-v", "moondream", "mistral-small3", "llama4", "granite3.2-vision")


class ErroreRelazione(RuntimeError):
    pass


# ---------------------------------------------------------------- Ollama
def _chiama(url, modello, messaggi, formato=None, contesto=16384, stop=None):
    payload = {"model": modello, "messages": messaggi, "stream": False,
               "options": {"temperature": 0.2, "num_ctx": contesto}}
    if formato:
        payload["format"] = formato
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
            with llm._req(url, "/api/show", {"model": nome}, timeout=10) as r:
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


def descrivi_foto(cartella, sessione, url, modello, stato=lambda _t: None, stop=None):
    """Descrive le foto non ancora descritte con quel modello. Ritorna {file: descrizione}."""
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
                        contesto=8192, stop=stop)
        cache[nome] = {"modello": modello, "descrizione": testo}
        _salva(cartella, dati)
    return {k: v["descrizione"] for k, v in cache.items()}


# ---------------------------------------------------------------- 2-3 · relazione strutturata
ISTRUZIONI = """Sei l'assistente commerciale che scrive la relazione di un incontro di lavoro (fiera o visita a un cliente).
Il testo ha righe «[minuto] Nome: frase». Le righe «📷 FOTO» sono foto scattate in quel momento, con il testo letto
e una descrizione: usale per identificare persone, aziende, recapiti e prodotti, e collegale a ciò che si dice.
Chi registra è la persona indicata come «Io» (o con il nome dell'utente): non è un contatto.
Regole: usa solo informazioni presenti; nessun nome, recapito, cifra o data inventati; campi sconosciuti vuoti.
Scrivi in italiano, in modo concreto e professionale."""

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
    },
    "required": ["titolo", "tipo", "riassunto", "contatti", "aziende", "interessi", "opportunita",
                 "punti_chiave", "azioni"],
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


def scrivi_relazione(cartella, sessione, url, modello_testo, modello_vision=None, stato=lambda _t: None, stop=None):
    """Genera la relazione e la salva nell'incontro. Ritorna (dati_relazione, markdown)."""
    if not llm.e_locale(url):
        raise ErroreRelazione("L'indirizzo di Ollama non è locale: per gli incontri si usa solo un modello su questo computer.")
    if not modello_testo:
        raise ErroreRelazione("Scegli un modello per i testi in Impostazioni › Modelli.")
    cartella = Path(cartella)
    descrizioni = {}
    if modello_vision and sessione.get("foto"):
        descrizioni = descrivi_foto(cartella, sessione, url, modello_vision, stato, stop)
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
                {"role": "system", "content": ISTRUZIONI},
                {"role": "user", "content": "Scrivi appunti fedeli e sintetici di questa parte (chi è chi, aziende, "
                                            "prodotti, richieste, cifre, decisioni, azioni). Conserva nomi e recapiti "
                                            "delle righe FOTO.\n\n" + b}], stop=stop))
        testo = "\n\n".join(appunti)
        giro += 1

    stato(f"Scrivo la relazione con {modello_testo}…")
    intestazione = (f"Titolo provvisorio: {sessione.get('titolo', '')}\n"
                    f"Data: {(sessione.get('creata') or '')[:16].replace('T', ' ')} · durata {_durata(sessione.get('durata'))}\n"
                    f"Partecipanti: {', '.join(p.get('nome', p['id']) for p in sessione.get('partecipanti', [])) or 'non indicati'}\n\n")
    risposta = _chiama(url, modello_testo, [
        {"role": "system", "content": ISTRUZIONI},
        {"role": "user", "content": intestazione + testo}], formato=SCHEMA, stop=stop)
    try:
        relazione = json.loads(risposta)
    except json.JSONDecodeError:
        raise ErroreRelazione(f"Il modello {modello_testo} non ha restituito una relazione strutturata: prova un altro modello.") from None

    dati = carica(cartella)
    dati.update({
        "relazione": relazione,
        "modello_testo": modello_testo,
        "modello_vision": modello_vision or None,
        "generata": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    _salva(cartella, dati)
    md = in_markdown(relazione, sessione, dati)
    (cartella / FILE_TESTO).write_text(md, encoding="utf-8")
    return relazione, md


def _riga(*parti):
    return " · ".join(p for p in parti if p)


def in_markdown(r, sessione, meta=None):
    meta = meta or {}
    out = [f"# {r.get('titolo') or sessione.get('titolo', 'Incontro')}", ""]
    quando = (sessione.get("creata") or "")[:16].replace("T", " ")
    out += [f"_{_riga(r.get('tipo', '').capitalize(), quando, 'durata ' + _durata(sessione.get('durata')))}_", ""]
    if r.get("riassunto"):
        out += ["## Riassunto", "", r["riassunto"], ""]
    if r.get("contatti"):
        out += ["## Contatti", ""]
        for c in r["contatti"]:
            nome = _riga(" ".join(x for x in (c.get("nome"), c.get("cognome")) if x))
            out.append(f"- **{nome}** — " + _riga(c.get("ruolo"), c.get("azienda"), c.get("email"),
                                                   c.get("telefono"), c.get("cellulare"), c.get("sito")))
            if c.get("note"):
                out.append(f"  {c['note']}")
        out.append("")
    if r.get("aziende"):
        out += ["## Aziende", ""] + [f"- **{a.get('nome')}** — " + _riga(a.get("settore"), a.get("citta"), a.get("sito"), a.get("note"))
                                     for a in r["aziende"]] + [""]
    o = r.get("opportunita") or {}
    if any(o.get(k) for k in ("descrizione", "prodotti", "budget", "tempistica", "prossimo_passo")):
        out += ["## Opportunità", ""]
        for etichetta, chiave in (("Descrizione", "descrizione"), ("Budget", "budget"), ("Tempistica", "tempistica"),
                                  ("Decisori", "decisori"), ("Concorrenti", "concorrenti"), ("Prossimo passo", "prossimo_passo")):
            if o.get(chiave):
                out.append(f"- **{etichetta}:** {o[chiave]}")
        if o.get("prodotti"):
            out.append("- **Prodotti/servizi:** " + ", ".join(o["prodotti"]))
        out.append("")
    if r.get("interessi"):
        out += ["## Interessi", ""] + [f"- {i}" for i in r["interessi"]] + [""]
    if r.get("punti_chiave"):
        out += ["## Punti chiave", ""] + [f"- {p}" for p in r["punti_chiave"]] + [""]
    if r.get("azioni"):
        out += ["## Azioni", ""] + [f"- [ ] {_riga(a.get('descrizione'), a.get('responsabile'), ('entro ' + a['scadenza']) if a.get('scadenza') else '')}"
                                    for a in r["azioni"]] + [""]
    modelli = _riga(meta.get("modello_testo"), ("foto: " + meta["modello_vision"]) if meta.get("modello_vision") else "")
    out += ["---", f"_Relazione generata con Argo · AI locale ({modelli}). Va riletta prima di usarla._"]
    return "\n".join(out)
