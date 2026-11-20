"""esporta_trascrizione.py - «⬇️ Scarica trascrizione» in Word (.docx) e in sottotitoli WebVTT (.vtt).

Le sorgenti:
    - Trascrivi e Registra (Live): il .json di WhisperX accanto al file _nomi.txt (tempi di inizio e fine di ogni
      frase, nomi dei parlanti come nel _nomi.txt); senza .json, il _nomi.txt (fine = inizio della frase dopo);
    - Incontri (iPhone e file): i segmenti di sessione.json, con i nomi dei partecipanti.
WebVTT (W3C): una «cue» per frase, con il parlante nel tag di voce <v Nome>, così i lettori video e Teams/Stream
mostrano chi parla. Frasi molto lunghe divise in più cue (al massimo ~7 secondi o ~120 caratteri ciascuna).
"""
import json
import re
from pathlib import Path

import voci_core as core

MAX_SECONDI_CUE = 7.0
MAX_CARATTERI_CUE = 120
_RIGA = re.compile(r"^\[(\d+):(\d{2})(?::(\d{2}))?\]\s*(?:([^:\n]{1,60}):\s*)?(.*)$")


# ---------------------------------------------------------------- lettura
def _secondi(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s) if s is not None else int(h) * 60 + int(m)


def _chiudi(segmenti):
    """Fine mancante o non valida: l'inizio della frase dopo (o +4 s per l'ultima)."""
    segmenti = sorted(segmenti, key=lambda s: s["inizio"])
    for i, s in enumerate(segmenti):
        dopo = segmenti[i + 1]["inizio"] if i + 1 < len(segmenti) else s["inizio"] + 4.0
        if not s.get("fine") or s["fine"] <= s["inizio"]:
            s["fine"] = max(dopo, s["inizio"] + 1.0)
    return segmenti


def da_testo(testo):
    """Da un _nomi.txt: righe «[hh:mm:ss] Nome: testo»."""
    out = []
    for blocco in re.split(r"\n\s*\n|\n(?=\[\d)", testo):
        m = _RIGA.match(blocco.strip())
        if m and m.group(5).strip():
            out.append({"inizio": float(_secondi(m.group(1), m.group(2), m.group(3))), "fine": 0.0,
                        "chi": (m.group(4) or "").strip(), "testo": " ".join(m.group(5).split())})
    return _chiudi(out)


def da_json(file_json):
    dati = json.loads(Path(file_json).read_text(encoding="utf-8"))
    try:
        mappa = core.mappa_nomi(dati)[0]
    except Exception:
        mappa = {}
    mappa.update(dati.get(core.NOMI_KEY) or {})
    out = []
    for s in dati.get("segments", []):
        testo = " ".join((s.get("text") or "").split())
        if testo:
            out.append({"inizio": float(s.get("start") or 0), "fine": float(s.get("end") or 0),
                        "chi": mappa.get(s.get("speaker"), "") if s.get("speaker") else "", "testo": testo})
    return _chiudi(out)


def da_file(percorso):
    """Da un file della coda di Trascrivi o dalla trascrizione della Live (_nomi.txt o .json)."""
    p = Path(percorso)
    candidati = [p] if p.suffix == ".json" else [p.with_name(p.stem.replace("_nomi", "") + ".json")]
    for c in candidati:
        if c.is_file():
            try:
                segmenti = da_json(c)
                if segmenti:
                    return segmenti
            except (OSError, json.JSONDecodeError, ValueError):
                pass
    nomi = p if p.suffix == ".txt" else p.with_name(p.stem + "_nomi.txt")
    return da_testo(nomi.read_text(encoding="utf-8", errors="replace")) if nomi.is_file() else []


def da_incontro(cartella):
    sessione = json.loads((Path(cartella) / "sessione.json").read_text(encoding="utf-8"))
    nomi = {p["id"]: p.get("nome") or p["id"] for p in sessione.get("partecipanti", [])}
    out = [{"inizio": float(s.get("inizio") or 0), "fine": float(s.get("fine") or 0),
            "chi": nomi.get(s.get("parlante"), s.get("parlante") or ""), "testo": " ".join((s.get("testo") or "").split())}
           for s in sessione.get("segmenti", []) if (s.get("testo") or "").strip()]
    if not out and sessione.get("trascrizioneLegacy"):
        return da_testo(sessione["trascrizioneLegacy"])
    return _chiudi(out)


