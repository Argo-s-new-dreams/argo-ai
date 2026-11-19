"""crm_dynamics.py - Dynamics 365 Sales (Dataverse Web API) per gli Incontri.

Accesso delegato con la stessa app Entra di Microsoft 365 (m365.py), con in più il permesso
«Dynamics CRM · user_impersonation». Su Dynamics va solo ciò che l'utente conferma nella finestra di invio:
lead o aggancio a contatti/account esistenti, la relazione come nota, le foto come allegati, le azioni come attività.
Mai audio, mai impronte vocali.
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import m365
import voci_core as core

VERSIONE_API = "v9.2"
# Origine del lead (leadsourcecode): 7 = Fiera/Trade Show, 10 = Altro (valori standard di Dynamics 365 Sales)
ORIGINE_LEAD = {"fiera": 7}


class ErroreCRM(Exception):
    pass


# ---------------------------------------------------------------- configurazione e accesso
def ambiente():
    """URL dell'ambiente, es. https://nome-ambiente.crm4.dynamics.com (senza / finale)."""
    url = (core.carica_impostazioni().get("d365_url") or "").strip().rstrip("/")
    if url and not url.startswith("https://"):
        url = "https://" + url.split("://")[-1]
    return url


def configurato():
    return bool(ambiente()) and m365.configurato()


def _scopes():
    return [f"{ambiente()}/user_impersonation"]


def accedi():
    """Accesso interattivo (browser di sistema) per il permesso su Dataverse. Bloccante: va in un thread."""
    if not configurato():
        raise ErroreCRM("Inserisci Client ID e Tenant ID (Microsoft 365) e l'indirizzo dell'ambiente Dynamics.")
    try:
        app, cache = m365._app()
    except m365.ErroreM365 as e:
        raise ErroreCRM(str(e)) from None
    r = app.acquire_token_interactive(
        _scopes(), prompt="select_account", timeout=300,
        success_template="<html><body style='font-family:sans-serif'><h2>Argo è collegato a Dynamics 365.</h2>"
                         "<p>Puoi chiudere questa scheda e tornare ad Argo.</p></body></html>",
        error_template="<html><body style='font-family:sans-serif'><h2>Accesso non riuscito</h2>"
                       "<p>$error: $error_description</p></body></html>")
    m365._salva_cache(cache)
    if "access_token" not in r:
        raise ErroreCRM(_spiega(r))
    return chi_sono()


def _spiega(r):
    desc = r.get("error_description") or r.get("error") or "accesso non riuscito"
    if "AADSTS65001" in desc or "consent" in desc.lower():
        return ("Manca il consenso al permesso «Dynamics CRM · user_impersonation» nell'app Entra di Argo: "
                "aggiungilo in API permissions e premi «Grant admin consent».")
    return m365._spiega(r)


def _token():
    try:
        app, cache = m365._app()
    except m365.ErroreM365 as e:
        raise ErroreCRM(str(e)) from None
    acc = app.get_accounts()
    r = app.acquire_token_silent(_scopes(), account=acc[0]) if acc else None
    m365._salva_cache(cache)
    if not r or "access_token" not in r:
        raise ErroreCRM("Dynamics 365 non collegato: Impostazioni › Dynamics 365 Sales › Collega.")
    return r["access_token"]


# ---------------------------------------------------------------- Web API
_TIPI = {"leads": "nuovo lead", "annotations": "nota (relazione) su un record", "tasks": "attività",
         "accounts": "nuovo account", "contacts": "nuovo contatto"}


def _uscita(metodo, percorso):
    """Cosa esce verso Dynamics: record creati o modificati e i testi delle ricerche (nomi, mail, aziende)."""
    entita = percorso.split("?")[0].strip("/").split("(")[0].split("/")[-1]
    if metodo in ("POST", "PATCH"):
        cosa = _TIPI.get(entita, f"dati del record «{entita}»")
    elif metodo == "GET" and "$filter" in percorso:
        cosa = "ricerca nel CRM (nomi, mail o aziende)"
    else:
        return
    import uscite
    uscite.registra("Dynamics 365 Sales", cosa)


