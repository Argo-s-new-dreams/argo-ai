"""voci_core.py - motore del Trascrittore: anagrafe voci, identificazione parlanti, comandi WhisperX.

Usato dall'interfaccia grafica e da riga di comando:
  python voci_core.py iscrivi NOME file_audio
  python voci_core.py identifica trascrizione.json
  python voci_core.py elenco
"""
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

APP_HOME = Path(os.environ.get("TRASCRITTORE_HOME", Path.home() / "whisperx-env"))
VOCI = APP_HOME / "voci"
TOKEN_FILE = APP_HOME / ".hf_token"
SETTINGS_FILE = APP_HOME / "trascrittore_impostazioni.json"
QUEUE_FILE = APP_HOME / "trascrittore_coda.json"
DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"

DEFAULT_SETTINGS = {
    "model": "large-v3",
    "language": "it",
    "device": "cpu",
    "soglia": 0.5,
    "hotwords": "",
    # Argo · attrezzi (Ollama)
    "ollama_url": "http://localhost:11434",
    "modello_chat": "",
    "modello_embed": "",
    "modello_dettatura": "large-v3-turbo",
    "controlla_aggiornamenti": True,  # all'avvio legge da GitHub solo il numero di versione
}


# ---------------------------------------------------------------- impostazioni
def carica_impostazioni():
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def salva_impostazioni(s):
    APP_HOME.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def leggi_token():
    try:
        return TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def salva_token(token):
    APP_HOME.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip(), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def verifica_token(token):
    """Ritorna (ok, messaggio). 200 = ok, 401 = token errato, 403 = condizioni non accettate."""
    import urllib.error
    import urllib.request

    url = f"https://huggingface.co/{DIARIZE_MODEL}/resolve/main/config.yaml"
    req = urllib.request.Request(url, method="HEAD", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            codice = r.status
    except urllib.error.HTTPError as e:
        codice = e.code
    except Exception as e:  # rete assente, proxy...
        return False, f"Impossibile contattare Hugging Face: {e}"
    if codice == 200:
        return True, "Token valido e condizioni del modello accettate."
    if codice == 401:
        return False, "Token non valido (401): creane uno nuovo di tipo Read."
    if codice == 403:
        return False, "Token valido ma condizioni non accettate (403): accettale sulla pagina del modello."
    return False, f"Risposta inattesa da Hugging Face: {codice}"


# ---------------------------------------------------------------- anagrafe voci
def norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def elenco_voci():
    """Lista di (nome, numero_campioni)."""
    if not VOCI.exists():
        return []
    out = []
    for c in sorted(VOCI.iterdir(), key=lambda p: p.name.lower()):
        if c.is_dir():
            out.append((c.name, len(list(c.glob("*.npy")))))
    return out


def carica_voci():
    voci = {}
    for nome, n in elenco_voci():
        campioni = [np.load(f) for f in (VOCI / nome).glob("*.npy")]
        if campioni:
            voci[nome] = norm(np.mean(campioni, axis=0))
    return voci


def nome_valido(nome):
    nome = nome.strip()
    return bool(nome) and not any(ch in nome for ch in '\\/:*?"<>|') and nome not in (".", "..")


def salva_impronta(nome, vettore):
    if not nome_valido(nome):
        raise ValueError(f"Nome non valido: {nome!r}")
    c = VOCI / nome.strip()
    c.mkdir(parents=True, exist_ok=True)
    n = 1
    while (c / f"campione_{n}.npy").exists():
        n += 1
    np.save(c / f"campione_{n}.npy", norm(vettore))
    return n


def rinomina_voce(vecchio, nuovo):
    if not nome_valido(nuovo):
        raise ValueError(f"Nome non valido: {nuovo!r}")
    dst = VOCI / nuovo.strip()
    if dst.exists():
        # unisce i campioni nella voce esistente
        for f in (VOCI / vecchio).glob("*.npy"):
            salva_impronta(nuovo, np.load(f))
        shutil.rmtree(VOCI / vecchio)
    else:
        (VOCI / vecchio).rename(dst)


def elimina_voce(nome):
    shutil.rmtree(VOCI / nome, ignore_errors=True)


def iscrivi(nome, file_audio, device="cpu"):
    """Calcola l'impronta da un audio con una sola persona (richiede torch/pyannote)."""
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    from whisperx.diarize import DiarizationPipeline

    pipe = DiarizationPipeline(token=leggi_token(), device=device)
    _, emb = pipe(file_audio, num_speakers=1, return_embeddings=True)
    if not emb:
        raise RuntimeError("Nessuna voce trovata: usa un audio di almeno 20-30 secondi.")
    n = salva_impronta(nome, next(iter(emb.values())))
    print(f"OK - Impronta di {nome} salvata (campione n. {n}).", flush=True)


# ---------------------------------------------------------------- identificazione
def abbina(emb_parlanti, voci, soglia):
    """Ritorna (mappa SPEAKER->nome, migliori SPEAKER->(nome, somiglianza), coppie)."""
    coppie = sorted(
        ((float(np.dot(norm(v), r)), s, n) for s, v in emb_parlanti.items() for n, r in voci.items()),
        reverse=True,
    )
    mappa, usati, migliori = {}, set(), {}
    for sim, s, n in coppie:
        migliori.setdefault(s, (n, sim))
        if sim >= soglia and s not in mappa and n not in usati:
            mappa[s] = n
            usati.add(n)
    for i, s in enumerate([s for s in sorted(emb_parlanti) if s not in mappa], 1):
        mappa[s] = f"Sconosciuto {i}"
    return mappa, migliori, coppie


def hms(t):
    t = int(t or 0)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def leggi_json(file_json):
    return json.loads(Path(file_json).read_text(encoding="utf-8"))


NOMI_KEY = "argo_nomi"  # nomi assegnati a mano in revisione, salvati nel JSON della trascrizione


def salva_nomi(file_json, mappa):
    """Salva solo i nomi veri: le etichette automatiche (Sconosciuto/Parlante) restano da ricalcolare."""
    dati = leggi_json(file_json)
    dati[NOMI_KEY] = {s: n for s, n in mappa.items() if not n.startswith(("Sconosciuto", "Parlante"))}
    Path(file_json).write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")


def ridiarizza(file_json, file_audio, n_parlanti=0, device="cpu"):
    """Rifà solo la separazione dei parlanti su una trascrizione esistente (il testo resta quello).
    n_parlanti = 0: decide il modello."""
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    from whisperx.audio import load_audio
    from whisperx.diarize import DiarizationPipeline, assign_word_speakers

    dati = leggi_json(file_json)
    for seg in dati.get("segments", []):
        seg.pop("speaker", None)
        for w in seg.get("words", []) or []:
            w.pop("speaker", None)
    dati.pop("speaker_embeddings", None)
    dati.pop(NOMI_KEY, None)
    print("Ricalcolo dei parlanti" + (f" con {n_parlanti} partecipanti" if n_parlanti else " (numero automatico)"),
          flush=True)
    pipe = DiarizationPipeline(token=leggi_token(), device=device)
    kw = {"num_speakers": int(n_parlanti)} if int(n_parlanti) > 0 else {}
    df, emb = pipe(load_audio(str(file_audio)), return_embeddings=True,
                   progress_callback=lambda pct: print(f"Progress: {pct:.1f}%", flush=True), **kw)
    dati = assign_word_speakers(df, dati, emb)
    Path(file_json).write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    print(f"OK - parlanti trovati: {len(set(df['speaker'])) if len(df) else 0}", flush=True)


def parlanti_senza_embedding(dati):
    return sorted({s.get("speaker") for s in dati.get("segments", []) if s.get("speaker")})


def scrivi_trascrizione(dati, mappa, file_json):
    righe, ultimo = [], None
    for seg in dati.get("segments", []):
        chi = mappa.get(seg.get("speaker"), "Non attribuito")
        testo = (seg.get("text") or "").strip()
        if not testo:
            continue
        if righe and chi == ultimo:
            righe[-1] += " " + testo
        else:
            righe.append(f"[{hms(seg.get('start'))}] {chi}: {testo}")
            ultimo = chi
    out = Path(file_json).with_name(Path(file_json).stem + "_nomi.txt")
    out.write_text("\n\n".join(righe) + "\n", encoding="utf-8")
    return out


def identifica(file_json, soglia=None):
    soglia = carica_impostazioni()["soglia"] if soglia is None else soglia
    dati = leggi_json(file_json)
    emb = dati.get("speaker_embeddings") or {}
    if emb:
        mappa, migliori, coppie = abbina(emb, carica_voci(), soglia)
    else:  # trascrizione fatta senza impronte: etichette generiche
        mappa = {s: f"Parlante {i}" for i, s in enumerate(parlanti_senza_embedding(dati), 1)}
        migliori, coppie = {}, []
    for s, n in (dati.get(NOMI_KEY) or {}).items():  # nomi corretti a mano: hanno la precedenza
        if s in mappa:
            mappa[s] = n
    out = scrivi_trascrizione(dati, mappa, file_json)
    return out, mappa, migliori, coppie


# ---------------------------------------------------------------- comando WhisperX
def comando_whisperx(file_audio, n_parlanti, impostazioni, token):
    """Argomenti per lanciare WhisperX in un processo separato (stesso Python dell'app)."""
    s = impostazioni
    device = s.get("device", "cpu")
    cmd = [
        sys.executable, "-m", "whisperx", str(file_audio),
        "--model", s.get("model", "large-v3"),
        "--device", device,
        "--compute_type", "float16" if device == "cuda" else "int8",
        "--diarize", "--speaker_embeddings",
        "--hf_token", token,
        "--output_format", "json",
        "--output_dir", str(Path(file_audio).parent),
        "--print_progress", "True",
    ]
    if s.get("language"):
        cmd += ["--language", s["language"]]
    if n_parlanti and n_parlanti > 0:
        cmd += ["--min_speakers", str(n_parlanti), "--max_speakers", str(n_parlanti)]
    if s.get("hotwords", "").strip():
        cmd += ["--hotwords", s["hotwords"].strip()]
    return cmd


def json_atteso(file_audio):
    p = Path(file_audio)
    return p.parent / (p.stem + ".json")


def env_processo():
    env = dict(os.environ)
    env.update({
        "PYANNOTE_METRICS_ENABLED": "0",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        # avviso innocuo: l'audio arriva a pyannote gia' decodificato da ffmpeg
        "PYTHONWARNINGS": "ignore:::pyannote.audio.core.io",
    })
    return env


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    a = sys.argv
    try:
        if len(a) >= 4 and a[1] == "iscrivi":
            iscrivi(a[2], a[3], a[4] if len(a) > 4 else "cpu")
        elif len(a) == 3 and a[1] == "identifica":
            out, mappa, _, coppie = identifica(a[2])
            for sim, s, n in coppie:
                print(f"  {s} ~ {n}: {sim:.2f}")
            for s, n in sorted(mappa.items()):
                print(f"  {s} -> {n}")
            print(f"OK - Trascrizione con i nomi: {out}")
        elif len(a) >= 4 and a[1] == "ridiarizza":
            ridiarizza(a[2], a[3], int(a[4]) if len(a) > 4 else 0, a[5] if len(a) > 5 else "cpu")
        elif len(a) == 2 and a[1] == "elenco":
            print("Voci registrate: " + (", ".join(f"{n} ({c})" for n, c in elenco_voci()) or "nessuna"))
        else:
            print(__doc__)
    except Exception as e:
        print(f"ERRORE: {e}", flush=True)
        sys.exit(1)
