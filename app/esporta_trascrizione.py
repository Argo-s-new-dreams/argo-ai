"""esporta_trascrizione.py - «⬇️ Scarica trascrizione» in Word (.docx) e in sottotitoli WebVTT (.vtt).

Le sorgenti:
    - Trascrivi e Registra (Live): il .json di WhisperX accanto al file _nomi.txt (tempi di inizio e fine di ogni
      frase, nomi dei parlanti come nel _nomi.txt); senza .json, il _nomi.txt (fine = inizio della frase dopo);
    - Incontri (iPhone e file): i segmenti di sessione.json, con i nomi dei partecipanti, e le foto scattate durante
      l'incontro, inserite nel punto esatto in cui sono state scattate (una frase in corso viene divisa lì).
WebVTT (W3C): una «cue» per frase, con il parlante nel tag di voce <v Nome>, così i lettori video e Teams/Stream
mostrano chi parla. Frasi molto lunghe divise in più cue (al massimo ~7 secondi o ~120 caratteri ciascuna).
Le foto: in Word come immagini con didascalia; in WebVTT, che non può contenere immagini, come blocchi NOTE.
"""
from lingua import tr
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


def foto_incontro(cartella, sessione=None):
    """Le foto dell'incontro in ordine di scatto: [{"foto": n, "inizio": secondo, "file": percorso, "testo": OCR}]."""
    cartella = Path(cartella)
    if sessione is None:
        sessione = json.loads((cartella / "sessione.json").read_text(encoding="utf-8"))
    out = []
    for n, f in enumerate(sessione.get("foto", []), 1):  # stessa numerazione della relazione («FOTO n»)
        if f.get("file"):
            out.append({"foto": n, "inizio": float(f.get("secondo") or 0), "file": str(cartella / f["file"]),
                        "testo": " · ".join(x.strip() for x in (f.get("testo") or "").splitlines() if x.strip())})
    return sorted(out, key=lambda x: x["inizio"])


def _dividi_a(seg, t):
    """Divide una frase al secondo t, in proporzione al tempo; (prima, dopo) oppure (seg, None)."""
    durata = seg["fine"] - seg["inizio"]
    parole = seg["testo"].split()
    if durata <= 0 or len(parole) < 2 or not seg["inizio"] < t < seg["fine"]:
        return seg, None
    k = round(len(parole) * (t - seg["inizio"]) / durata)
    if k <= 0 or k >= len(parole):
        return seg, None
    return (dict(seg, fine=t, testo=" ".join(parole[:k])), dict(seg, inizio=t, testo=" ".join(parole[k:])))


def con_foto(segmenti, foto):
    """Frasi e foto in ordine di tempo. Una foto scattata a metà di una frase la divide in quel punto."""
    out, foto = [], sorted(foto, key=lambda f: f["inizio"])
    j = 0
    for seg in segmenti:
        while j < len(foto) and foto[j]["inizio"] < seg["fine"]:
            if foto[j]["inizio"] <= seg["inizio"]:
                out.append(foto[j])
            else:
                prima, dopo = _dividi_a(seg, foto[j]["inizio"])
                if dopo is None:
                    break  # frase troppo corta per dividerla: la foto va subito dopo
                out += [prima, foto[j]]
                seg = dopo
            j += 1
        out.append(seg)
    out += foto[j:]
    return out


def da_incontro(cartella, con_le_foto=True):
    """Segmenti dell'incontro con chi parla; con le foto inserite nel momento in cui sono state scattate."""
    sessione = json.loads((Path(cartella) / "sessione.json").read_text(encoding="utf-8"))
    nomi = {p["id"]: p.get("nome") or p["id"] for p in sessione.get("partecipanti", [])}
    out = [{"inizio": float(s.get("inizio") or 0), "fine": float(s.get("fine") or 0),
            "chi": nomi.get(s.get("parlante"), s.get("parlante") or ""), "testo": " ".join((s.get("testo") or "").split())}
           for s in sessione.get("segmenti", []) if (s.get("testo") or "").strip()]
    out = _chiudi(out) if out else (da_testo(sessione["trascrizioneLegacy"]) if sessione.get("trascrizioneLegacy") else [])
    return con_foto(out, foto_incontro(cartella, sessione)) if con_le_foto else out


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
        if seg.get("foto"):
            nota = f"Foto {seg['foto']} scattata a {_hms(seg['inizio'])}: {Path(seg['file']).name}"
            righe += [f"NOTE {nota}" + (f"\nTesto letto: {seg['testo']}" if seg.get("testo") else "").replace("-->", "->"), ""]
            continue
        for c in _dividi(seg):
            n += 1
            testo = _voce(c["testo"])
            righe += [str(n), f"{_tempo_vtt(c['inizio'])} --> {_tempo_vtt(c['fine'])}",
                      f"<v {_voce(c['chi'])}>{testo}" if c.get("chi") else testo, ""]
    return "\n".join(righe)


def didascalia(f, massimo=160):
    testo_letto = f.get("testo") or ""
    if len(testo_letto) > massimo:
        testo_letto = testo_letto[:massimo].rsplit(" ", 1)[0] + "…"
    return f"📷 Foto {f['foto']} · {_hms(f['inizio'])}" + (f" · testo letto: {testo_letto}" if testo_letto else "")


def testo(segmenti):
    """Testo leggibile per Word: un paragrafo per intervento, come nel _nomi.txt; le foto come «![didascalia](file)»."""
    righe, ultimo = [], None
    for s in segmenti:
        if s.get("foto"):
            alt = didascalia(s).replace("[", "(").replace("]", ")")
            righe.append(f"![{alt}](<{s['file']}>)")
            ultimo = None  # dopo la foto il discorso riprende con l'orario
            continue
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
    m.addAction(tr('Word (.docx)…'), lambda: scarica(parent, sorgente, ("docx",)))
    m.addAction(tr('Sottotitoli WebVTT (.vtt)…'), lambda: scarica(parent, sorgente, ("vtt",)))
    m.addAction(tr('Word e WebVTT…'), lambda: scarica(parent, sorgente, ("docx", "vtt")))
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
        QMessageBox.information(parent, tr('Niente da scaricare'), tr('Questa trascrizione è vuota o non è ancora pronta.'))
        return []
    nome = re.sub(r'[\\/:*?"<>|]+', "_", nome).strip() or "trascrizione"
    base = Path(cartella or Path.home() / "Documents") / f"{nome}_trascrizione"
    if len(formati) == 1:
        filtro = "Documento Word (*.docx)" if formati[0] == "docx" else "Sottotitoli WebVTT (*.vtt)"
        f, _ = QFileDialog.getSaveFileName(parent, tr('Scarica la trascrizione'), str(base.with_suffix("." + formati[0])), filtro)
        if not f:
            return []
        base = Path(f).with_suffix("")
    else:
        scelta = QFileDialog.getExistingDirectory(parent, tr('Cartella per Word e WebVTT'), str(base.parent))
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
        QMessageBox.warning(parent, tr('Scarica trascrizione'), tr('Non riesco a salvare: {e}', e=e))
        return salvati
    finestra = parent.window()
    if hasattr(finestra, "statusBar"):
        finestra.statusBar().showMessage("Trascrizione salvata: " + ", ".join(Path(s).name for s in salvati), 10000)
    if len(salvati) == 1 and salvati[0].suffix == ".docx":
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(salvati[0])))
    elif salvati:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(salvati[0].parent)))
    return salvati
