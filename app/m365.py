"""m365.py - connettore FACOLTATIVO a Microsoft 365 per gli Incarichi.

Cosa fa (solo se l'utente collega il proprio account):
- legge dal calendario la riunione registrata, per avere titolo e partecipanti;
- crea una BOZZA in Outlook (non la invia mai);
- crea i task in un piano di Microsoft Planner.

Cosa NON fa: l'audio, la trascrizione e i documenti non vengono mai inviati; su Microsoft 365 vanno solo
i risultati che l'utente conferma. Accesso delegato con MSAL (codice dispositivo), token conservato in
whisperx-env/m365_token.bin con permessi 600.
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import voci_core as core

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Calendars.Read", "Mail.ReadWrite", "Tasks.ReadWrite", "User.ReadBasic.All", "Group.Read.All"]
CACHE = core.APP_HOME / "m365_token.bin"
RE_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


class ErroreM365(Exception):
    pass


def configurato():
    s = core.carica_impostazioni()
    return bool(s.get("m365_client_id") and s.get("m365_tenant_id"))


def _app():
    try:
        import msal
    except ImportError:
        raise ErroreM365("Manca la libreria «msal»: rilancia l'installer di Argo (o aggiorna) per installarla.") from None
    s = core.carica_impostazioni()
    if not configurato():
        raise ErroreM365("Inserisci Client ID e Tenant ID in Impostazioni → Microsoft 365.")
    cache = msal.SerializableTokenCache()
    if CACHE.exists():
        cache.deserialize(CACHE.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(s["m365_client_id"],
                                       authority=f"https://login.microsoftonline.com/{s['m365_tenant_id']}",
                                       token_cache=cache)
    return app, cache


def _salva_cache(cache):
    if cache.has_state_changed:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(cache.serialize(), encoding="utf-8")
        try:
            os.chmod(CACHE, 0o600)
        except OSError:
            pass


def account():
    """Nome dell'account collegato, oppure None."""
    if not configurato() or not CACHE.exists():
        return None
    try:
        app, _ = _app()
        acc = app.get_accounts()
        return acc[0].get("username") if acc else None
    except ErroreM365:
        return None


def accedi_interattivo():
    """Accesso consigliato: apre il browser di sistema sulla pagina Microsoft (codice di autorizzazione + PKCE,
    risposta su http://localhost). Bloccante fino alla fine dell'accesso: va eseguito in un thread.
    Richiede nella registrazione dell'app il redirect URI «http://localhost» (Mobile and desktop applications)."""
    app, cache = _app()
    r = app.acquire_token_interactive(
        SCOPES, prompt="select_account", timeout=300,
        success_template="<html><body style='font-family:sans-serif'><h2>Argo è collegato a Microsoft 365.</h2>"
                         "<p>Puoi chiudere questa scheda e tornare ad Argo.</p></body></html>",
        error_template="<html><body style='font-family:sans-serif'><h2>Accesso non riuscito</h2>"
                       "<p>$error: $error_description</p></body></html>")
    _salva_cache(cache)
    if "access_token" not in r:
        raise ErroreM365(_spiega(r))
    return r.get("id_token_claims", {}).get("preferred_username") or account()


def _spiega(r):
    desc = r.get("error_description") or r.get("error") or "accesso non riuscito"
    if "AADSTS53003" in desc:
        return ("Accesso bloccato da un criterio di accesso condizionale del tuo tenant (AADSTS53003). "
                "Controlla in Entra → Log di accesso → scheda «Accesso condizionale» quale criterio blocca "
                "l'app «Argo AI».")
    if "AADSTS50011" in desc:
        return ("Nella registrazione dell'app manca il redirect URI «http://localhost»: aggiungilo in "
                "Authentication → Mobile and desktop applications.")
    if "AADSTS65001" in desc:
        return "Manca il consenso ai permessi: un amministratore deve premere «Grant admin consent» nell'app."
    return desc


def avvia_accesso():
    """Primo passo del codice dispositivo: ritorna il flow con user_code e verification_uri."""
    app, cache = _app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise ErroreM365(flow.get("error_description") or "accesso non avviato")
    return flow


def completa_accesso(flow):
    """Attende che l'utente inserisca il codice nel browser (bloccante: va eseguito in un thread)."""
    app, cache = _app()
    r = app.acquire_token_by_device_flow(flow)
    _salva_cache(cache)
    if "access_token" not in r:
        raise ErroreM365(_spiega(r))
    return r.get("id_token_claims", {}).get("preferred_username") or account()


def scollega():
    try:
        CACHE.unlink()
    except FileNotFoundError:
        pass


def _token():
    app, cache = _app()
    acc = app.get_accounts()
    if not acc:
        raise ErroreM365("Account Microsoft 365 non collegato.")
    r = app.acquire_token_silent(SCOPES, account=acc[0])
    _salva_cache(cache)
    if not r or "access_token" not in r:
        raise ErroreM365("Accesso scaduto: ricollega Microsoft 365 nelle Impostazioni.")
    return r["access_token"]


def _contesti():
    yield ssl.create_default_context()
    try:
        import certifi
        yield ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass


def graph(metodo, percorso, corpo=None, token=None):
    url = percorso if percorso.startswith("http") else GRAPH + percorso
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo, headers={
        "Authorization": f"Bearer {token or _token()}", "Content-Type": "application/json",
        "Prefer": 'outlook.timezone="Europe/Rome"'})
    ultimo = None
    for ctx in _contesti():
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                testo = r.read().decode("utf-8")
                return json.loads(testo) if testo else {}
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            raise ErroreM365(f"Microsoft 365 ha risposto {e.code}: {msg or e.reason}") from None
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                ultimo = e
                continue
            raise ErroreM365(f"Microsoft 365 non raggiungibile: {e.reason}") from None
    raise ErroreM365(f"certificato non verificato: {ultimo}")


# ---------------------------------------------------------------- calendario
def riunione_vicina(quando, ore=4):
    """La riunione del calendario più vicina all'istante della registrazione (datetime locale)."""
    t = quando.astimezone(timezone.utc)
    q = urllib.parse.urlencode({
        "startDateTime": (t - timedelta(hours=ore)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": (t + timedelta(hours=ore)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "$select": "subject,start,end,attendees,organizer", "$orderby": "start/dateTime", "$top": "50"})
    eventi = graph("GET", f"/me/calendarView?{q}").get("value", [])
    if not eventi:
        return None

    def distanza(ev):
        try:
            ini = datetime.fromisoformat(ev["start"]["dateTime"][:19])
            fin = datetime.fromisoformat(ev["end"]["dateTime"][:19])
        except Exception:
            return 1e12
        loc = quando.replace(tzinfo=None)
        if ini <= loc <= fin + timedelta(minutes=30):
            return 0
        return min(abs((loc - ini).total_seconds()), abs((loc - fin).total_seconds()))

    ev = min(eventi, key=distanza)
    persone = []
    org = (ev.get("organizer") or {}).get("emailAddress") or {}
    for a in [{"emailAddress": org}] + (ev.get("attendees") or []):
        e = a.get("emailAddress") or {}
        if e.get("address") and e["address"].lower() not in {p["email"].lower() for p in persone}:
            persone.append({"nome": e.get("name") or e["address"], "email": e["address"]})
    return {"oggetto": ev.get("subject", ""), "inizio": ev["start"]["dateTime"][:16].replace("T", " "),
            "persone": persone}


# ---------------------------------------------------------------- Outlook
def destinatari_da_testo(testo):
    """'Markus <markus@x.it>, anna@x.it' -> [{'nome','email'}]"""
    out = []
    for parte in re.split(r"[;,\n]", testo or ""):
        m = RE_EMAIL.search(parte)
        if m:
            nome = parte.replace(m.group(0), "").strip(" <>\"'") or m.group(0)
            out.append({"nome": nome, "email": m.group(0)})
    return out


def separa_oggetto(mail):
    righe = (mail or "").strip().splitlines()
    if righe and re.match(r"^\s*(\*\*)?(oggetto|subject|betreff)(\*\*)?\s*:", righe[0], re.I):
        ogg = righe[0].split(":", 1)[1].strip(" *")
        return ogg, "\n".join(righe[1:]).strip()
    return "Recap della riunione", (mail or "").strip()


def crea_bozza(mail, destinatari):
    oggetto, corpo = separa_oggetto(mail)
    msg = {"subject": oggetto, "body": {"contentType": "Text", "content": corpo},
           "toRecipients": [{"emailAddress": {"address": d["email"], "name": d["nome"]}} for d in destinatari]}
    r = graph("POST", "/me/messages", msg)
    return {"id": r.get("id"), "link": r.get("webLink"), "oggetto": oggetto}


# ---------------------------------------------------------------- Planner
def piani():
    """Piani Planner dell'utente: [{'id','titolo'}]"""
    return [{"id": p["id"], "titolo": p.get("title", "")} for p in graph("GET", "/me/planner/plans").get("value", [])]


def bucket(piano_id):
    return [{"id": b["id"], "nome": b.get("name", "")} for b in
            graph("GET", f"/planner/plans/{piano_id}/buckets").get("value", [])]


def trova_utenti(persone):
    """{'nome visualizzato': id} per le email note (partecipanti della riunione)."""
    out = {}
    for p in persone:
        try:
            u = graph("GET", f"/users/{urllib.parse.quote(p['email'])}?$select=id,displayName")
            out[u.get("displayName") or p["nome"]] = u["id"]
        except ErroreM365:
            continue
    return out


def assegnatario(responsabile, utenti):
    """Abbina 'Marco' o 'Marco Rossi' a un utente; None se ambiguo o assente."""
    r = (responsabile or "").strip().lower()
    if not r or r.startswith("non "):
        return None
    trovati = [uid for nome, uid in utenti.items()
               if r == nome.lower() or r in nome.lower().split() or nome.lower().startswith(r)]
    return trovati[0] if len(trovati) == 1 else None


def crea_task(piano_id, bucket_id, task, utenti):
    creati = []
    for t in task:
        corpo = {"planId": piano_id, "bucketId": bucket_id, "title": t["titolo"][:255]}
        if t.get("scadenza_iso"):
            corpo["dueDateTime"] = f"{t['scadenza_iso']}T16:00:00Z"
        uid = assegnatario(t.get("responsabile"), utenti)
        if uid:
            corpo["assignments"] = {uid: {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}}
        r = graph("POST", "/planner/tasks", corpo)
        creati.append({"titolo": t["titolo"], "id": r.get("id"), "assegnato": bool(uid)})
    return creati