def api(metodo, percorso, corpo=None, token=None):
    """Chiamata alla Dataverse Web API. Ritorna (json, id_creato)."""
    if not ambiente():
        raise ErroreCRM("Indirizzo dell'ambiente Dynamics mancante (Impostazioni).")
    _uscita(metodo, percorso)
    url = percorso if percorso.startswith("http") else f"{ambiente()}/api/data/{VERSIONE_API}/{percorso.lstrip('/')}"
    # Spazi e caratteri speciali dei filtri OData vanno codificati (i valori sono già protetti da _q)
    url = urllib.parse.quote(url, safe=":/?&=$(),'@*!;%-._~")
    dati = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo, headers={
        "Authorization": f"Bearer {token or _token()}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Prefer": 'odata.include-annotations="OData.Community.Display.V1.FormattedValue"',
    })
    ultimo = None
    for ctx in m365._contesti():
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                testo = r.read().decode("utf-8")
                id_creato = None
                entita = r.headers.get("OData-EntityId") or ""
                m = re.search(r"\(([0-9a-fA-F-]{36})\)\s*$", entita)
                if m:
                    id_creato = m.group(1)
                return (json.loads(testo) if testo else {}), id_creato
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            if e.code == 401:
                raise ErroreCRM("Accesso a Dynamics scaduto o non valido: ricollega in Impostazioni.") from None
            if e.code == 403:
                raise ErroreCRM(f"Dynamics ha negato l'operazione (403): controlla licenza e ruolo di sicurezza. {msg}") from None
            raise ErroreCRM(f"Dynamics ha risposto {e.code}: {msg or e.reason}") from None
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(getattr(e, "reason", "")):
                ultimo = e
                continue
            raise ErroreCRM(f"Dynamics non raggiungibile: {e.reason}") from None
    raise ErroreCRM(f"Certificato non verificato: {ultimo}")


def chi_sono():
    """Prova di collegamento: nome dell'utente in Dynamics."""
    dati, _ = api("GET", "WhoAmI")
    utente, _ = api("GET", f"systemusers({dati['UserId']})?$select=fullname")
    return utente.get("fullname") or dati["UserId"]


def link(entita, id_record):
    return f"{ambiente()}/main.aspx?etn={entita}&pagetype=entityrecord&id={id_record}"


def _q(testo):
    """Valore per un filtro OData: apici raddoppiati e caratteri che spezzerebbero l'indirizzo codificati."""
    testo = (testo or "").replace("'", "''")
    return "".join(urllib.parse.quote(c, safe="") if c in "&#+%?/=" else c for c in testo)


# ---------------------------------------------------------------- ricerca di duplicati
def cerca(contatto):
    """Possibili record già presenti per un contatto della relazione: [(tipo, id, descrizione)]."""
    trovati = []
    email = (contatto.get("email") or "").strip()
    nome_completo = " ".join(x for x in (contatto.get("nome"), contatto.get("cognome")) if x).strip()
    azienda = (contatto.get("azienda") or "").strip()

    filtri_persona = []
    if email:
        filtri_persona.append(f"emailaddress1 eq '{_q(email)}'")
    if nome_completo and contatto.get("cognome"):
        filtri_persona.append(f"contains(fullname,'{_q(nome_completo)}')")
    if filtri_persona:
        f = " or ".join(filtri_persona)
        dati, _ = api("GET", "contacts?$select=contactid,fullname,emailaddress1,jobtitle,_parentcustomerid_value"
                             f"&$filter=({f}) and statecode eq 0&$top=5")
        for c in dati.get("value", []):
            societa = c.get("_parentcustomerid_value@OData.Community.Display.V1.FormattedValue", "")
            trovati.append(("contact", c["contactid"], " · ".join(x for x in (
                c.get("fullname"), societa, c.get("emailaddress1")) if x)))
        dati, _ = api("GET", "leads?$select=leadid,fullname,companyname,emailaddress1"
                             f"&$filter=({f}) and statecode eq 0&$top=5")
        for l in dati.get("value", []):
            trovati.append(("lead", l["leadid"], " · ".join(x for x in (
                l.get("fullname"), l.get("companyname"), l.get("emailaddress1")) if x)))
    if azienda:
        nome_breve = re.sub(r"\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?n\.?c\.?|s\.?a\.?s\.?|gmbh|ag|ltd|inc)\b\.?", "",
                            azienda, flags=re.I).strip(" .,")
        dati, _ = api("GET", "accounts?$select=accountid,name,address1_city,websiteurl"
                             f"&$filter=contains(name,'{_q(nome_breve or azienda)}') and statecode eq 0&$top=5")
        for a in dati.get("value", []):
            trovati.append(("account", a["accountid"], " · ".join(x for x in (
                a.get("name"), a.get("address1_city"), a.get("websiteurl")) if x)))
    return trovati


