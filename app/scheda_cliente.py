"""scheda_cliente.py - «Client Intel Scout» in locale: profilo pubblico di un'azienda.

Stesse regole dell'agente Copilot Studio Client Intel Scout (istruzioni v20260819.0334, AIFirst ›
Sviluppo AI › Copilot Studio › Agents › Client Intel Scout), con due differenze di architettura:
- la ricerca web la fa Ollama Web Search (ricerca_web.py): esce solo il nome dell'azienda;
- il modello è quello locale di Ollama, e lavora SOLO sulle pagine scaricate, passate con URL e data:
  niente memoria del modello, niente fonti non consultate.

Passi: ricerche mirate → pagine scaricate (prima il sito ufficiale) → controllo omonimia → profilo in 10 sezioni
→ dati strutturati per proporre l'account in Dynamics.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import llm_locale as llm
import relazione_incontro as rel
import ricerca_web as web
import voci_core as core

CARTELLA = core.APP_HOME / "clienti"
CARATTERI_PER_PAGINA = 5_000
PAGINE_MASSIME = 7

# Livelli di affidabilità (istruzioni di Client Intel Scout, «Regole sulle fonti»)
ISTITUZIONALI = ("registroimprese", "infocamere", "camcom", "gov.it", "europa.eu",
                 "agenziaentrate", "inps.it", "consob")  # ufficiocamerale è un portale privato: livello 4
TESTATE = ("ilsole24ore", "corriere", "repubblica", "lastampa", "milanofinanza", "reuters", "bloomberg",
           "ansa", "affaritaliani", "economyup", "zerounoweb", "corrierecomunicazioni", "industriaitaliana")
AGGREGATORI = ("reportaziende", "fatturatoitalia", "companyreports", "linkedin", "crunchbase", "zoominfo",
               "dnb.com", "kompass", "atoka", "ufficiocamerale")

ISTRUZIONI = """Sei Client Intel Scout, un assistente di ricerca che raccoglie informazioni PUBBLICHE su aziende
a supporto della fase presales. Fornisci materiale grezzo, verificabile e datato. Rispondi in italiano,
con stile professionale e asciutto.

USI SOLO LE FONTI FORNITE QUI SOTTO (pagine scaricate, ciascuna con numero, URL e data di consultazione).
Non usare conoscenze tue: se un dato non è nelle fonti, scrivi [DATO NON DISPONIBILE].

Cosa cerchi: 1 Identità (denominazione esatta, forma giuridica, sito ufficiale); 2 Settore e attività reale;
3 Dimensione (fatturato e dipendenti SEMPRE con anno); 4 Sedi e geografia; 5 Struttura societaria (gruppo,
controllante, controllate); 6 Momento aziendale (acquisizioni, fusioni, aperture, riorganizzazioni, cambi di
proprietà, investimenti, nuovi mercati, ricambio generazionale); 7 Notizie recenti degli ultimi 24 mesi;
8 Segnali tecnologici pubblici solo se esplicitamente pubblicati (casi studio, comunicati IT, offerte di lavoro
che nominano tecnologie, certificazioni).
Dato di gruppo e dato della singola società: riportali entrambi, distinti.

NON profili persone fisiche oltre nome, ruolo e data di nomina pubblicati dall'azienda o da fonti istituzionali.
NON fai valutazioni economiche, di solvibilità o di rischio. NON stimi fatturato o dipendenti. NON deduci lo stack
tecnologico da indizi indiretti. NON suggerisci soluzioni o approcci commerciali. NON riproduci testi lunghi.

Fonti: dopo ogni dato metti [n] con il numero della fonte. Affidabilità: 1 sito ufficiale e comunicati,
2 registri e fonti istituzionali, 3 testate riconosciute, 4 portali di dati aggregati, 5 altro (dichiaralo).
Fonti in contraddizione: riporta entrambe con le date, non scegliere. Dato con più di 24 mesi rispetto alla data
della ricerca: [DATO POTENZIALMENTE SUPERATO]. Campo senza fonte attendibile: [DATO NON DISPONIBILE].

Formato (non omettere sezioni: se vuote, dichiaralo):
# Profilo pubblico — <Ragione sociale>
Ricerca eseguita il: <AAAA-MM-GG>
## 1. Identità
## 2. Settore e attività
## 3. Dimensione
## 4. Sedi e geografia
## 5. Struttura societaria
## 6. Momento aziendale
## 7. Notizie recenti (ultimi 24 mesi)
## 8. Segnali tecnologici pubblici
## 9. Dati non reperiti   (obbligatoria: cosa manca e come ottenerlo: domanda al cliente, documento, registro)
(La sezione 10 «Elenco fonti consultate» la aggiunge Argo: non scriverla.)

