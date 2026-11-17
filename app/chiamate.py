"""chiamate.py - le «call» per la pagina Clienti, da tre sorgenti:

1. Incontri dall'iPhone (ponte.elenco_incontri);
2. trascrizioni fatte con Argo sul computer (coda di Trascrivi): diventano incontri con lo stesso formato
   argo.sessione, così relazione, CRM e task funzionano allo stesso modo;
3. calendario di Outlook: gli invitati della riunione più vicina all'orario della registrazione, con le email
   (servono per proporre l'azienda dal dominio).
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ponte as pt
import voci_core as core


def trascrizioni_desktop():
    """Trascrizioni completate nella coda di Trascrivi: [(job, già_importata)]."""
    try:
        jobs = json.loads(core.QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    importate = {d.get("origine_file") for _c, d in pt.elenco_incontri()}
    out = []
    for j in jobs:
        if j.get("stato") == "Completata" and j.get("json") and Path(j["json"]).exists():
            out.append((j, j["json"] in importate))
    return out


def importa_trascrizione(file_json, titolo=None):
    """Trascrizione WhisperX del desktop → incontro (idempotente sul percorso del file). Ritorna l'id."""
    dati = core.leggi_json(file_json)
    mappa, _m, _c = core.mappa_nomi(dati)
    segmenti, parlanti = [], []
    for s in dati.get("segments", []):
        testo = (s.get("text") or "").strip()
        if not testo:
            continue
        chi = s.get("speaker")
        if chi and chi not in parlanti:
            parlanti.append(chi)
        segmenti.append({"inizio": float(s.get("start") or 0), "fine": float(s.get("end") or 0),
                         "parlante": chi, "testo": testo})
    p = Path(file_json)
    sorgente = next((p.with_suffix(x) for x in (".m4a", ".wav", ".mp3", ".mp4", ".mov", ".webm")
                     if p.with_suffix(x).exists()), p)
    creata = datetime.fromtimestamp(sorgente.stat().st_mtime).astimezone()
    id_incontro = str(uuid.uuid5(uuid.NAMESPACE_URL, "argo-desktop:" + str(p.resolve())))
    sessione = {
        "formato": "argo.sessione", "versioneFormato": 1, "app": "Argo desktop · Trascrivi",
        "id": id_incontro, "creata": creata.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "titolo": titolo or p.stem.replace("_", " "), "lingua": core.carica_impostazioni().get("language", "it"),
        "durata": max((s["fine"] for s in segmenti), default=0),
        "partecipanti": [{"id": s, "nome": mappa.get(s, s)} for s in parlanti],
        "segmenti": segmenti, "foto": [], "relazione": None, "trascrizioneLegacy": None,
        "origine_file": str(p),
    }
    cartella = pt.INCONTRI / id_incontro
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / "sessione.json").write_text(json.dumps(sessione, ensure_ascii=False), encoding="utf-8")
    (cartella / "ricevuto.json").write_text(json.dumps({
        "ricevuto": datetime.now().strftime("%Y-%m-%d %H:%M"), "origine": "Trascrivi (computer)"},
        ensure_ascii=False), encoding="utf-8")
    return id_incontro


def invitati(sessione):
    """Invitati della riunione di calendario più vicina all'incontro: (titolo_riunione, [{nome, email}]) o (None, [])."""
    import m365
    if not m365.account():
        return None, []
    try:
        quando = datetime.fromisoformat((sessione.get("creata") or "").replace("Z", "+00:00")).astimezone()
        ev = m365.riunione_vicina(quando)
    except Exception:
        return None, []
    if not ev:
        return None, []
    return ev.get("oggetto"), ev.get("persone", [])
