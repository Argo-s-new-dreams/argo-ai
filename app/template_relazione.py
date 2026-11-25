"""template_relazione.py - come deve essere fatta la relazione di un incontro.

Un template dice:
    - la forma: «schede» (sezioni fisse dal catalogo SEZIONI) oppure «documento» (un documento di lavoro libero,
      con capitoli, tabelle e le foto dentro il testo dove aiutano a spiegare, secondo la «struttura» del template);
    - quali sezioni mostrare e in che ordine (scelte dal catalogo SEZIONI, forma «schede»);
    - quanto lunga (breve, media, dettagliata);
    - le indicazioni libere dell'utente («come la voglio»: taglio, tono, a chi è rivolta, cosa evidenziare).

I dati di base (contatti, aziende, azioni) vengono estratti sempre, anche se il template non li mostra:
servono all'invio a Dynamics e alla pagina Clienti. Il template cambia cosa si legge, non cosa si perde.

Template standard (sempre presenti, non modificabili: si duplicano) + template dell'utente,
salvati nelle impostazioni ("template_relazione"), con un predefinito ("template_relazione_predefinito").
Solo libreria standard.
"""
import copy
import uuid

import voci_core as core

# chiave -> (titolo della sezione, cosa deve scrivere il modello)
SEZIONI = {
    "riassunto": ("Riassunto", "sintesi dell'incontro: chi, perché, com'è andata, esito"),
    "contatti": ("Contatti", "persone incontrate con ruolo, azienda e recapiti trovati nel testo o nelle foto"),
    "aziende": ("Aziende", "aziende coinvolte con settore, città, sito"),
    "esigenze": ("Esigenze del cliente", "bisogni, problemi e obiettivi espressi dall'interlocutore"),
    "interessi": ("Interessi", "prodotti, servizi o temi per cui l'interlocutore ha mostrato interesse"),
    "opportunita": ("Opportunità", "opportunità commerciale: descrizione, prodotti, budget, tempi, decisori, concorrenti, prossimo passo"),
    "temi": ("Temi e risposte", "per ogni tema o domanda affrontata: sintesi della risposta e, se c'è, una citazione breve e fedele"),
    "punti_chiave": ("Punti chiave", "i fatti e i passaggi più importanti emersi"),
    "decisioni": ("Decisioni", "decisioni prese durante l'incontro, con chi le ha prese se è chiaro"),
    "punti_aperti": ("Punti aperti", "questioni non risolte, dubbi, informazioni mancanti"),
    "rischi": ("Rischi e criticità", "ostacoli, obiezioni, rischi e segnali di attenzione"),
    "azioni": ("Azioni", "cose da fare, con responsabile e scadenza se dette"),
}
SEMPRE_ESTRATTE = ("contatti", "aziende", "azioni")  # per CRM e Clienti, anche se non mostrate
FORME = {
    "schede": ("Schede (sezioni)", "Relazione a sezioni fisse: riassunto, temi, esigenze, azioni…"),
    "documento": ("Documento con figure", "Documento di lavoro libero, con capitoli, tabelle e le foto dentro il testo"),
}

STRUTTURA_ENVISION = """Copertina: una riga in maiuscolo «ENVISION FRONTIER FIRM»; poi «# <nome del cliente>»; una riga di sottotitolo che sintetizza la trasformazione («Da … a …»); la foto più rappresentativa; la riga «Riepilogo strategico basato sugli incontri del <date>»; la riga «Documento di lavoro per workshop Envision».
## 1. Executive summary: perché non basta automatizzare un singolo passaggio; la North Star in grassetto (una frase); 3-5 direzioni principali in elenco puntato; poi «### Le aree prioritarie» con una tabella Area | Problema osservato | Direzione Frontier Firm.
## 2. Il processo attuale: la catena end-to-end in una riga con le frecce (FASE → FASE → …); poi un sottocapitolo per ogni fase osservata (### 2.1, ### 2.2…) con cosa succede oggi, strumenti usati, passaggi manuali e punti di attrito, e le foto che lo mostrano.
## Dal 3 in poi: un capitolo per ogni area critica emersa, nell'ordine del processo: cosa succede, le foto che lo spiegano, perché conta (tempi, errori, costi, volumi citati) e la scheda dell'agente proposto come tabella a due colonne con intestazione «Agent N - Nome dell'agente» e righe Cosa fa | Input | Output | Human in the loop | Beneficio atteso. Dove aiuta, un «### Esempio di trasformazione» in tabella (Prima | Dopo).
## Architettura concettuale Frontier Firm: tabella Livello | Componenti candidate | Funzione (persone, agenti, dati e documenti, sistemi esistenti, canali); una nota sui vincoli da verificare; «### Principi di progettazione» in elenco.
## Roadmap proposta: tabella Wave | Ambito | Output | Orizzonte indicativo | KPI principale; poi «### PoC consigliato» con il caso, cosa serve e come si decide go/no-go.
## KPI per il business case: tabella KPI | Baseline da misurare | Target iniziale indicativo; poi «### Criteri di successo» in elenco.
## Messaggio conclusivo: due frasi da citare, tra virgolette; il prossimo passo consigliato.
### Nota sulla fonte: documento elaborato dalla trascrizione automatica degli incontri del <date>, fatta con Argo in locale; nomi dei parlanti e testo possono contenere errori; le immagini sono foto scattate durante gli incontri, collegate al momento del discorso."""

