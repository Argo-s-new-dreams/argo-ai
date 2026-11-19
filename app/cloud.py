"""cloud.py - modelli linguistici nel cloud, facoltativi e scelti attrezzo per attrezzo.

Di base Argo usa solo Ollama su questo computer. In Impostazioni › Modelli cloud si possono collegare:
    claude        Anthropic Claude      (chiave API da console.anthropic.com)
    ollama_cloud  Ollama Cloud          (chiave da ollama.com/settings/keys; la stessa della Ricerca web)
e poi, per ogni attrezzo (Verbale, Traduzione, Incontri…), scegliere «Locale» oppure un modello cloud.
Quando un attrezzo usa il cloud, il testo che elabora esce dal computer: Argo lo scrive nello stato.

Restano SEMPRE in locale: audio, trascrizione (WhisperX), impronte vocali, indice dei documenti (embedding).
I criteri aziendali (criteri.json, chiave "modelli_cloud") possono vietare il cloud o limitare i fornitori.
Solo libreria standard.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import diagnostica
import uscite
import voci_core as core

FORNITORI = {
    "claude": {"nome": "Claude (Anthropic)", "breve": "Claude",
               "aiuto": "Chiave API da console.anthropic.com › API Keys"},
    "ollama_cloud": {"nome": "Ollama Cloud", "breve": "Ollama Cloud",
                     "aiuto": "Chiave da ollama.com/settings/keys (vuota = quella della Ricerca web)"},
}
# Schede «Maggiori info» (verificate sulle pagine ufficiali il 19/11/2026: le condizioni dei fornitori
# cambiano, per questo ogni scheda porta la data e i link alle fonti).
VERIFICATO_IL = "19/11/2026"
INFO = {
    "claude": {
        "sito": ("console Claude (platform.claude.com)", "https://platform.claude.com"),
        "passi": [
            "Crea un account sulla console Claude (platform.claude.com) e scegli o crea l'organizzazione.",
            "In Billing aggiungi un metodo di pagamento o del credito: l'API si paga a consumo.",
            "Apri API Keys › Create Key, dai un nome (es. «Argo») e copia la chiave: si vede una volta sola.",
            "In Argo incollala qui e premi «Collega e verifica», poi scegli Claude per gli attrezzi che vuoi.",
        ],
        "dove": "<b>Nessuna garanzia di restare in Europa.</b> Con l'API diretta di Anthropic, che è quella usata da Argo, l'elaborazione "
                "può avvenire in qualunque area geografica disponibile (impostazione «global», predefinita) oppure "
                "solo negli Stati Uniti; i dati salvati stanno negli Stati Uniti. Un'elaborazione solo in Europa "
                "oggi è possibile tramite AWS Bedrock o Google Vertex AI, che Argo non usa.",
        "conservazione": "Input e output dell'API vengono cancellati automaticamente entro 30 giorni, salvo accordi "
                         "di conservazione zero (per le organizzazioni che li ottengono), violazioni delle regole d'uso "
                         "(fino a 2 anni) o obblighi di legge.",
        "addestramento": "Per i prodotti commerciali, API compresa, Anthropic per impostazione predefinita non usa i "
                         "dati dei clienti per addestrare i modelli.",
        "fonti": [("Conservazione dei dati dell'API", "https://privacy.claude.com/en/articles/7996866"),
                  ("Residenza dei dati", "https://platform.claude.com/docs/en/manage-claude/data-residency")],
    },
    "ollama_cloud": {
        "sito": ("ollama.com", "https://ollama.com"),
        "passi": [
            "Crea un account su ollama.com (lo stesso che usi per la Ricerca web della pagina Clienti, se c'è già).",
            "Apri ollama.com/settings/keys e crea una chiave API; copiala.",
            "In Argo incollala qui (o lascia vuoto per usare la chiave della Ricerca web) e premi «Collega e verifica».",
            "I modelli cloud disponibili sono elencati su ollama.com/search?c=cloud; piani e prezzi sono su ollama.com.",
        ],
        "dove": "<b>Principalmente negli Stati Uniti.</b> Ollama dichiara di ospitare modelli e calcolo soprattutto "
                "negli USA e di poter instradare le richieste anche in Europa e a Singapore per avere capacità in "
                "più: non si può scegliere l'area. I modelli girano presso fornitori cloud partner di NVIDIA.",
        "conservazione": "Ollama dichiara che elabora prompt e risposte solo per dare il servizio, senza salvarli "
                         "né registrarli nei log, e che ai partner richiede nessun log, nessun addestramento e "
                         "conservazione zero.",
        "addestramento": "Ollama dichiara che prompt e risposte non vengono mai usati per l'addestramento.",
        "fonti": [("Domande frequenti di Ollama (privacy)", "https://docs.ollama.com/faq"),
                  ("Ollama Cloud · piani e privacy", "https://registry.ollama.ai/cloud"),
                  ("Documentazione Ollama Cloud", "https://docs.ollama.com/cloud")],
    },
}


def scheda_info(fornitore):
    """Testo (HTML semplice) della scheda «Maggiori info» di un fornitore."""
    i = INFO[fornitore]
    nome, url = i["sito"]
    righe = [f"<h3>{FORNITORI[fornitore]['nome']}</h3>",
             f"<p><b>Sito:</b> <a href='{url}'>{nome}</a></p>",
             "<p><b>Come collegarlo ad Argo</b></p><ol>" + "".join(f"<li>{x}</li>" for x in i["passi"]) + "</ol>",
             f"<p><b>🌍 Dove vengono elaborati i dati</b><br>{i['dove']}</p>",
             f"<p><b>🗄 Quanto vengono conservati</b><br>{i['conservazione']}</p>",
             f"<p><b>🧠 Addestramento</b><br>{i['addestramento']}</p>",
             "<p><b>Cosa esce da Argo:</b> solo il testo dell'attrezzo per cui scegli questo fornitore (lo vedi "
             "riga per riga in «Quale modello per ogni attrezzo»). Audio, trascrizione, voci e indice dei documenti "
             "restano sul computer.</p>",
             "<p><b>Fonti</b> (verificate il " + VERIFICATO_IL + "; le condizioni possono cambiare): "
             + " · ".join(f"<a href='{u}'>{t}</a>" for t, u in i["fonti"]) + "</p>"]
    return "".join(righe)


ATTREZZI = [  # chiave, nome mostrato, cosa esce dal computer se si sceglie il cloud
    ("verbale", "Verbale", "la trascrizione della riunione"),
    ("documenti", "Documenti riservati", "la domanda e gli estratti dei documenti trovati"),
    ("dettatura", "Dettatura", "il testo dettato"),
    ("traduzione", "Traduzione", "il testo da tradurre"),
    ("agenda", "Agenda", "i dati dell'evento"),
    ("posta", "Posta", "il testo della mail"),
    ("incarichi", "Incarichi", "la trascrizione o la mail da cui estrarre i compiti"),
    ("incontri", "Incontri · relazione", "la trascrizione dell'incontro"),
    ("incontri_foto", "Incontri · foto", "le foto (biglietti da visita, documenti)"),
    ("clienti", "Clienti", "le pagine web trovate e, per «Dalla call», la trascrizione"),
]
NOMI_ATTREZZI = {k: n for k, n, _ in ATTREZZI}
ESCE = {k: e for k, _, e in ATTREZZI}
LOCALE = "locale"
FILE_CHIAVI = core.APP_HOME / ".chiavi_cloud.json"
URL = {
    "claude": "https://api.anthropic.com",
    "ollama_cloud": "https://ollama.com",
}


class ErroreCloud(RuntimeError):
    pass


# ---------------------------------------------------------------- l'attrezzo che sta lavorando (per thread)
_corrente = threading.local()


def imposta_attrezzo(attrezzo):
    _corrente.attrezzo = attrezzo


def attrezzo():
    return getattr(_corrente, "attrezzo", None)


# ---------------------------------------------------------------- criteri aziendali
def ammessi():
    """Fornitori che l'organizzazione consente (criteri.json, "modelli_cloud")."""
    try:
        import criteri
        regola = criteri.carica().get("modelli_cloud", "consentiti")
    except Exception:
        regola = "consentiti"
    if regola == "vietati":
        return []
    if isinstance(regola, list):
        return [f for f in FORNITORI if f in regola]
    return list(FORNITORI)


