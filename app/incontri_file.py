"""incontri_file.py - incontri creati sul computer: da un file audio o video, e file aggiunti a un incontro.

Un incontro creato qui ha lo stesso formato di quelli che arrivano dall'iPhone (argo.sessione, vedi ponte.py),
quindi relazione, foto con il modello vision, Dynamics ed esportazioni funzionano allo stesso modo.

    crea_da_media(file)          audio o video -> WhisperX (parole, parlanti, voci note) -> nuovo incontro
    aggiungi_file(cartella, ...) a un incontro esistente:
        immagini      -> foto/ (convertite in JPEG), descritte dal modello vision nella relazione
        audio, video  -> trascritti e messi in coda alla trascrizione (seguito dell'incontro)
        documenti     -> allegati/ con il testo estratto (PDF, Word, testo), letto dalla relazione

L'audio non resta: la copia di lavoro e il JSON di WhisperX (con le impronte vocali) si cancellano alla fine.
Il file originale dell'utente non viene toccato.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import ponte as pt
import risorse
import voci_core as core

AUDIO_VIDEO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".caf",
               ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv"}
IMMAGINI = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DOCUMENTI = {".pdf", ".docx", ".txt", ".md", ".csv"}
MAX_TESTO_ALLEGATO = 12000  # caratteri per allegato passati alla relazione
LAVORO = core.APP_HOME / "lavoro_incontri"
RE_PROGRESSO = re.compile(r"Progress:\s*([\d.]+)%")
FASI = {
    "Performing transcription": ("Trascrivo", 5, 60),
    "Performing alignment": ("Allineo le parole", 60, 80),
    "Performing diarization": ("Riconosco i parlanti", 80, 97),
}


class ErroreIncontro(RuntimeError):
    pass


def tipo_di(percorso):
    ext = Path(percorso).suffix.lower()
    if ext in AUDIO_VIDEO:
        return "audio"
    if ext in IMMAGINI:
        return "immagine"
    if ext in DOCUMENTI:
        return "documento"
    return None


def filtro_dialogo(solo_media=False):
    media = " ".join("*" + x for x in sorted(AUDIO_VIDEO))
    if solo_media:
        return f"Audio e video ({media})"
    tutti = " ".join("*" + x for x in sorted(AUDIO_VIDEO | IMMAGINI | DOCUMENTI))
    return (f"File per l'incontro ({tutti});;Immagini ({' '.join('*' + x for x in sorted(IMMAGINI))});;"
            f"Audio e video ({media});;Documenti ({' '.join('*' + x for x in sorted(DOCUMENTI))})")


# ---------------------------------------------------------------- trascrizione
def _estrai_audio(sorgente, destinazione):
    """Audio mono 16 kHz da qualsiasi audio o video (serve ffmpeg, installato con Argo)."""
    try:
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(sorgente), "-vn", "-ac", "1",
                            "-ar", "16000", str(destinazione)], capture_output=True, text=True,
                           env=core.env_processo(),
                           creationflags=(0x08000000 if os.name == "nt" else 0) | risorse.flag_windows())
    except FileNotFoundError:
        raise ErroreIncontro("ffmpeg non trovato: rilancia l'installer di Argo.") from None
    if r.returncode != 0 or not Path(destinazione).exists():
        raise ErroreIncontro("Non riesco a leggere l'audio di questo file: "
                             + (r.stderr.strip().splitlines() or ["formato non supportato"])[-1])


def trascrivi(sorgente, stato=lambda _t, _p=None: None, stop=lambda: False, n_parlanti=0):
    """Trascrive un audio/video con WhisperX + parlanti + voci note.

    Ritorna (segmenti, partecipanti, durata) nel formato argo.sessione. stato(testo, percento|None).
    """
    if not core.leggi_token():
        raise ErroreIncontro("Manca il token Hugging Face (Impostazioni › Token): serve per riconoscere i parlanti.")
    lavoro = LAVORO / uuid.uuid4().hex
    lavoro.mkdir(parents=True, exist_ok=True)
    try:
        audio = lavoro / "audio.wav"
        stato(f"Preparo l'audio di «{Path(sorgente).name}»…", 2)
        _estrai_audio(sorgente, audio)
        cmd = core.comando_whisperx(str(audio), n_parlanti, core.carica_impostazioni(), core.leggi_token())
        with risorse.turno(on_attesa=lambda t: stato(t, None)):
            if stop():
                raise ErroreIncontro("Interrotto.")
            if risorse.profilo() == "leggero":
                risorse.libera_ollama()
            _esegui_whisperx(cmd, stato, stop)
        file_json = core.json_atteso(audio)
        if not file_json.exists():
            raise ErroreIncontro("WhisperX non ha prodotto la trascrizione (guarda il registro nella pagina Trascrivi).")
        dati = core.leggi_json(file_json)
        mappa, _migliori, _coppie = core.mappa_nomi(dati)
        segmenti, visti = [], []
        for s in dati.get("segments", []):
            testo = (s.get("text") or "").strip()
            if not testo:
                continue
            chi = s.get("speaker") or ""
            if chi and chi not in visti:
                visti.append(chi)
            segmenti.append({"inizio": float(s.get("start") or 0), "fine": float(s.get("end") or 0),
                             "parlante": chi, "testo": testo})
        partecipanti = [{"id": c, "nome": mappa.get(c, c)} for c in visti]
        durata = max((s["fine"] for s in segmenti), default=0.0)
        return segmenti, partecipanti, durata
    finally:
        shutil.rmtree(lavoro, ignore_errors=True)  # audio di lavoro e impronte vocali: non restano


def _esegui_whisperx(cmd, stato, stop):
    flags = (0x08000000 if os.name == "nt" else 0) | risorse.flag_windows()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=core.env_processo(), creationflags=flags, start_new_session=(os.name != "nt"),
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    if os.name != "nt":
        risorse.abbassa_priorita(proc.pid)
    fase, ultime = None, []
    try:
        for riga in proc.stdout:
            if stop():
                proc.kill()
                raise ErroreIncontro("Interrotto.")
            riga = riga.strip()
            if not riga:
                continue
            ultime = (ultime + [riga])[-15:]
            if "%|" in riga:
                stato("Scarico i modelli di trascrizione (solo la prima volta)…", None)
                continue
            for chiave, valore in FASI.items():
                if chiave in riga:
                    fase = valore
                    stato(f"{valore[0]}…", valore[1])
            m = RE_PROGRESSO.search(riga)
            if m and fase:
                nome, ini, fine = fase
                stato(f"{nome}… {float(m.group(1)):.0f}%", ini + (fine - ini) * float(m.group(1)) / 100)
        codice = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if codice != 0:
        dettaglio = next((r for r in reversed(ultime) if "Error" in r or "error" in r), ultime[-1] if ultime else "")
        raise ErroreIncontro(f"La trascrizione non è riuscita: {dettaglio[:300]}")


# ---------------------------------------------------------------- nuovo incontro da file
def _salva_sessione(cartella, sessione):
    (Path(cartella) / "sessione.json").write_text(json.dumps(sessione, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")


def crea_da_media(sorgente, versione="", stato=lambda _t, _p=None: None, stop=lambda: False, n_parlanti=0):
    """Nuovo incontro da un file audio o video. Ritorna (cartella, sessione)."""
    sorgente = Path(sorgente)
    segmenti, partecipanti, durata = trascrivi(sorgente, stato, stop, n_parlanti)
    if not segmenti:
        raise ErroreIncontro("Nel file non ho trovato parlato da trascrivere.")
    stato("Creo l'incontro…", 99)
    id_incontro = str(uuid.uuid4())
    quando = datetime.fromtimestamp(sorgente.stat().st_mtime).astimezone()
    sessione = {
        "formato": "argo.sessione", "versioneFormato": 1,
        "app": f"Argo desktop {versione} · da file".strip(),
        "id": id_incontro, "creata": quando.isoformat(timespec="seconds"),
        "titolo": sorgente.stem, "lingua": core.carica_impostazioni().get("language") or "",
        "durata": durata, "partecipanti": partecipanti, "segmenti": segmenti, "foto": [], "allegati": [],
    }
    cartella = pt.INCONTRI / id_incontro
    (cartella / "foto").mkdir(parents=True, exist_ok=True)
    _salva_sessione(cartella, sessione)
    (cartella / "ricevuto.json").write_text(json.dumps({
        "ricevuto": datetime.now().strftime("%Y-%m-%d %H:%M"), "origine": f"file «{sorgente.name}»",
    }, ensure_ascii=False), encoding="utf-8")
    return cartella, sessione


def crea_da_trascrizione(percorso, versione="", titolo=None):
    """Nuovo incontro da una trascrizione già fatta nella pagina Trascrivi (.json di WhisperX o _nomi.txt),
    senza trascrivere di nuovo: parlanti con i nomi dati, data del file. Ritorna (cartella, sessione)."""
    import esporta_trascrizione as et
    percorso = Path(percorso)
    righe = et.da_file(percorso)
    if not righe:
        raise ErroreIncontro(f"La trascrizione «{percorso.name}» è vuota o non è ancora pronta.")
    ids, partecipanti = {}, []
    for r in righe:
        chi = r.get("chi") or "Parlante"
        if chi not in ids:
            ids[chi] = f"p{len(ids) + 1}"
            partecipanti.append({"id": ids[chi], "nome": chi})
    segmenti = [{"inizio": r["inizio"], "fine": r["fine"], "parlante": ids[r.get("chi") or "Parlante"],
                 "testo": r["testo"]} for r in righe]
    id_incontro = str(uuid.uuid4())
    quando = datetime.fromtimestamp(percorso.stat().st_mtime).astimezone()
    sessione = {
        "formato": "argo.sessione", "versioneFormato": 1,
        "app": f"Argo desktop {versione} · da Trascrivi".strip(),
        "id": id_incontro, "creata": quando.isoformat(timespec="seconds"),
        "titolo": titolo or percorso.stem.replace("_nomi", ""),
        "lingua": core.carica_impostazioni().get("language") or "",
        "durata": max((x["fine"] for x in segmenti), default=0.0),
        "partecipanti": partecipanti, "segmenti": segmenti, "foto": [], "allegati": [],
    }
    cartella = pt.INCONTRI / id_incontro
    (cartella / "foto").mkdir(parents=True, exist_ok=True)
    _salva_sessione(cartella, sessione)
    (cartella / "ricevuto.json").write_text(json.dumps({
        "ricevuto": datetime.now().strftime("%Y-%m-%d %H:%M"), "origine": f"Trascrivi «{percorso.name}»",
    }, ensure_ascii=False), encoding="utf-8")
    return cartella, sessione


# ---------------------------------------------------------------- file aggiunti a un incontro
def _nome_libero(cartella, base, ext):
    i = 1
    while (cartella / f"{base}{i:02d}{ext}").exists():
        i += 1
    return f"{base}{i:02d}{ext}"


def _immagine_in_jpeg(sorgente, destinazione, lato_massimo=2048):
    """JPEG leggero per vista e modello vision (anche da HEIC, con il lettore di immagini di Qt)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage(str(sorgente))
    if img.isNull():
        raise ErroreIncontro(f"Immagine non leggibile: {Path(sorgente).name}")
    if max(img.width(), img.height()) > lato_massimo:
        img = img.scaled(lato_massimo, lato_massimo, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if not img.save(str(destinazione), "JPG", 88):
        raise ErroreIncontro(f"Non riesco a salvare l'immagine {Path(sorgente).name}")


def _testo_documento(percorso):
    import argo_attrezzi
    pagine = argo_attrezzi.estrai_testo(percorso)
    testo = "\n".join(t for _p, t in pagine).strip()
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    return testo[:MAX_TESTO_ALLEGATO] + (" […]" if len(testo) > MAX_TESTO_ALLEGATO else "")


def _anonimo(nome):
    return nome.startswith(("Sconosciuto", "Parlante"))


def aggiungi_file(cartella, sessione, file, stato=lambda _t, _p=None: None, stop=lambda: False, secondo=None):
    """Aggiunge immagini, audio/video e documenti a un incontro. Ritorna (sessione, riepilogo, scartati).

    `secondo`: momento dell'incontro a cui legare foto e documenti (predefinito: la fine).
    Audio e video vengono trascritti e messi in coda alla trascrizione, dopo l'ultimo secondo esistente.
    """
    cartella = Path(cartella)
    sessione = dict(sessione)
    sessione.setdefault("foto", [])
    sessione.setdefault("allegati", [])
    sessione.setdefault("segmenti", [])
    sessione.setdefault("partecipanti", [])
    momento = float(sessione.get("durata") or 0) if secondo is None else float(secondo)
    conta = {"immagine": 0, "audio": 0, "documento": 0}
    scartati = []
    for i, f in enumerate(map(Path, file), 1):
        if stop():
            break
        tipo = tipo_di(f)
        if not tipo or not f.exists():
            scartati.append(f.name)
            continue
        if tipo == "immagine":
            stato(f"Aggiungo la foto {f.name}…", None)
            (cartella / "foto").mkdir(exist_ok=True)
            nome = "foto/" + _nome_libero(cartella / "foto", "pc", ".jpg")
            _immagine_in_jpeg(f, cartella / nome)
            sessione["foto"].append({"file": nome, "secondo": momento, "testo": "", "origine": f.name})
        elif tipo == "documento":
            stato(f"Leggo il documento {f.name}…", None)
            (cartella / "allegati").mkdir(exist_ok=True)
            nome = "allegati/" + _nome_libero(cartella / "allegati", "doc", f.suffix.lower())
            shutil.copy2(f, cartella / nome)
            try:
                testo = _testo_documento(cartella / nome)
            except Exception as e:
                testo = ""
                stato(f"Testo di {f.name} non leggibile ({e}): lo allego senza testo.", None)
            sessione["allegati"].append({"file": nome, "nome": f.name, "secondo": momento, "testo": testo})
        else:
            spostamento = max([float(s.get("fine", 0)) for s in sessione["segmenti"]]
                              + [float(sessione.get("durata") or 0)])
            segmenti, partecipanti, durata = trascrivi(
                f, lambda t, p=None, n=f.name: stato(f"{n}: {t}", p), stop)
            # parlanti: stesso nome = stessa persona; le etichette anonime del nuovo file restano distinte
            per_nome = {p.get("nome"): p["id"] for p in sessione["partecipanti"]}
            anonimi = sum(1 for p in sessione["partecipanti"] if _anonimo(p.get("nome", "")))
            rinomina = {}
            for p in partecipanti:
                if p["nome"] in per_nome and not _anonimo(p["nome"]):
                    rinomina[p["id"]] = per_nome[p["nome"]]
                    continue
                nome = p["nome"]
                if _anonimo(nome):  # «Sconosciuto 1» del nuovo file non è lo «Sconosciuto 1» di prima
                    anonimi += 1
                    nome = f"{nome.split()[0]} {anonimi}"
                nuovo_id = f"F{len(sessione['partecipanti']) + 1}-{p['id']}"
                rinomina[p["id"]] = nuovo_id
                sessione["partecipanti"].append({"id": nuovo_id, "nome": nome})
                per_nome.setdefault(nome, nuovo_id)
            for s in segmenti:
                sessione["segmenti"].append({**s, "inizio": s["inizio"] + spostamento, "fine": s["fine"] + spostamento,
                                             "parlante": rinomina.get(s["parlante"], s["parlante"])})
            sessione["durata"] = spostamento + durata
        conta[tipo] += 1
    _salva_sessione(cartella, sessione)
    parti = []
    if conta["immagine"]:
        parti.append(f"{conta['immagine']} foto")
    if conta["audio"]:
        parti.append(f"{conta['audio']} audio/video trascritt{'o' if conta['audio'] == 1 else 'i'}")
    if conta["documento"]:
        parti.append(f"{conta['documento']} document{'o' if conta['documento'] == 1 else 'i'}")
    return sessione, ", ".join(parti), scartati


if __name__ == "__main__":  # prova: python incontri_file.py file_audio_o_video
    cartella, s = crea_da_media(sys.argv[1], stato=lambda t, p=None: print(t, flush=True))
    print(cartella, len(s["segmenti"]), "segmenti", [p["nome"] for p in s["partecipanti"]])