LUNGHEZZE = {
    "breve": ("Breve", "Sii molto sintetico: riassunto di 3-5 righe, elenchi di poche voci, solo l'essenziale."),
    "media": ("Media", "Lunghezza media: riassunto di un paragrafo, elenchi completi ma senza ripetizioni."),
    "dettagliata": ("Dettagliata", "Sii completo e dettagliato: riassunto di più paragrafi, riporta tutti i passaggi "
                                   "rilevanti con cifre, nomi e motivazioni."),
}

STANDARD = [
    {
        "id": "fiera", "nome": "Fiera · primo contatto", "standard": True,
        "descrizione": "Incontri allo stand o in fiera: chi era, di cosa ha bisogno, quanto vale il contatto, come richiamarlo.",
        "sezioni": ["riassunto", "contatti", "aziende", "interessi", "opportunita", "azioni"],
        "lunghezza": "media",
        "istruzioni": "Qualifica il contatto come un buon commerciale: interesse reale, ruolo nella decisione, "
                      "urgenza. Nel riassunto dai un giudizio sul potenziale (alto, medio, basso) e motivalo.",
    },
    {
        "id": "visita", "nome": "Visita cliente", "standard": True,
        "descrizione": "Riunione commerciale con un cliente o un prospect: esigenze, opportunità, decisioni e prossimi passi.",
        "sezioni": ["riassunto", "esigenze", "opportunita", "decisioni", "rischi", "azioni", "contatti"],
        "lunghezza": "media",
        "istruzioni": "Scrivi per il collega commerciale che deve seguire il cliente: metti in evidenza esigenze, "
                      "obiezioni e impegni presi da entrambe le parti.",
    },
    {
        "id": "interna", "nome": "Riunione interna · verbale", "standard": True,
        "descrizione": "Riunioni di progetto o di team: decisioni, punti aperti, azioni con responsabile e scadenza.",
        "sezioni": ["riassunto", "punti_chiave", "decisioni", "punti_aperti", "azioni"],
        "lunghezza": "media",
        "istruzioni": "Tono neutro da verbale, nessun linguaggio commerciale. Attribuisci le decisioni e le azioni "
                      "alle persone che le hanno prese. Non includere contatti e aziende nel testo.",
    },
    {
        "id": "intervista", "nome": "Intervista · assessment", "standard": True,
        "descrizione": "Interviste a clienti o colleghi (assessment, analisi dei processi, Frontier Firm): temi, risposte, bisogni.",
        "sezioni": ["riassunto", "temi", "esigenze", "rischi", "punti_aperti", "azioni"],
        "lunghezza": "dettagliata",
        "istruzioni": "Organizza per temi, nell'ordine in cui sono stati affrontati. Riporta fedelmente le risposte "
                      "senza interpretarle; aggiungi citazioni brevi solo se sono parole davvero dette. "
                      "Evidenzia processi manuali, strumenti usati e opportunità di miglioramento con l'AI.",
    },
    {
        "id": "breve", "nome": "Nota rapida · CRM o mail", "standard": True,
        "descrizione": "Poche righe da incollare in un'attività del CRM o in una mail: cosa è successo e cosa fare.",
        "sezioni": ["riassunto", "azioni"],
        "lunghezza": "breve",
        "istruzioni": "Scrivi come una nota da incollare nel CRM: frasi brevi, niente premesse.",
    },
    {
        "id": "envision", "nome": "Envision · Frontier Firm", "standard": True, "forma": "documento",
        "descrizione": "Documento di lavoro per un workshop Envision: processo attuale, aree critiche, agenti AI proposti, "
                       "architettura, roadmap e KPI, con le foto dentro il testo.",
        "sezioni": ["riassunto", "temi", "esigenze", "azioni"],
        "lunghezza": "dettagliata",
        "struttura": STRUTTURA_ENVISION,
        "istruzioni": "Scrivi per il management del cliente e per il team che progetterà la soluzione: tono da "
                      "consulente, concreto, senza enfasi. Parti sempre da ciò che è stato visto e detto negli "
                      "incontri; le proposte (agenti, architettura, roadmap, KPI) presentale come proposte da "
                      "validare nel workshop. Le cifre solo come sono state dette; i target sono indicativi.",
    },
]
PREDEFINITO = "fiera"


