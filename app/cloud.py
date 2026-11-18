"""cloud.py - modelli linguistici nel cloud, facoltativi e scelti attrezzo per attrezzo.

Di base Argo usa solo Ollama su questo computer. In Impostazioni › Modelli cloud si possono collegare:
    claude        Anthropic Claude      (chiave API da console.anthropic.com)
    github        GitHub Models         (token personale GitHub con permesso «models: read»)
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
import urllib.error
import urllib.request

import voci_core as core

FORNITORI = {
    "claude": {"nome": "Claude (Anthropic)", "breve": "Claude",
               "aiuto": "Chiave API da console.anthropic.com › API Keys"},
    "github": {"nome": "GitHub Models", "breve": "GitHub",
               "aiuto": "Token personale (fine-grained) con permesso «Models: read» da github.com/settings/tokens"},
    "ollama_cloud": {"nome": "Ollama Cloud", "breve": "Ollama Cloud",
                     "aiuto": "Chiave da ollama.com/settings/keys (vuota = quella della Ricerca web)"},
}
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
    "github": "https://models.github.ai",
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
    if fornitore == "github":
        h.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
    return h


def _apri(fornitore, percorso, payload=None, timeout=600):
    dati = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(URL[fornitore] + percorso, data=dati, headers=_intestazioni(fornitore),
                                 method="POST" if dati is not None else "GET")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        motivo = {401: "chiave non valida", 403: "accesso negato (permessi o criteri dell'account)",
                  404: "modello o indirizzo non trovato", 429: "troppe richieste o credito esaurito"}.get(e.code, "")
        raise ErroreCloud(f"{FORNITORI[fornitore]['nome']} ha risposto {e.code}"
                          + (f" ({motivo})" if motivo else "") + f": {corpo}") from None
    except Exception as e:
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
    if fornitore == "github":
        with _apri(fornitore, "/catalog/models", timeout=20) as r:
            dati = json.load(r)
        voci = dati if isinstance(dati, list) else dati.get("models", [])
        return sorted(m["id"] for m in voci if m.get("id") and "text" in (m.get("supported_output_modalities") or ["text"])
                      and "embed" not in m["id"].lower())
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
    """Claude e GitHub non accettano lo schema JSON di Ollama: lo si chiede nelle istruzioni."""
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
    elif fornitore == "github":
        payload = {"model": modello, "messages": _per_openai(_con_formato(messaggi, formato)), "stream": True,
                   "temperature": temperatura}
        if formato:
            payload["response_format"] = {"type": "json_object"}
        with _apri_chat(fornitore, "/inference/chat/completions", payload) as r:
            for d in _righe_sse(r):
                if stop and stop():
                    break
                for scelta in d.get("choices") or []:
                    pezzo((scelta.get("delta") or {}).get("content") or "")
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
