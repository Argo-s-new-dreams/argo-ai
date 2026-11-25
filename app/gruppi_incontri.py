"""gruppi_incontri.py - più incontri in un gruppo, con una relazione unica (uno a molti).

Il capogruppo è l'incontro più vecchio: porta la relazione, scritta sulla somma delle trascrizioni in ordine di
tempo. Gli altri restano incontri a sé (foto, trascrizione, file), collegati al capogruppo.

Nell'incontro: argo-gruppo.json
    capogruppo: {"figli": [id, …], "creato": "AAAA-MM-GG HH:MM"}
    figlio:     {"capogruppo": id}
Il file si conserva quando il telefono rimanda lo stesso incontro (vedi ponte.importa_pacchetto).
Un capogruppo eliminato libera i figli; un figlio eliminato esce dal gruppo da solo.

Per la relazione: sessione_unita(capo) costruisce una sessione «somma» (argo.sessione) con gli incontri uno dopo
l'altro, un segnaposto «=== Incontro k di n ===» all'inizio di ciascuno, tempi in fila, parlanti distinti per
incontro e foto con il percorso relativo alla cartella del capogruppo («../<id>/foto/…»).
"""
import json
from datetime import datetime
from pathlib import Path

import ponte as pt

FILE = "argo-gruppo.json"


def _leggi(cartella):
    try:
        return json.loads((Path(cartella) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scrivi(cartella, dati):
    p = Path(cartella) / FILE
    if dati:
        p.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    elif p.exists():
        p.unlink()


def _sessione(cartella):
    try:
        return json.loads((Path(cartella) / "sessione.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def capogruppo_di(cartella):
    """Id del capogruppo se l'incontro è un figlio (e il capogruppo esiste ancora), altrimenti None."""
    capo = _leggi(cartella).get("capogruppo")
    if capo and (pt.INCONTRI / capo / "sessione.json").exists() and Path(cartella).name in _leggi(pt.INCONTRI / capo).get("figli", []):
        return capo
    return None


def figli(cartella):
    """Cartelle dei figli ancora esistenti, in ordine di tempo (vuoto se non è un capogruppo)."""
    out = []
    for i in _leggi(cartella).get("figli", []):
        c = pt.INCONTRI / str(i)
        if (c / "sessione.json").exists():
            out.append(c)
    return sorted(out, key=lambda c: _sessione(c).get("creata") or "")


def e_capogruppo(cartella):
    return bool(figli(cartella))


def membri(cartella):
    """Capogruppo + figli in ordine di tempo; [cartella] se non è un capogruppo."""
    return [Path(cartella)] + figli(cartella)


def crea(cartelle):
    """Raggruppa gli incontri scelti. Se tra questi c'è un capogruppo entrano anche i suoi figli; chi era in un
    altro gruppo ne esce. Il capogruppo è il più vecchio. Ritorna la cartella del capogruppo."""
    tutte = []
    for c in cartelle:
        for m in membri(c):
            if m not in tutte:
                tutte.append(Path(m))
    if len(tutte) < 2:
        raise ValueError("Per una relazione unica servono almeno due incontri.")
    for c in tutte:  # esce dai gruppi di prima
        separa_da_vecchi(c, tutte)
    tutte.sort(key=lambda c: _sessione(c).get("creata") or "")
    capo, resto = tutte[0], tutte[1:]
    _scrivi(capo, {"figli": [c.name for c in resto], "creato": datetime.now().strftime("%Y-%m-%d %H:%M")})
    for c in resto:
        _scrivi(c, {"capogruppo": capo.name})
    return capo


def separa_da_vecchi(cartella, nuovi):
    """Toglie l'incontro dal gruppo in cui era, se quel gruppo non è tra quelli che si stanno unendo."""
    dati = _leggi(cartella)
    if dati.get("capogruppo"):
        vecchio = pt.INCONTRI / dati["capogruppo"]
        if vecchio not in nuovi and (vecchio / FILE).exists():
            v = _leggi(vecchio)
            v["figli"] = [i for i in v.get("figli", []) if i != Path(cartella).name]
            _scrivi(vecchio, v if v["figli"] else {})
    _scrivi(cartella, {})


def separa(capo):
    """Gli incontri del gruppo tornano indipendenti; la relazione resta al capogruppo."""
    for c in figli(capo):
        _scrivi(c, {})
    _scrivi(capo, {})


def sessione_unita(capo):
    """La sessione «somma» del gruppo, per relazione, cronologia e trascrizione scaricata."""
    capo = Path(capo)
    elenco = membri(capo)
    base = _sessione(capo)
    if len(elenco) < 2:
        return base
    unita = dict(base)
    unita.update({"partecipanti": [], "segmenti": [], "foto": [], "allegati": [], "durata": 0.0,
                  "gruppo": [c.name for c in elenco]})
    unita.pop("trascrizioneLegacy", None)
    scarto = 0.0
    nomi_visti = {}
    for k, c in enumerate(elenco, 1):
        s = _sessione(c)
        prefisso = "" if c == capo else f"../{c.name}/"
        quando = (s.get("creata") or "")[:16].replace("T", " ")
        unita["segmenti"].append({"inizio": scarto, "fine": scarto, "parlante": None,
                                  "testo": f"=== Incontro {k} di {len(elenco)}: «{s.get('titolo', '')}» del {quando} ==="})
        mappa = {}
        for p in s.get("partecipanti", []):
            nome = p.get("nome") or p.get("id")
            if nome not in nomi_visti:  # la stessa persona in più incontri resta una sola
                nomi_visti[nome] = f"{k}:{p.get('id')}"
                unita["partecipanti"].append(dict(p, id=nomi_visti[nome]))
            mappa[p.get("id")] = nomi_visti[nome]
        fine = 0.0
        for seg in s.get("segmenti", []):
            fine = max(fine, float(seg.get("fine") or seg.get("inizio") or 0))
            unita["segmenti"].append(dict(seg, inizio=scarto + float(seg.get("inizio") or 0),
                                          fine=scarto + float(seg.get("fine") or 0),
                                          parlante=mappa.get(seg.get("parlante"), seg.get("parlante"))))
        if not s.get("segmenti") and s.get("trascrizioneLegacy"):
            unita["segmenti"].append({"inizio": scarto + 1, "fine": scarto + 1, "parlante": None,
                                      "testo": s["trascrizioneLegacy"]})
        for f in s.get("foto", []):
            if f.get("file"):
                unita["foto"].append(dict(f, file=prefisso + f["file"], secondo=scarto + float(f.get("secondo") or 0)))
        for a in s.get("allegati", []):
            unita["allegati"].append(dict(a, file=prefisso + a["file"] if a.get("file") else a.get("file"),
                                          secondo=scarto + float(a.get("secondo") or 0)))
        durata = max(float(s.get("durata") or 0), fine)
        scarto += durata + 1.0
        unita["durata"] += durata
    unita["segmenti"].sort(key=lambda x: x["inizio"])
    return unita