# ---------------------------------------------------------------- elenco e salvataggio
def personali():
    return [dict(t, standard=False) for t in core.carica_impostazioni().get("template_relazione") or []]


def tutti():
    return copy.deepcopy(STANDARD) + personali()


def trova(id_template):
    return next((t for t in tutti() if t["id"] == id_template), None)


def predefinito():
    scelto = core.carica_impostazioni().get("template_relazione_predefinito") or PREDEFINITO
    return trova(scelto) or trova(PREDEFINITO)


def imposta_predefinito(id_template):
    s = core.carica_impostazioni()
    s["template_relazione_predefinito"] = id_template
    core.salva_impostazioni(s)


def _pulisci(t):
    sezioni = [x for x in t.get("sezioni", []) if x in SEZIONI] or ["riassunto"]
    return {
        "id": t.get("id") or uuid.uuid4().hex[:8],
        "nome": (t.get("nome") or "Template senza nome").strip()[:80],
        "descrizione": (t.get("descrizione") or "").strip()[:300],
        "sezioni": list(dict.fromkeys(sezioni)),
        "lunghezza": t.get("lunghezza") if t.get("lunghezza") in LUNGHEZZE else "media",
        "istruzioni": (t.get("istruzioni") or "").strip()[:3000],
        "forma": t.get("forma") if t.get("forma") in FORME else "schede",
        "struttura": (t.get("struttura") or "").strip()[:6000],
    }


def salva(template):
    """Crea o aggiorna un template personale. Ritorna il template salvato."""
    if template.get("standard") or any(s["id"] == template.get("id") for s in STANDARD):
        raise ValueError("I template standard non si modificano: duplicali.")
    t = _pulisci(template)
    s = core.carica_impostazioni()
    elenco = [x for x in s.get("template_relazione") or [] if x.get("id") != t["id"]]
    vecchi = [x.get("id") for x in s.get("template_relazione") or []]
    posizione = vecchi.index(t["id"]) if t["id"] in vecchi else len(elenco)
    elenco.insert(posizione, t)
    s["template_relazione"] = elenco
    core.salva_impostazioni(s)
    return t


def duplica(id_template):
    origine = trova(id_template) or trova(PREDEFINITO)
    copia = dict(copy.deepcopy(origine), id=uuid.uuid4().hex[:8], nome=origine["nome"] + " (copia)", standard=False)
    return salva(copia)


def elimina(id_template):
    s = core.carica_impostazioni()
    s["template_relazione"] = [x for x in s.get("template_relazione") or [] if x.get("id") != id_template]
    if s.get("template_relazione_predefinito") == id_template:
        s["template_relazione_predefinito"] = PREDEFINITO
    core.salva_impostazioni(s)


# ---------------------------------------------------------------- per il modello
def e_documento(template):
    return (template or {}).get("forma") == "documento"


def guida(template):
    """Indicazioni da aggiungere alle istruzioni del modello."""
    t = template or trova(PREDEFINITO)
    righe = [f"TIPO DI RELAZIONE: {t['nome']}." + (f" {t['descrizione']}" if t.get("descrizione") else "")]
    righe.append("Sezioni da curare, in quest'ordine:")
    righe += [f"- {SEZIONI[k][0]} ({k}): {SEZIONI[k][1]}" for k in t["sezioni"] if k in SEZIONI]
    altre = [k for k in SEZIONI if k not in t["sezioni"] and k not in SEMPRE_ESTRATTE and k != "riassunto"]
    if altre:
        righe.append("Lascia vuoti (stringa vuota o elenco vuoto) i campi: " + ", ".join(altre) + ".")
    righe.append("Compila comunque contatti, aziende e azioni quando compaiono nel testo: servono al CRM.")
    righe.append(LUNGHEZZE[t.get("lunghezza", "media")][1])
    if t.get("istruzioni"):
        righe.append("INDICAZIONI DELL'UTENTE (hanno la precedenza sullo stile, mai sulle regole di fedeltà):\n"
                     + t["istruzioni"])
    return "\n".join(righe)
