"""whisperx_argo.py - WhisperX con modelli di allineamento a licenza commerciale.

WhisperX allinea le parole all'audio con un modello wav2vec2 per lingua. Per italiano, francese, tedesco e spagnolo
il suo predefinito è VoxPopuli di torchaudio, pubblicato con licenza CC BY-NC 4.0 (non commerciale): Argo si usa
per lavoro, quindi lo sostituisce con i modelli di Jonatas Grosman su Hugging Face, Apache-2.0 (verificato il
20/11/2026 sulle schede dei modelli). L'inglese resta WAV2VEC2_ASR_BASE_960H di torchaudio (MIT).

Uso:
- al posto di `python -m whisperx …`: `python whisperx_argo.py …` (stessi argomenti; lo fa voci_core);
- dentro un processo che usa WhisperX come libreria (motore Live): `whisperx_argo.applica()` prima di
  `whisperx.load_align_model`.
Vale anche con il rilevamento automatico della lingua, perché cambia la tabella dei predefiniti di WhisperX.
"""
import sys

MODELLI_ALLINEAMENTO = {
    "it": "jonatasgrosman/wav2vec2-large-xlsr-53-italian",
    "fr": "jonatasgrosman/wav2vec2-large-xlsr-53-french",
    "de": "jonatasgrosman/wav2vec2-large-xlsr-53-german",
    "es": "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
}


def applica():
    """Sostituisce nei predefiniti di WhisperX i modelli VoxPopuli (non commerciali) con quelli Apache-2.0."""
    import whisperx.alignment as allineamento
    for lingua, modello in MODELLI_ALLINEAMENTO.items():
        allineamento.DEFAULT_ALIGN_MODELS_TORCH.pop(lingua, None)
        allineamento.DEFAULT_ALIGN_MODELS_HF[lingua] = modello


if __name__ == "__main__":
    applica()
    from whisperx.__main__ import cli
    sys.argv[0] = "whisperx"
    cli()
