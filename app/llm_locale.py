"""llm_locale.py - accesso a un modello linguistico locale tramite Ollama (http://localhost:11434).

Nessuna dipendenza esterna: solo libreria standard + numpy. Tutto il traffico resta su questo computer.
"""
import json
import re
import socket
import time
import urllib.error
import urllib.request

import numpy as np

import diagnostica
import uscite
import risorse

DEFAULT_URL = "http://localhost:11434"


class ErroreLLM(RuntimeError):
    pass


_DIMENSIONI_NOTE = {}  # nome modello -> byte, aggiornato da dimensioni(): serve solo a spiegare gli errori

TEMPO_BREVE = 30      # elenco e dettagli dei modelli: brevi, ma Ollama occupato a caricare un modello è lento


def _scaduto(e):
    """True se l'errore è un tempo scaduto (Ollama acceso ma non risponde), non un rifiuto (Ollama spento)."""
    motivo = getattr(e, "reason", e)
    return isinstance(motivo, (TimeoutError, socket.timeout)) or "timed out" in str(motivo).lower()


def _spiega_scaduto(url, timeout, payload):
    modello = (payload or {}).get("model") or ""
    dim = _DIMENSIONI_NOTE.get(modello)
    try:
        import risorse
        ram = risorse.ram_gb()
    except Exception:
        ram = 0
    testo = (f"Ollama è acceso su {url} ma non ha risposto entro {timeout} s: di solito sta ancora caricando un "
             "modello o il computer ha esaurito la memoria.")
    if modello and dim and ram and not risorse.modello_entra(dim):
        testo += (f" Il modello {modello} occupa {f'{dim / 1e9:.1f}'.replace('.', ',')} GB su {ram:.0f} GB di RAM: è troppo grande per "
                  "questo computer. Scegline uno più piccolo in Impostazioni › Modelli AI (per esempio gemma3:4b).")
    else:
        testo += " Aspetta un minuto e riprova; se succede sempre, scegli un modello più piccolo in Impostazioni › Modelli AI."
    return testo


def _req(url, path, payload=None, timeout=600, tentativi=1):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    for tentativo in range(1, tentativi + 1):
        inizio = time.monotonic()
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            diagnostica.http(req.get_method(), req.full_url, r.status, inizio)
            return r
        except urllib.error.HTTPError as e:
            diagnostica.http(req.get_method(), req.full_url, e.code, inizio)
            corpo = e.read().decode("utf-8", "replace")[:300]
            raise ErroreLLM(f"Ollama ha risposto {e.code}: {corpo}") from None
        except Exception as e:
            diagnostica.http(req.get_method(), req.full_url, type(e).__name__, inizio)
            if _scaduto(e):
                if tentativo < tentativi:
                    continue
                raise ErroreLLM(_spiega_scaduto(url, timeout, payload)) from None
            raise ErroreLLM(f"Ollama non risponde su {url} ({e}): è spento? Sul Mac avvialo dall'icona del lama "
                            "nella barra dei menu, su Windows dal menu Start.") from None


def _host(url):
    import urllib.parse
    return urllib.parse.urlparse(url).hostname or url