# ---------------------------------------------------------------- creazione
INSIEMI = {"lead": "leads", "contact": "contacts", "account": "accounts"}


def crea_lead(contatto, relazione, tipo_incontro):
    """Lead dai dati del contatto e dell'opportunità. Ritorna l'id."""
    o = relazione.get("opportunita") or {}
    cognome = (contatto.get("cognome") or "").strip()
    nome = (contatto.get("nome") or "").strip()
    if not cognome:  # in Dynamics il cognome è obbligatorio: se c'è un solo nome, va lì
        nome, cognome = "", nome or "Contatto"
    oggetto = (o.get("descrizione") or relazione.get("titolo") or "Incontro")[:200]
    corpo = {
        "subject": oggetto,
        "firstname": nome or None,
        "lastname": cognome,
        "jobtitle": contatto.get("ruolo") or None,
        "companyname": contatto.get("azienda") or None,
        "emailaddress1": contatto.get("email") or None,
        "telephone1": contatto.get("telefono") or None,
        "mobilephone": contatto.get("cellulare") or None,
        "websiteurl": contatto.get("sito") or None,
        "description": "\n".join(x for x in (
            relazione.get("riassunto"), contatto.get("note"),
            ("Prossimo passo: " + o["prossimo_passo"]) if o.get("prossimo_passo") else "",
            ("Tempistica: " + o["tempistica"]) if o.get("tempistica") else "",
            ("Budget: " + o["budget"]) if o.get("budget") else "") if x)[:2000] or None,
    }
    if tipo_incontro in ORIGINE_LEAD:
        corpo["leadsourcecode"] = ORIGINE_LEAD[tipo_incontro]
    corpo = {k: v for k, v in corpo.items() if v is not None}
    _, id_lead = api("POST", "leads", corpo)
    if not id_lead:
        raise ErroreCRM("Dynamics non ha restituito l'id del lead creato.")
    return id_lead


def crea_nota(entita, id_record, oggetto, testo, allegato=None):
    """Nota (annotation) sul record; allegato = (nome_file, bytes, mime)."""
    corpo = {
        "subject": oggetto[:500],
        "notetext": testo[:100000],
        f"objectid_{entita}@odata.bind": f"/{INSIEMI[entita]}({id_record})",
    }
    if allegato:
        nome, contenuto, mime = allegato
        corpo.update(filename=nome, mimetype=mime, documentbody=base64.b64encode(contenuto).decode("ascii"),
                     isdocument=True)
    _, id_nota = api("POST", "annotations", corpo)
    return id_nota


def crea_attivita(entita, id_record, azione):
    """Attività (task) collegata al record, da un'azione della relazione."""
    descrizione = " · ".join(x for x in (
        ("Responsabile: " + azione["responsabile"]) if azione.get("responsabile") else "",
        ("Scadenza indicata: " + azione["scadenza"]) if azione.get("scadenza") else "") if x)
    corpo = {
        "subject": (azione.get("descrizione") or "Azione")[:200],
        "description": descrizione or None,
        f"regardingobjectid_{entita}_task@odata.bind": f"/{INSIEMI[entita]}({id_record})",
    }
    _, id_task = api("POST", "tasks", {k: v for k, v in corpo.items() if v is not None})
    return id_task


# ---------------------------------------------------------------- pagina Clienti: account e contatti
SELEZIONE_ACCOUNT = ("accountid,name,websiteurl,address1_city,address1_country,telephone1,emailaddress1,"
                     "numberofemployees,revenue,description,_primarycontactid_value")


def _nome_breve(azienda):
    return re.sub(r"\b(s\.?r\.?l\.?s?|s\.?p\.?a\.?|s\.?n\.?c\.?|s\.?a\.?s\.?|s\.?c\.?a?\.?r\.?l\.?|gmbh|ag|ltd|inc|spa|srl)\b\.?",
                  "", azienda or "", flags=re.I).strip(" .,-")


def dominio_email(email):
    d = (email or "").split("@")[-1].lower().strip()
    pubblici = ("gmail.", "outlook.", "hotmail.", "yahoo.", "libero.it", "icloud.", "live.", "tiscali.", "virgilio.",
                "alice.it", "me.com", "proton")
    return "" if not d or "." not in d or d.startswith(pubblici) else d


