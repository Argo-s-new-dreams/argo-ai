"""live_motore.py - processo di trascrizione per la modalità Live (avviato da Argo, non a mano).

Carica i modelli una volta sola (WhisperX, allineamento, separazione dei parlanti) e poi trascrive i blocchi
che riceve su stdin, uno per riga in JSON: {"blocco": "<percorso.wav>"}. Una riga vuota o {"fine": true} chiude.
Risponde su stdout con righe che iniziano con «@@ARGO » seguite da JSON (le altre righe sono log delle librerie):

    {"tipo": "stato", "msg": "..."}
    {"tipo": "pronto"}
    {"tipo": "risultato", "blocco": ..., "segmenti": [{start, end, text, speaker}], "emb": {speaker: [...]}, "secondi": ...}
    {"tipo": "errore", "blocco": ..., "msg": ...}

Il processo non cancella nulla: è Argo a cancellare il blocco dopo averne salvato il testo.
"""
import gc
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")

import voci_core as core  # noqa: E402


def manda(**kw):
    sys.stdout.write("@@ARGO " + json.dumps(kw, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    import cattura_audio as ca
    import whisperx
    from whisperx.diarize import DiarizationPipeline, assign_word_speakers

    s = core.carica_impostazioni()
    device = s.get("device", "cpu")
    lingua = s.get("language") or "it"
    modello = s.get("modello_live") or "large-v3-turbo"
    token = core.leggi_token()
    if not token:
        manda(tipo="errore", blocco="", msg="Manca il token Hugging Face: inseriscilo in Impostazioni.")
        return 2

    manda(tipo="stato", msg=f"Carico il modello di trascrizione {modello}…")
    opzioni = {"hotwords": s["hotwords"].strip()} if s.get("hotwords", "").strip() else None
    asr = whisperx.load_model(modello, device, compute_type="float16" if device == "cuda" else "int8",
                              language=lingua, asr_options=opzioni)
    manda(tipo="stato", msg="Carico il modello di allineamento delle parole…")
    try:
        allinea, meta_allinea = whisperx.load_align_model(language_code=lingua, device=device)
    except Exception as e:  # senza allineamento si lavora per frasi: meno preciso ma funziona
        allinea, meta_allinea = None, None
        manda(tipo="stato", msg=f"Allineamento non disponibile ({e}): i parlanti saranno assegnati per frase.")
    manda(tipo="stato", msg="Carico il modello dei parlanti…")
    parlanti = DiarizationPipeline(token=token, device=device)
    manda(tipo="pronto")

    for riga in sys.stdin:
        riga = riga.strip()
        if not riga:
            break
        try:
            cmd = json.loads(riga)
        except Exception:
            continue
        if cmd.get("fine"):
            break
        blocco = cmd.get("blocco", "")
        t0 = time.time()
        try:
            audio = ca.leggi_wav(blocco)
            ris = asr.transcribe(audio, batch_size=8, language=lingua)
            segmenti = ris.get("segments", [])
            if segmenti and allinea is not None:
                ris = whisperx.align(segmenti, allinea, meta_allinea, audio, device)
            emb = {}
            if ris.get("segments"):
                df, emb = parlanti(audio, return_embeddings=True)
                emb = emb or {}
                if len(df):
                    ris = assign_word_speakers(df, ris, emb)
            out = [{"start": x.get("start"), "end": x.get("end"), "text": x.get("text", ""),
                    "speaker": x.get("speaker")} for x in ris.get("segments", [])]
            manda(tipo="risultato", blocco=blocco, segmenti=out, emb=emb, secondi=round(time.time() - t0, 1))
        except Exception as e:
            manda(tipo="errore", blocco=blocco, msg=str(e))
        gc.collect()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        manda(tipo="errore", blocco="", msg=f"Il motore Live si è fermato: {e}")
        sys.exit(1)