def e_locale(url):
    return bool(re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?/?$", url.strip()))


def elenco_modelli(url=DEFAULT_URL):
    """Ritorna (modelli_chat, modelli_embedding) installati in Ollama."""
    with _req(url, "/api/tags", timeout=TEMPO_BREVE, tentativi=2) as r:
        dati = json.load(r)
    _DIMENSIONI_NOTE.update({m.get("name", ""): int(m.get("size") or 0) for m in dati.get("models", [])})
    nomi = sorted(m.get("name", "") for m in dati.get("models", []))
    emb = [n for n in nomi if "embed" in n.lower() or n.lower().startswith(("bge", "e5", "gte"))]
    chat = [n for n in nomi if n not in emb]
    return chat, emb


def dimensioni(url=DEFAULT_URL):
    """{nome modello: byte occupati sul disco} dei modelli installati in Ollama ({} se non risponde)."""
    try:
        with _req(url, "/api/tags", timeout=TEMPO_BREVE) as r:
            trovate = {m.get("name", ""): int(m.get("size") or 0) for m in json.load(r).get("models", [])}
        _DIMENSIONI_NOTE.update(trovate)
        return trovate
    except Exception:
        return {}


def etichetta(nome, dimensioni_byte=None):
    """«gemma3:12b · 8,1 GB» per le tendine (il nome vero va nei dati della voce)."""
    if not dimensioni_byte:
        return nome
    gb = dimensioni_byte / 1e9
    testo = f"{gb:.1f}" if gb >= 0.1 else f"{gb:.2f}"
    avviso = "" if risorse.modello_entra(dimensioni_byte) else " · ⚠️ troppo grande per questo computer"
    return f"{nome} · {testo.replace('.', ',')} GB{avviso}"


def chat(messaggi, modello, url=DEFAULT_URL, temperatura=0.3, on_token=None, stop=None, contesto=None,
         on_attesa=None):
    """Chat in streaming. on_token(testo) riceve i pezzi; stop() -> True interrompe. Ritorna il testo completo.

    on_attesa(testo) viene chiamata se, nel profilo Leggero, bisogna aspettare che finisca un'altra elaborazione.
    """
    opzioni = {"temperature": temperatura}
    if contesto:
        opzioni["num_ctx"] = contesto
    payload = {"model": modello, "messages": messaggi, "stream": True,
               "options": risorse.opzioni_ollama(opzioni), "keep_alive": risorse.keep_alive()}
    with risorse.turno(on_attesa=on_attesa):
        if stop and stop():
            return ""
        if not e_locale(url):
            uscite.registra(f"Ollama su {_host(url)}", "testo per il modello linguistico")
        with diagnostica.misura("chat", fornitore="ollama" if e_locale(url) else "ollama_remoto", modello=modello):
            return _chat_stream(url, payload, on_token, stop)


def _chat_stream(url, payload, on_token, stop):
    out = []
    with _req(url, "/api/chat", payload) as r:
        for riga in r:
            if stop and stop():
                break
            riga = riga.strip()
            if not riga:
                continue
            pezzo = json.loads(riga)
            if pezzo.get("error"):
                raise ErroreLLM(pezzo["error"])
            t = pezzo.get("message", {}).get("content", "")
            if t:
                out.append(t)
                if on_token:
                    on_token(t)
            if pezzo.get("done"):
                break
    testo = "".join(out)
    # alcuni modelli "ragionano" tra <think>...</think>: non serve mostrarlo nel risultato finale
    return re.sub(r"<think>.*?</think>\s*", "", testo, flags=re.S).strip()


def embed(testi, modello, url=DEFAULT_URL):
    """Vettori normalizzati per una lista di testi."""
    if not e_locale(url):
        uscite.registra(f"Ollama su {_host(url)}", "testi dei documenti da indicizzare")
    with diagnostica.misura("embedding", modello=modello, testi=len(testi)):
        return _embed(testi, modello, url)


def _embed(testi, modello, url):
    vettori = []
    for i in range(0, len(testi), 16):
        richiesta = {"model": modello, "input": testi[i:i + 16], "options": risorse.opzioni_ollama(),
                     "keep_alive": risorse.keep_alive()}
        with risorse.turno(), _req(url, "/api/embed", richiesta) as r:
            dati = json.load(r)
        vettori.extend(dati.get("embeddings", []))
    if len(vettori) != len(testi):
        raise ErroreLLM("Il modello di embedding non ha restituito tutti i vettori.")
    m = np.asarray(vettori, dtype=np.float32)
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


def scarica_modello(nome, url=DEFAULT_URL, on_stato=None, stop=None):
    """Scarica un modello in Ollama (equivalente di `ollama pull`)."""
    with _req(url, "/api/pull", {"model": nome, "stream": True}, timeout=3600) as r:
        for riga in r:
            if stop and stop():
                return False
            riga = riga.strip()
            if not riga:
                continue
            d = json.loads(riga)
            if d.get("error"):
                raise ErroreLLM(d["error"])
            if on_stato:
                tot, fatto = d.get("total"), d.get("completed")
                perc = f" {fatto * 100 // tot}%" if tot and fatto else ""
                on_stato(f"{d.get('status', '')}{perc}")
            if d.get("status") == "success":
                return True
    return True


def spezza(testo, max_car=6000, sovrapposizione=0):
    """Divide un testo in blocchi di circa max_car caratteri, rispettando i paragrafi."""
    paragrafi = [p for p in re.split(r"\n\s*\n", testo) if p.strip()]
    blocchi, cur = [], ""
    for p in paragrafi:
        while len(p) > max_car:  # paragrafo enorme: taglio duro
            if cur:
                blocchi.append(cur)
                cur = ""
            blocchi.append(p[:max_car])
            p = p[max_car - sovrapposizione:]
        if len(cur) + len(p) + 2 > max_car and cur:
            blocchi.append(cur)
            cur = cur[-sovrapposizione:] if sovrapposizione else ""
        cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        blocchi.append(cur)
    return blocchi


def piu_simili(vettore_domanda, matrice, k=5):
    if len(matrice) == 0:
        return []
    punteggi = matrice @ vettore_domanda
    idx = np.argsort(-punteggi)[:k]
    return [(int(i), float(punteggi[i])) for i in idx]
