"""ricerca_web.py - ricerca web per la scheda pubblica dei clienti, con Ollama Web Search.

Unico punto di Argo che esce su Internet per cercare: parte solo la query (es. il nome di un'azienda),
mai trascrizioni, partecipanti o documenti. Serve una chiave API di un account Ollama (gratuito):
https://ollama.com/settings/keys — salvata in whisperx-env/.ollama_web_key (permessi 600).

API (docs.ollama.com/web-search): POST https://ollama.com/api/web_search {query, max_results}
                                  POST https://ollama.com/api/web_fetch  {url}
"""
import json
import os
import ssl
import urllib.error
import urllib.request

import voci_core as core

BASE = "https://ollama.com/api"
FILE_CHIAVE = core.APP_HOME / ".ollama_web_key"


class ErroreRicerca(Exception):
    pass


def chiave():
    try:
        return FILE_CHIAVE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return os.environ.get("OLLAMA_API_KEY", "").strip()


def salva_chiave(valore):
    core.APP_HOME.mkdir(parents=True, exist_ok=True)
    FILE_CHIAVE.write_text(valore.strip(), encoding="utf-8")
    try:
        os.chmod(FILE_CHIAVE, 0o600)
    except OSError:
        pass


def vietata():
    """True se l'IT ha disattivato la ricerca web con i criteri aziendali («ricerca_web»: false)."""
    try:
        import criteri
        return criteri.carica().get("ricerca_web") is False
    except Exception:
        return False


def configurata():
    return bool(chiave()) and not vietata()


def _contesti():
    yield ssl.create_default_context()
    try:
        import certifi
        yield ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass


def _post(percorso, corpo, timeout=40):
    if vietata():
        raise ErroreRicerca("La ricerca web è disattivata dall'IT con i criteri aziendali.")
    if not chiave():
        raise ErroreRicerca("Manca la chiave di Ollama Web Search: Impostazioni › Ricerca web (account Ollama gratuito).")
    import uscite
    uscite.registra("Ollama Web Search" if percorso == "web_search" else "Ollama Web Fetch",
                    "testo di una ricerca web (nome dell'azienda)" if percorso == "web_search"
                    else "indirizzo di una pagina web da leggere")
    req = urllib.request.Request(f"{BASE}/{percorso}", data=json.dumps(corpo).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {chiave()}", "Content-Type": "application/json"})
    ultimo = None
    for ctx in _contesti():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            dettaglio = ""
            try:
                testo = e.read().decode("utf-8", "replace").strip()
                try:
                    dati = json.loads(testo)
                    testo = dati.get("error") or dati.get("message") or testo
                except Exception:
                    pass
                dettaglio = f" — {str(testo)[:200]}" if testo else ""
            except Exception:
                pass
            if e.code == 401:
                raise ErroreRicerca(f"Chiave di Ollama Web Search non valida (401){dettaglio}.") from None
            if e.code == 402:
                raise ErroreRicerca("Ollama chiede un piano o un credito per la ricerca web (402)"
                                    f"{dettaglio}. Controlla l'account su ollama.com › Settings.") from None
            if e.code == 429:
                raise ErroreRicerca(f"Limite di ricerche di Ollama raggiunto (429){dettaglio}: riprova più tardi.") from None
            raise ErroreRicerca(f"Ollama Web Search ha risposto {e.code}{dettaglio}.") from None
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(getattr(e, "reason", "")):
                ultimo = e
                continue
            raise ErroreRicerca(f"Ollama Web Search non raggiungibile: {e.reason}") from None
    raise ErroreRicerca(f"Certificato non verificato: {ultimo}")


def cerca(query, massimo=5):
    """[{title, url, content}]"""
    return _post("web_search", {"query": query, "max_results": max(1, min(10, massimo))}).get("results", [])


def scarica(url):
    """{title, content, links}: testo della pagina."""
    return _post("web_fetch", {"url": url}, timeout=60)