def cerca_account(testo, massimo=10):
    """Account attivi per nome, sito o dominio. Ritorna [dict] con i campi di SELEZIONE_ACCOUNT."""
    testo = (testo or "").strip()
    if not testo:
        return []
    filtri = []
    if "." in testo and " " not in testo:  # sembra un sito o un dominio
        dom = testo.split("://")[-1].split("/")[0].removeprefix("www.")
        filtri += [f"contains(websiteurl,'{_q(dom)}')", f"contains(emailaddress1,'{_q(dom)}')"]
        breve = dom.split(".")[0]
    else:
        breve = _nome_breve(testo) or testo
    filtri.append(f"contains(name,'{_q(breve)}')")
    dati, _ = api("GET", f"accounts?$select={SELEZIONE_ACCOUNT}&$filter=({' or '.join(filtri)}) and statecode eq 0"
                         f"&$orderby=name&$top={massimo}")
    return dati.get("value", [])


def account_per_dominio(dominio):
    """Account legati a un dominio email: sito dell'account o email dei suoi contatti."""
    if not dominio:
        return []
    trovati = {a["accountid"]: a for a in cerca_account(dominio)}
    dati, _ = api("GET", "contacts?$select=_parentcustomerid_value"
                         f"&$filter=endswith(emailaddress1,'@{_q(dominio)}') and statecode eq 0&$top=10")
    for c in dati.get("value", []):
        aid = c.get("_parentcustomerid_value")
        if aid and aid not in trovati:
            try:
                a, _ = api("GET", f"accounts({aid})?$select={SELEZIONE_ACCOUNT}")
                trovati[aid] = a
            except ErroreCRM:
                pass
    return list(trovati.values())


def contatti_account(account_id):
    dati, _ = api("GET", "contacts?$select=contactid,fullname,jobtitle,emailaddress1,telephone1"
                         f"&$filter=_parentcustomerid_value eq {account_id} and statecode eq 0&$orderby=fullname&$top=50")
    return dati.get("value", [])


def contatto_per_email(email):
    if not email:
        return None
    dati, _ = api("GET", "contacts?$select=contactid,fullname,_parentcustomerid_value"
                         f"&$filter=emailaddress1 eq '{_q(email)}' and statecode eq 0&$top=1")
    v = dati.get("value", [])
    return v[0] if v else None


def crea_account(campi):
    """Account da campi già confermati dall'utente. Ritorna l'id."""
    corpo = {
        "name": campi.get("ragione_sociale") or campi.get("name"),
        "websiteurl": campi.get("sito") or None,
        "address1_line1": campi.get("indirizzo") or None,
        "address1_postalcode": campi.get("cap") or None,
        "address1_city": campi.get("citta") or None,
        "address1_stateorprovince": campi.get("provincia") or None,
        "address1_country": campi.get("nazione") or None,
        "telephone1": campi.get("telefono") or None,
        "emailaddress1": campi.get("email") or None,
        "description": campi.get("descrizione") or None,
    }
    if str(campi.get("dipendenti") or "").strip().isdigit():
        corpo["numberofemployees"] = int(str(campi["dipendenti"]).strip())
    if not corpo["name"]:
        raise ErroreCRM("Manca la ragione sociale.")
    _, id_account = api("POST", "accounts", {k: v for k, v in corpo.items() if v is not None})
    if not id_account:
        raise ErroreCRM("Dynamics non ha restituito l'id dell'account creato.")
    return id_account


def crea_contatto(persona, account_id=None):
    """Contatto (nome, cognome, email, ruolo, telefono) legato all'account. Ritorna l'id."""
    nome, cognome = (persona.get("nome") or "").strip(), (persona.get("cognome") or "").strip()
    if not cognome and " " in nome:
        nome, cognome = nome.rsplit(" ", 1)
    corpo = {"firstname": nome or None, "lastname": cognome or nome or "Contatto",
             "emailaddress1": persona.get("email") or None, "jobtitle": persona.get("ruolo") or None,
             "telephone1": persona.get("telefono") or None}
    if account_id:
        corpo["parentcustomerid_account@odata.bind"] = f"/accounts({account_id})"
    _, id_contatto = api("POST", "contacts", {k: v for k, v in corpo.items() if v is not None})
    return id_contatto


def account(account_id):
    dati, _ = api("GET", f"accounts({account_id})?$select={SELEZIONE_ACCOUNT}")
    return dati