Un profilo con molte sezioni [DATO NON DISPONIBILE] è corretto; un profilo completo ma inventato è un danno."""

NOTA_FINALE = ("> Informazioni pubbliche non verificate presso l'azienda. Da confermare in sede di\n"
               "> discovery prima di qualsiasi uso in un documento destinato al cliente.")

SCHEMA_OMONIMIA = {
    "type": "object",
    "properties": {
        "ambiguo": {"type": "boolean"},
        "candidati": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "sito": {"type": "string"}, "sede": {"type": "string"},
            "descrizione": {"type": "string"}}, "required": ["nome"]}},
        "sito_ufficiale": {"type": "string"},
    },
    "required": ["ambiguo", "candidati", "sito_ufficiale"],
}

SCHEMA_ACCOUNT = {
    "type": "object",
    "properties": {
        "ragione_sociale": {"type": "string"}, "sito": {"type": "string"}, "citta": {"type": "string"},
        "provincia": {"type": "string"}, "nazione": {"type": "string"}, "indirizzo": {"type": "string"},
        "cap": {"type": "string"}, "telefono": {"type": "string"}, "email": {"type": "string"},
        "partita_iva": {"type": "string"}, "settore": {"type": "string"},
        "dipendenti": {"type": "integer"}, "dipendenti_anno": {"type": "string"},
        "fatturato_euro": {"type": "number"}, "fatturato_anno": {"type": "string"},
        "gruppo": {"type": "string"}, "descrizione": {"type": "string"},
    },
    "required": ["ragione_sociale"],
}


class ErroreScheda(RuntimeError):
    pass


def _slug(testo):
    return re.sub(r"[^a-z0-9]+", "-", (testo or "").lower()).strip("-")[:60] or "azienda"


def _dominio(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def livello(url, sito_ufficiale=""):
    d = _dominio(url)
    if sito_ufficiale and d and _dominio(sito_ufficiale) and d.endswith(_dominio(sito_ufficiale)):
        return 1
    if any(x in d for x in ISTITUZIONALI):
        return 2
    if any(x in d for x in TESTATE):
        return 3
    if any(x in d for x in AGGREGATORI):
        return 4
    return 5


def _chiama(modello, url, sistema, utente, formato=None, stop=None):
    return rel._chiama(url, modello, [{"role": "system", "content": sistema}, {"role": "user", "content": utente}],
                       formato=formato, contesto=32768, stop=stop)


def ricerca(nome, extra="", url_ollama=None, modello=None, stato=lambda _t: None, avanzamento=lambda _p: None,
            stop=None, scelta_candidato=None):
    """Scheda pubblica dell'azienda. Ritorna dict con: stato ('ok' | 'ambiguo'), candidati, markdown, account, fonti,
    cartella. `extra` = sito, sede o partita IVA per disambiguare."""
    s = core.carica_impostazioni()
    url_ollama = url_ollama or s.get("ollama_url", llm.DEFAULT_URL)
    modello = modello or s.get("modello_chat")
    if not llm.e_locale(url_ollama):
        raise ErroreScheda("L'indirizzo di Ollama non è locale: la scheda si scrive solo con un modello su questo computer.")
    if not modello:
        raise ErroreScheda("Scegli un modello per i testi in Impostazioni › Modelli.")
    oggi = date.today().isoformat()
    anno = date.today().year
    chiave = f'"{nome}" {extra}'.strip()

    # 1 · ricerche mirate (query brevi: esce solo il nome dell'azienda e l'eventuale elemento distintivo)
    query = [chiave, f"{chiave} sito ufficiale chi siamo", f"{chiave} fatturato dipendenti",
             f"{chiave} sede legale partita IVA", f"{chiave} notizie {anno - 1} {anno}",
             f"{chiave} acquisizione OR investimento OR nuovo stabilimento"]
    risultati, visti = [], set()
    for i, q in enumerate(query, 1):
        stato(f"Cerco sul web ({i}/{len(query)}): {q}")
        for r in web.cerca(q, 6):
            u = r.get("url", "")
            if u and u not in visti:
                visti.add(u)
                risultati.append(r)
        avanzamento(int(i * 30 / len(query)))
    if not risultati:
        raise ErroreScheda(f"Nessun risultato web per «{nome}».")

    # 2 · omonimia (regola di Client Intel Scout: se ambiguo ci si ferma e si chiede)
    stato("Controllo che non ci siano aziende omonime…")
    elenco = "\n".join(f"- {r.get('title', '')} | {r.get('url', '')} | {(r.get('content') or '')[:300]}" for r in risultati[:25])
    controllo = json.loads(_chiama(modello, url_ollama,
        "Analizzi risultati di ricerca su un'azienda. Rispondi solo con il JSON richiesto, senza inventare.",
        f"Azienda cercata: {nome} {extra}\nRisultati:\n{elenco}\n\n"
        "Se i risultati parlano di più aziende diverse con lo stesso nome e l'elemento distintivo non basta, "
        "ambiguo=true ed elenca i candidati (nome, sito, sede, descrizione breve). Altrimenti ambiguo=false. "
        "In sito_ufficiale metti l'URL del sito ufficiale dell'azienda cercata se è tra i risultati, altrimenti vuoto.",
        formato=SCHEMA_OMONIMIA, stop=stop))
    if controllo.get("ambiguo") and not extra and not scelta_candidato:
        return {"stato": "ambiguo", "candidati": controllo.get("candidati", [])}
    sito = (scelta_candidato or {}).get("sito") or controllo.get("sito_ufficiale") or ""
    avanzamento(38)

    # 3 · pagine da leggere: prima il sito ufficiale, poi registri, testate, aggregatori
    ordinati = sorted(risultati, key=lambda r: livello(r.get("url", ""), sito))
    if sito and not any(_dominio(r.get("url", "")) == _dominio(sito) for r in ordinati):
        ordinati.insert(0, {"url": sito, "title": "Sito ufficiale"})
    fonti = []
    for r in ordinati:
        if len(fonti) >= PAGINE_MASSIME:
            break
        u = r["url"]
        stato(f"Leggo la fonte {len(fonti) + 1}: {_dominio(u)}")
        try:
            pagina = web.scarica(u)
            testo = (pagina.get("content") or "").strip()
        except web.ErroreRicerca:
            testo = (r.get("content") or "").strip()
        if len(testo) < 200:
            testo = testo or (r.get("content") or "")
        if not testo:
            continue
        fonti.append({"n": len(fonti) + 1, "titolo": (r.get("title") or _dominio(u))[:120], "url": u,
                      "dominio": _dominio(u), "livello": livello(u, sito), "consultato": oggi,
                      "testo": testo[:CARATTERI_PER_PAGINA]})
        avanzamento(38 + int(len(fonti) * 30 / PAGINE_MASSIME))
    if not fonti:
        raise ErroreScheda("Nessuna pagina leggibile tra i risultati.")

    # 4 · profilo in 10 sezioni, solo dalle fonti
    stato(f"Scrivo la scheda con {modello}…")
    blocco = "\n\n".join(f"### FONTE [{f['n']}] — {f['dominio']} (livello {f['livello']}) — consultato il {f['consultato']}\n"
                         f"URL: {f['url']}\n{f['testo']}" for f in fonti)
    profilo = _chiama(modello, url_ollama, ISTRUZIONI,
                      f"Data della ricerca: {oggi}\nAzienda: {nome} {extra}\n"
                      + (f"Candidato scelto dall'utente: {json.dumps(scelta_candidato, ensure_ascii=False)}\n" if scelta_candidato else "")
                      + f"\nFONTI:\n\n{blocco}", stop=stop)
    avanzamento(85)
    tabella = ["## 10. Elenco fonti consultate", "", "| # | Fonte | URL | Data di consultazione | Livello |",
               "|---|---|---|---|---|"]
    tabella += [f"| {f['n']} | {f['titolo'].replace('|', '/')} | {f['url']} | {f['consultato']} | {f['livello']} |" for f in fonti]
    markdown = profilo.rstrip() + "\n\n" + "\n".join(tabella) + "\n\n" + NOTA_FINALE + "\n"

    # 5 · dati per l'account (solo ciò che è scritto nel profilo)
    stato("Preparo i dati per l'account in Dynamics…")
    account = json.loads(_chiama(modello, url_ollama,
        "Estrai dati anagrafici dal profilo. Solo dati presenti nel testo; campi assenti vuoti o omessi. "
        "Niente valori con [DATO NON DISPONIBILE]. Fatturato in euro come numero, solo se scritto.",
        markdown, formato=SCHEMA_ACCOUNT, stop=stop))
    avanzamento(100)

    cartella = CARTELLA / _slug(account.get("ragione_sociale") or nome)
    cartella.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    (cartella / f"scheda-{marca}.md").write_text(markdown, encoding="utf-8")
    (cartella / f"scheda-{marca}.json").write_text(json.dumps({
        "azienda": nome, "extra": extra, "ricerca": oggi, "modello": modello, "account": account,
        "fonti": [{k: v for k, v in f.items() if k != "testo"} for f in fonti]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"stato": "ok", "markdown": markdown, "account": account, "fonti": fonti, "cartella": cartella}


def schede_salvate(nome):
    """Schede già fatte per quel nome (dalla più recente)."""
    c = CARTELLA / _slug(nome)
    return sorted(c.glob("scheda-*.md"), reverse=True) if c.exists() else []
