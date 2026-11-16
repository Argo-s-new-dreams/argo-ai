# Componenti di terze parti

Il repository non contiene codice né modelli di terze parti, con l'eccezione del carattere Roboto (in `app/fonti/`, con la sua licenza): gli installer scaricano i pacchetti da PyPI e i modelli da Hugging Face sul computer dell'utente. Ogni componente resta soggetto alla propria licenza.

| Componente | Uso | Licenza |
| --- | --- | --- |
| [WhisperX](https://github.com/m-bain/whisperX) | Trascrizione, allineamento, orchestrazione | BSD-2-Clause |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Motore di trascrizione | MIT |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | Separazione dei parlanti e impronte vocali | MIT |
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | Modello di diarizzazione | Licenza indicata sulla pagina del modello; accesso soggetto all'accettazione delle condizioni |
| Modelli Whisper (via faster-whisper) | Trascrizione | Licenze indicate sulle rispettive pagine Hugging Face |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | Interfaccia grafica | LGPL-3.0 (o GPL-2.0/GPL-3.0) |
| [PyTorch](https://pytorch.org) | Calcolo | BSD-style |
| [FFmpeg](https://ffmpeg.org) | Decodifica audio (installato tramite winget/Homebrew) | LGPL/GPL a seconda della build |
| [uv](https://github.com/astral-sh/uv) | Ambiente Python | MIT o Apache-2.0 |
| [Roboto](https://fonts.google.com/specimen/Roboto) (incluso in `app/fonti/`) | Carattere dell'interfaccia, dal Brand Book di Argo's New Dreams | Apache-2.0 |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) (solo Windows) | Audio del computer in Registra (WASAPI loopback) | MIT |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) (solo macOS) | Audio del computer in Registra (ScreenCaptureKit) | MIT |

PySide6 viene installato come libreria separata nell'ambiente dell'utente e non è modificato né incluso in questo repository.
