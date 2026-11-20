# Componenti di terze parti

*Aggiornato il 20/11/2026. Licenze verificate sulle pagine ufficiali di ogni componente. È un inventario, non un parere legale.*

Argo usa componenti di terze parti in tre modi diversi, e cambia cosa vuol dire «distribuire»:

| Come arriva sul computer | Cosa | Chi lo distribuisce |
| --- | --- | --- |
| **Nel repository** | Solo il carattere Roboto (`app/fonti/`, con la sua licenza) | Argo |
| **Nel pacchetto del Microsoft Store** (MSIX, Windows) | Python 3.12, le librerie di `app/requisiti.lock`, FFmpeg in versione LGPL | Argo, tramite lo Store |
| **Scaricato sul computer dell'utente** | Librerie da PyPI (installer), modelli da Hugging Face e da Ollama al primo uso, Ollama e FFmpeg dagli installer | Le fonti originali; Argo li scarica per conto dell'utente |

Ogni componente resta soggetto alla propria licenza.

## Programmi e librerie principali

| Componente | Uso in Argo | Licenza |
| --- | --- | --- |
| [Python](https://www.python.org) | Linguaggio di Argo; incluso nel pacchetto dello Store | [PSF License](https://docs.python.org/3/license.html) |
| [WhisperX](https://github.com/m-bain/whisperX) | Trascrizione, allineamento delle parole, orchestrazione | BSD-2-Clause |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Motore di trascrizione (anche Dettatura e Traduzione) | MIT |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | Separazione dei parlanti e impronte vocali | MIT |
| [PyTorch](https://pytorch.org) e torchaudio | Calcolo | BSD-style |
| [Transformers](https://github.com/huggingface/transformers) | Modelli di allineamento wav2vec2 | Apache-2.0 |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | Interfaccia grafica | LGPL-3.0 (o GPL-2.0/GPL-3.0). Usata come libreria separata, non modificata |
| [FFmpeg](https://ffmpeg.org) | Decodifica di audio e video | Vedi sotto |
| [Ollama](https://ollama.com) | Esegue i modelli linguistici locali; installato dagli installer di Argo dalle fonti ufficiali | MIT |
| [uv](https://github.com/astral-sh/uv) | Crea l'ambiente Python negli installer | MIT o Apache-2.0 |
| [Roboto](https://fonts.google.com/specimen/Roboto) (in `app/fonti/`) | Carattere dell'interfaccia | Apache-2.0 |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) (solo Windows) | Audio del computer in Registra (WASAPI loopback) | MIT |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) (solo macOS) | Audio del computer in Registra (ScreenCaptureKit) | MIT |

**Tutte le librerie Python**, con versione e licenza dichiarata, sono in [docs/LICENZE-LIBRERIE.md](docs/LICENZE-LIBRERIE.md). L'elenco viene generato da `strumenti/elenco_licenze.py` sull'ambiente installato da `app/requisiti.lock`, e la GitHub Action «Prova di avvio» lo produce a ogni modifica su macOS e Windows.

### FFmpeg

- **Installer per Mac e Windows**: FFmpeg non è incluso. Lo installa l'utente tramite Homebrew (Mac) o winget, pacchetto `Gyan.FFmpeg` (Windows). La licenza è quella della build scelta, LGPL o GPL.
- **Pacchetto del Microsoft Store**: include la build **LGPL shared** di [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), cioè senza le librerie solo-GPL, con le librerie `libav*` separate e collegate dinamicamente. Licenza: LGPL-2.1 o successiva. I sorgenti sono su [ffmpeg.org](https://ffmpeg.org/download.html#get-sources), e gli script di build su [github.com/BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds). Argo non modifica FFmpeg e lo usa come programma e libreria separati.

## Modelli di intelligenza artificiale

I modelli **non sono inclusi** in Argo: si scaricano sul computer al primo uso, da Hugging Face o da Ollama.

| Modello | Uso in Argo | Licenza | Note |
| --- | --- | --- | --- |
| [Whisper large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) (conversione Systran per faster-whisper) | Trascrizione | MIT | Modello originale di OpenAI, MIT |
| [Whisper large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) (conversione Mobius Labs) | Trascrizione veloce, Dettatura, Traduzione | MIT | |
| [wav2vec2 XLSR-53 italiano](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-italian), [francese](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-french), [tedesco](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-german), [spagnolo](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-spanish) (Jonatas Grosman) | Allineamento delle parole all'audio | Apache-2.0 | Scelti da Argo (`app/whisperx_argo.py`) al posto del predefinito di WhisperX per queste lingue, **VoxPopuli di torchaudio**, che è [CC BY-NC 4.0](https://pytorch.org/audio/main/generated/torchaudio.pipelines.VOXPOPULI_ASR_BASE_10K_IT.html), cioè non commerciale. Circa 1,2 GB per lingua, scaricati una volta |
| [WAV2VEC2_ASR_BASE_960H](https://pytorch.org/audio/main/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html) (torchaudio) | Allineamento in inglese | MIT | Predefinito di WhisperX |
| Rilevamento della voce di WhisperX | Trova i tratti con parlato | Incluso nel pacchetto WhisperX (BSD-2-Clause) | |
| Silero VAD (incluso in faster-whisper) | Rilevamento della voce in Dettatura e Traduzione | MIT | |
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | Separazione dei parlanti | **CC-BY-4.0** | Richiede un account Hugging Face e l'accettazione delle condizioni del modello. Attribuzione come indicato sulla scheda del modello |
| [Gemma 3](https://ai.google.dev/gemma) (`gemma3:4b`, `gemma3:12b` su Ollama) | Relazioni, verbali, documenti (consigliati) | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) e [Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) | Chi lo usa accetta questi termini, compresi gli usi vietati. «Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms» |
| [BGE-M3](https://huggingface.co/BAAI/bge-m3) (`bge-m3` su Ollama) | Ricerca nei Documenti riservati | MIT | |
| [Qwen2.5-VL 7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2.5vl:7b` su Ollama) | Lettura delle foto negli Incontri (facoltativo) | Apache-2.0 | Vale per la taglia 7B: altre taglie di Qwen2.5-VL hanno una licenza Qwen diversa |

Se scegli in Argo un altro modello di Ollama, valgono la sua licenza e i suoi termini, indicati sulla pagina del modello su [ollama.com](https://ollama.com/library).

## Servizi cloud facoltativi

Claude (Anthropic) e Ollama Cloud si usano solo se li scegli per un attrezzo, con la tua chiave, alle condizioni del fornitore (*Impostazioni › Modelli cloud › Maggiori info*). Lo stesso vale per Microsoft 365, Dynamics 365 e Ollama Web Search. Non sono componenti di Argo.