# ---------------------------------------------------------------- scrittura
def _tempo_vtt(secondi):
    ms = int(round(max(0.0, secondi) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _hms(secondi):
    s = int(secondi)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _dividi(seg):
    """Una frase lunga in più cue, con il tempo diviso in proporzione ai caratteri."""
    durata = seg["fine"] - seg["inizio"]
    if durata <= MAX_SECONDI_CUE and len(seg["testo"]) <= MAX_CARATTERI_CUE:
        return [seg]
    parole, pezzi, corrente = seg["testo"].split(), [], ""
    limite = max(40, min(MAX_CARATTERI_CUE, int(len(seg["testo"]) * MAX_SECONDI_CUE / max(durata, 0.1))))
    for p in parole:
        if corrente and len(corrente) + 1 + len(p) > limite:
            pezzi.append(corrente)
            corrente = p
        else:
            corrente = f"{corrente} {p}".strip()
    if corrente:
        pezzi.append(corrente)
    totale, t, out = sum(len(x) for x in pezzi), seg["inizio"], []
    for x in pezzi:
        fine = t + durata * len(x) / totale
        out.append(dict(seg, inizio=t, fine=fine, testo=x))
        t = fine
    return out


def _voce(nome):
    return nome.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def vtt(segmenti, titolo=""):
    righe = ["WEBVTT" + (f" - {titolo}" if titolo else ""), "",
             "NOTE Trascrizione automatica realizzata con Argo · Cassetta degli attrezzi AI, in locale. "
             "Può contenere errori: rileggila prima di usarla.", ""]
    n = 0
    for seg in segmenti:
        for c in _dividi(seg):
            n += 1
            testo = _voce(c["testo"])
            righe += [str(n), f"{_tempo_vtt(c['inizio'])} --> {_tempo_vtt(c['fine'])}",
                      f"<v {_voce(c['chi'])}>{testo}" if c.get("chi") else testo, ""]
    return "\n".join(righe)


def testo(segmenti):
    """Testo leggibile per Word: un paragrafo per intervento, come nel _nomi.txt."""
    righe, ultimo = [], None
    for s in segmenti:
        if righe and s["chi"] == ultimo:
            righe[-1] += " " + s["testo"]
        else:
            righe.append(f"**[{_hms(s['inizio'])}] {s['chi']}:** {s['testo']}" if s["chi"]
                         else f"**[{_hms(s['inizio'])}]** {s['testo']}")
            ultimo = s["chi"]
    return "\n\n".join(righe)


def salva_vtt(segmenti, file, titolo=""):
    f = Path(file).with_suffix(".vtt")
    f.write_text(vtt(segmenti, titolo), encoding="utf-8")
    return f


def salva_word(segmenti, file, titolo, sottotitolo=""):
    import esporta_word as word
    return word.salva_docx(testo(segmenti), str(Path(file).with_suffix(".docx")), titolo, sottotitolo,
                           word.NOTA_TRASCRIZIONE)


# ---------------------------------------------------------------- interfaccia
def menu(parent, sorgente):
    """Menu «Word / WebVTT / entrambi». sorgente() -> (segmenti, nome base, cartella proposta, titolo) o None."""
    from PySide6.QtWidgets import QMenu
    m = QMenu(parent)
    m.addAction("Word (.docx)…", lambda: scarica(parent, sorgente, ("docx",)))
    m.addAction("Sottotitoli WebVTT (.vtt)…", lambda: scarica(parent, sorgente, ("vtt",)))
    m.addAction("Word e WebVTT…", lambda: scarica(parent, sorgente, ("docx", "vtt")))
    return m


def scarica(parent, sorgente, formati):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    dati = sorgente()
    if not dati:
        return []
    segmenti, nome, cartella, titolo = dati
    if not segmenti:
        QMessageBox.information(parent, "Niente da scaricare", "Questa trascrizione è vuota o non è ancora pronta.")
        return []
    nome = re.sub(r'[\\/:*?"<>|]+', "_", nome).strip() or "trascrizione"
    base = Path(cartella or Path.home() / "Documents") / f"{nome}_trascrizione"
    if len(formati) == 1:
        filtro = "Documento Word (*.docx)" if formati[0] == "docx" else "Sottotitoli WebVTT (*.vtt)"
        f, _ = QFileDialog.getSaveFileName(parent, "Scarica la trascrizione", str(base.with_suffix("." + formati[0])), filtro)
        if not f:
            return []
        base = Path(f).with_suffix("")
    else:
        scelta = QFileDialog.getExistingDirectory(parent, "Cartella per Word e WebVTT", str(base.parent))
        if not scelta:
            return []
        base = Path(scelta) / base.name
    salvati = []
    try:
        from datetime import date
        if "docx" in formati:
            salvati.append(salva_word(segmenti, base, titolo or f"Trascrizione: {nome}", date.today().strftime("%d/%m/%Y")))
        if "vtt" in formati:
            salvati.append(salva_vtt(segmenti, base, titolo))
    except Exception as e:
        QMessageBox.warning(parent, "Scarica trascrizione", f"Non riesco a salvare: {e}")
        return salvati
    finestra = parent.window()
    if hasattr(finestra, "statusBar"):
        finestra.statusBar().showMessage("Trascrizione salvata: " + ", ".join(Path(s).name for s in salvati), 10000)
    if len(salvati) == 1 and salvati[0].suffix == ".docx":
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(salvati[0])))
    elif salvati:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(salvati[0].parent)))
    return salvati
