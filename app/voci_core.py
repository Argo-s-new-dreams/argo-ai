"""voci_core.py - motore del Trascrittore: anagrafe voci, identificazione parlanti, comandi WhisperX.

Usato dall'interfaccia grafica e da riga di comando:
  python voci_core.py iscrivi NOME file_audio
  python voci_core.py identifica trascrizione.json
  python voci_core.py elenco
  python voci_core.py esporta-iphone anagrafe.argovoci [NOME ...]
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
    "controlla_aggiornamenti": True,
    "tema": "scuro",  # scuro | chiaro | sistema
    "m365_client_id": "",  # Microsoft 365, facoltativo
    "m365_tenant_id": "",
    "m365_leggi_posta": False,  # Posta AI: lettura della posta, solo se attivata dall'utente
    "modello_live": "large-v3-turbo",  # Registra · Live: modello più veloce, per stare dietro al parlato
    "registra_microfono": "",  # Registra: nome del microfono, vuoto = predefinito del sistema
    "registra_sistema": "auto",  # Registra: audio del computer, auto | nessuna | nativo | dev:<nome>
    "registra_volume_mic": 100,  # Registra: volume in %, 0-200
    "registra_volume_sistema": 100,
    "risorse": "auto",  # Uso del computer: auto | leggero | bilanciato | massimo (vedi risorse.py)
    "riconoscimento_voci": False,  # anagrafe voci: spenta finché l'utente non la attiva (promessa di Argo)
    "cartella_registrazioni": "",  # Agenda: dove salvare le registrazioni (vuoto = ~/Documents/Argo)  # all'avvio legge da GitHub solo il numero di versione
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
        n = len(list(c.glob("*.npy"))) if c.is_dir() else 0
        if n:  # una cartella con il solo consenso (impronta non ancora calcolata) non è ancora una voce
            out.append((c.name, n))
    return out


# ---------------------------------------------------------------- riconoscimento e consenso
# Le impronte vocali che servono a riconoscere una persona possono essere dati biometrici (art. 9 GDPR).
# Per questo il riconoscimento è spento finché l'utente non lo attiva, e ogni voce si usa solo se c'è il
# consenso della persona, registrato con la data in voci/<Nome>/consenso.json.
CONSENSO = "consenso.json"


def riconoscimento_vietato():
    """True se l'IT l'ha disattivato con i criteri aziendali (chiave «riconoscimento_voci»: false)."""
    try:
        import criteri
        return criteri.carica().get("riconoscimento_voci") is False
    except Exception:
        return False


def riconoscimento_attivo():
    return bool(carica_impostazioni().get("riconoscimento_voci")) and not riconoscimento_vietato()


def imposta_riconoscimento(attivo):
    s = carica_impostazioni()
    s["riconoscimento_voci"] = bool(attivo) and not riconoscimento_vietato()
    salva_impostazioni(s)


def consenso(nome):
    """{'data': 'AAAA-MM-GG HH:MM', 'come': ...} o None."""
    try:
        return json.loads((VOCI / nome / CONSENSO).read_text(encoding="utf-8"))
    except Exception:
        return None


def registra_consenso(nome, come="confermato dall'utente"):
    from datetime import datetime
    c = VOCI / nome.strip()
    c.mkdir(parents=True, exist_ok=True)
    (c / CONSENSO).write_text(json.dumps({"data": datetime.now().strftime("%Y-%m-%d %H:%M"), "come": come},
                                         ensure_ascii=False), encoding="utf-8")


def senza_consenso():
    return [n for n, _ in elenco_voci() if consenso(n) is None]


def carica_voci(tutte=False):
    """Impronte medie delle voci usabili: solo con il riconoscimento attivo e il consenso della persona.
    tutte=True le carica comunque (solo per spostarle o unirle, mai per riconoscere)."""
    if not tutte and not riconoscimento_attivo():
        return {}
    voci = {}
    for nome, n in elenco_voci():
        if not tutte and consenso(nome) is None:
            continue
        campioni = [np.load(f) for f in (VOCI / nome).glob("*.npy")]
        if campioni:
            voci[nome] = norm(np.mean(campioni, axis=0))
    return voci


def nome_valido(nome):
    nome = nome.strip()
    return bool(nome) and not any(ch in nome for ch in '\\/:*?"<>|') and nome not in (".", "..")


def salva_impronta(nome, vettore, controlla=True):
    if not nome_valido(nome):
        raise ValueError(f"Nome non valido: {nome!r}")
    if controlla and (not riconoscimento_attivo() or consenso(nome.strip()) is None):
        raise PermissionError(f"Manca il consenso di {nome.strip()} o il riconoscimento delle voci è spento.")
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
            salva_impronta(nuovo, np.load(f), controlla=False)
        if consenso(nuovo.strip()) is None and consenso(vecchio) is not None:
            shutil.copy2(VOCI / vecchio / CONSENSO, dst / CONSENSO)
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


# ---------------------------------------------------------------- anagrafe per Argo per iPhone
FORMATO_IPHONE = "argo.voci"
ESTENSIONE_IPHONE = ".argovoci"


def esporta_per_iphone(percorso, nomi=None):
    """Scrive l'anagrafe (o le sole voci in `nomi`) nel formato letto da Argo per iPhone.

    Ogni voce porta l'impronta media normalizzata, come la usa `abbina`. Il test di compatibilità
    (argo-ios, strumenti/prova-impronte) ha mostrato che FluidAudio sull'iPhone produce impronte nello
    stesso spazio di pyannote community-1 (somiglianza 0,94 sullo stesso audio), quindi si usano così.
    Sono dati biometrici: il file va trattato come tale (AirDrop diretto, poi cancellarlo dal Mac).
    """
    from datetime import datetime, timezone

    tutte = carica_voci()
    conteggi = dict(elenco_voci())
    scelte = [n for n in sorted(tutte, key=str.lower) if nomi is None or n in nomi]
    if not scelte:
        raise ValueError("Nessuna voce da esportare.")
    dati = {
        "formato": FORMATO_IPHONE,
        "versioneFormato": 1,
        "motore": DIARIZE_MODEL,
        "creata": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "soglia": float(carica_impostazioni().get("soglia", 0.5)),
        "voci": [
            {"nome": n, "impronta": [round(float(x), 6) for x in tutte[n]], "campioni": int(conteggi.get(n, 0))}
            for n in scelte
        ],
    }
    p = Path(percorso)
    if p.suffix != ESTENSIONE_IPHONE:
        p = p.with_suffix(ESTENSIONE_IPHONE)
    p.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # solo l'utente: contiene dati biometrici
    except OSError:
        pass
    return p, len(scelte)


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
    if not riconoscimento_attivo():  # le impronte non si conservano se non servono a riconoscere
        emb = None
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


def mappa_nomi(dati, soglia=None):
    """Chi è chi in una trascrizione (senza scrivere file): impronte + nomi corretti a mano."""
    soglia = carica_impostazioni()["soglia"] if soglia is None else soglia
    emb = dati.get("speaker_embeddings") or {}
    if emb:
        mappa, migliori, coppie = abbina(emb, carica_voci(), soglia)
    else:  # trascrizione fatta senza impronte: etichette generiche
        mappa = {s: f"Parlante {i}" for i, s in enumerate(parlanti_senza_embedding(dati), 1)}
        migliori, coppie = {}, []
    for s, n in (dati.get(NOMI_KEY) or {}).items():  # nomi corretti a mano: hanno la precedenza
        if s in mappa:
            mappa[s] = n
    return mappa, migliori, coppie


def identifica(file_json, soglia=None):
    dati = leggi_json(file_json)
    mappa, migliori, coppie = mappa_nomi(dati, soglia)
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
        "--diarize",
        "--hf_token", token,
        "--output_format", "json",
        "--output_dir", str(Path(file_audio).parent),
        "--print_progress", "True",
    ]
    if device != "cuda":  # su CPU: core e memoria secondo il profilo «Uso del computer»
        import risorse
        cmd += ["--threads", str(risorse.thread_lavoro()), "--batch_size", str(risorse.batch_whisper())]
    if s.get("language"):
        cmd += ["--language", s["language"]]
    if n_parlanti and n_parlanti > 0:
        cmd += ["--min_speakers", str(n_parlanti), "--max_speakers", str(n_parlanti)]
    if s.get("hotwords", "").strip():
        cmd += ["--hotwords", s["hotwords"].strip()]
    if riconoscimento_attivo():  # impronte dei parlanti solo se servono a riconoscerli
        cmd.insert(cmd.index("--diarize") + 1, "--speaker_embeddings")
    return cmd


def json_atteso(file_audio):
    p = Path(file_audio)
    return p.parent / (p.stem + ".json")


def env_processo():
    import risorse
    env = risorse.env_limiti()  # thread delle librerie numeriche secondo il profilo «Uso del computer»
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
        elif len(a) >= 3 and a[1] == "esporta-iphone":
            p, n = esporta_per_iphone(a[2], a[3:] or None)
            print(f"OK - {n} voci esportate in {p}")
        elif len(a) == 2 and a[1] == "elenco":
            print("Voci registrate: " + (", ".join(f"{n} ({c})" for n, c in elenco_voci()) or "nessuna"))
        else:
            print(__doc__)
    except Exception as e:
        print(f"ERRORE: {e}", flush=True)
        sys.exit(1)