def vietati_da_criteri():
    return not ammessi()


# ---------------------------------------------------------------- chiavi (file leggibile solo dall'utente)
def _leggi_chiavi():
    try:
        return json.loads(FILE_CHIAVI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def chiave(fornitore):
    valore = (_leggi_chiavi().get(fornitore) or "").strip()
    if not valore and fornitore == "ollama_cloud":  # stessa chiave della Ricerca web
        try:
            import ricerca_web
            valore = ricerca_web.chiave() or ""
        except Exception:
            valore = ""
    return valore


def salva_chiave(fornitore, valore):
    dati = _leggi_chiavi()
    if valore.strip():
        dati[fornitore] = valore.strip()
    else:
        dati.pop(fornitore, None)
    core.APP_HOME.mkdir(parents=True, exist_ok=True)
    FILE_CHIAVI.write_text(json.dumps(dati, indent=2), encoding="utf-8")
    try:
        os.chmod(FILE_CHIAVI, 0o600)
    except Exception:
        pass


def collegato(fornitore):
    return fornitore in ammessi() and bool(chiave(fornitore))


# ---------------------------------------------------------------- quale motore per un attrezzo
def motore(nome_attrezzo=None):
    """(fornitore, modello) per l'attrezzo; ("locale", None) se locale, non configurato o vietato."""
    nome_attrezzo = nome_attrezzo or attrezzo()
    if not nome_attrezzo:
        return LOCALE, None
    scelta = (core.carica_impostazioni().get("motori") or {}).get(nome_attrezzo) or LOCALE
    if scelta == LOCALE or ":" not in scelta:
        return LOCALE, None
    fornitore, modello = scelta.split(":", 1)
    if fornitore not in FORNITORI or not collegato(fornitore) or not modello:
        return LOCALE, None
    return fornitore, modello


def e_cloud(nome_attrezzo=None):
    return motore(nome_attrezzo)[0] != LOCALE


def etichetta(fornitore, modello):
    return f"☁️ {FORNITORI[fornitore]['breve']} · {modello}" if fornitore != LOCALE else "🖥 Locale"


def avviso(nome_attrezzo=None):
    """Frase per lo stato quando l'attrezzo usa il cloud ('' se è locale)."""
    nome_attrezzo = nome_attrezzo or attrezzo()
    f, m = motore(nome_attrezzo)
    if f == LOCALE:
        return ""
    return f"☁️ {FORNITORI[f]['breve']} · {m}: dati inviati nel cloud ({ESCE.get(nome_attrezzo, 'il testo')})."


# ---------------------------------------------------------------- HTTP
def _intestazioni(fornitore):
    k = chiave(fornitore)
    if not k:
        raise ErroreCloud(f"Manca la chiave di {FORNITORI[fornitore]['nome']}: Impostazioni › Modelli cloud.")
    if fornitore == "claude":
        return {"x-api-key": k, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    h = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
    return h


def _apri(fornitore, percorso, payload=None, timeout=600):
    dati = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(URL[fornitore] + percorso, data=dati, headers=_intestazioni(fornitore),
                                 method="POST" if dati is not None else "GET")
    inizio = time.monotonic()
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        diagnostica.http(req.get_method(), req.full_url, r.status, inizio)
        return r
    except urllib.error.HTTPError as e:
        diagnostica.http(req.get_method(), req.full_url, e.code, inizio)
        corpo = e.read().decode("utf-8", "replace")[:300]
        motivo = {401: "chiave non valida", 403: "accesso negato (permessi o criteri dell'account)",
                  404: "modello o indirizzo non trovato", 429: "troppe richieste o credito esaurito"}.get(e.code, "")
        raise ErroreCloud(f"{FORNITORI[fornitore]['nome']} ha risposto {e.code}"
                          + (f" ({motivo})" if motivo else "") + f": {corpo}") from None
    except Exception as e:
        diagnostica.http(req.get_method(), req.full_url, type(e).__name__, inizio)
        raise ErroreCloud(f"{FORNITORI[fornitore]['nome']} non raggiungibile: {e}") from None


def _apri_chat(fornitore, percorso, payload):
    """Come _apri, ma se il modello rifiuta «temperature» (alcuni modelli di ragionamento) riprova senza."""
    try:
        return _apri(fornitore, percorso, payload, timeout=1800)
    except ErroreCloud as e:
        if "temperature" not in str(e).lower() or "temperature" not in payload:
            raise
        payload = {k: v for k, v in payload.items() if k != "temperature"}
        return _apri(fornitore, percorso, payload, timeout=1800)


def elenco_modelli(fornitore):
    """Modelli di testo disponibili con la chiave salvata (verifica anche che la chiave funzioni)."""
    if fornitore not in ammessi():
        raise ErroreCloud(f"{FORNITORI[fornitore]['nome']} non è consentito dai criteri aziendali.")
    if fornitore == "claude":
        with _apri(fornitore, "/v1/models?limit=100", timeout=20) as r:
            return [m["id"] for m in json.load(r).get("data", []) if m.get("id")]
    with _apri(fornitore, "/api/tags", timeout=20) as r:
        return sorted(m.get("name", "") for m in json.load(r).get("models", []) if m.get("name"))


# ---------------------------------------------------------------- messaggi nei vari formati
def _tipo_immagine(b64):
    inizio = b64[:16]
    if inizio.startswith("iVBOR"):
        return "image/png"
    if inizio.startswith("R0lG"):
        return "image/gif"
    if inizio.startswith("UklG"):
        return "image/webp"
    return "image/jpeg"


def _per_openai(messaggi):
    out = []
    for m in messaggi:
        if m.get("images"):
            parti = [{"type": "text", "text": m.get("content", "")}]
            parti += [{"type": "image_url", "image_url": {"url": f"data:{_tipo_immagine(i)};base64,{i}"}}
                      for i in m["images"]]
            out.append({"role": m["role"], "content": parti})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def _per_claude(messaggi):
    sistema = "\n\n".join(m.get("content", "") for m in messaggi if m["role"] == "system")
    out = []
    for m in messaggi:
        if m["role"] == "system":
            continue
        if m.get("images"):
            parti = [{"type": "image", "source": {"type": "base64", "media_type": _tipo_immagine(i), "data": i}}
                     for i in m["images"]]
            parti.append({"type": "text", "text": m.get("content", "")})
            out.append({"role": m["role"], "content": parti})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return sistema, out


def _con_formato(messaggi, formato):
    """Claude non accetta lo schema JSON di Ollama: lo si chiede nelle istruzioni."""
    if not formato:
        return messaggi
    schema = "" if formato == "json" else "\nSchema JSON da rispettare:\n" + json.dumps(formato, ensure_ascii=False)
    nota = ("\n\nRispondi SOLO con un oggetto JSON valido, senza testo prima o dopo e senza blocchi ```." + schema)
    messaggi = [dict(m) for m in messaggi]
    for m in messaggi:
        if m["role"] == "system":
            m["content"] = m.get("content", "") + nota
            return messaggi
    return [{"role": "system", "content": nota.strip()}] + messaggi


def solo_json(testo):
    """Toglie eventuali ``` e testo attorno all'oggetto JSON."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", testo.strip())
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i >= 0 and j > i else t


def _righe_sse(risposta):
    for riga in risposta:
        riga = riga.decode("utf-8", "replace").strip()
        if riga.startswith("data:"):
            dato = riga[5:].strip()
            if dato and dato != "[DONE]":
                yield json.loads(dato)


# ---------------------------------------------------------------- chat
def chat(fornitore, modello, messaggi, temperatura=0.3, on_token=None, stop=None, formato=None):
    """Chat in streaming con un fornitore cloud. Ritorna il testo completo (solo JSON se `formato`)."""
    if fornitore not in ammessi():
        raise ErroreCloud(f"{FORNITORI[fornitore]['nome']} non è consentito dai criteri aziendali.")
    uscite.registra(f"{FORNITORI[fornitore]['nome']} (modello cloud)",
                    f"testo per l'attrezzo «{attrezzo() or 'Argo'}»")
    with diagnostica.misura("chat", fornitore=fornitore, modello=modello):
        return _chat(fornitore, modello, messaggi, temperatura, on_token, stop, formato)


def _chat(fornitore, modello, messaggi, temperatura, on_token, stop, formato):
    out = []

    def pezzo(t):
        if t:
            out.append(t)
            if on_token:
                on_token(t)

    if fornitore == "ollama_cloud":
        payload = {"model": modello, "messages": messaggi, "stream": True, "options": {"temperature": temperatura}}
        if formato:
            payload["format"] = formato
        with _apri(fornitore, "/api/chat", payload, timeout=1800) as r:
            for riga in r:
                if stop and stop():
                    break
                if not riga.strip():
                    continue
                d = json.loads(riga)
                if d.get("error"):
                    raise ErroreCloud(d["error"])
                pezzo(d.get("message", {}).get("content", ""))
                if d.get("done"):
                    break
    else:  # claude
        sistema, msg = _per_claude(_con_formato(messaggi, formato))
        payload = {"model": modello, "max_tokens": 8192, "messages": msg, "stream": True,
                   "temperature": min(1.0, temperatura)}
        if sistema:
            payload["system"] = sistema
        with _apri_chat(fornitore, "/v1/messages", payload) as r:
            for d in _righe_sse(r):
                if stop and stop():
                    break
                if d.get("type") == "error":
                    raise ErroreCloud((d.get("error") or {}).get("message", "errore di Claude"))
                if d.get("type") == "content_block_delta":
                    pezzo((d.get("delta") or {}).get("text", ""))
    testo = re.sub(r"<think>.*?</think>\s*", "", "".join(out), flags=re.S).strip()
    return solo_json(testo) if formato else testo
