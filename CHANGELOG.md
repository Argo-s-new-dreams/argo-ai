# Novità di Argo · Cassetta degli attrezzi AI

Le versioni hanno il formato `AAAAMMGG.HHMM` (ora di Roma). Il manuale completo è in [docs/MANUALE.md](docs/MANUALE.md).

## 20261114.1830: partecipanti e nomi modificabili dopo la trascrizione
- La colonna **Partecipanti** si può cambiare anche su una trascrizione completata. In quel caso Argo rifà **solo la separazione dei parlanti**: il testo resta lo stesso e ci vuole meno tempo.
- **Rimetti in coda** su una trascrizione completata chiede se rifare solo i parlanti o tutta la trascrizione.
- **✏️ Nomi dei parlanti…**, che si apre anche con un doppio clic sulla riga:
  - i nomi corretti a mano restano salvati e li ritrovi alla riapertura;
  - dare lo stesso nome a due etichette le unisce.

## 20261114.1615: video delle call
- Trascrittore, Marca voci, Dettatura e Traduzione accettano anche video: `mp4`, `mov`, `mkv`, `webm`, `m4v`, `avi`, `wmv` (Teams, Zoom, Meet…).
- **Marca voci** mostra il video sincronizzato con l'audio, così riconosci chi parla dal riquadro della call.

## 20261114.1600: creare le impronte vocali da Argo
- **🎙 Registra voce**: registrazione dal microfono con indicatore di livello, testo da leggere, riascolto e consenso obbligatorio.
- **🎧 Marca voci in un audio**:
  - forma d'onda con zoom e ascolto;
  - selezione dei tratti da assegnare a ogni persona;
  - corsia dei parlanti già trascritti, con il nome suggerito dove li riconosce;
  - creazione di più impronte in coda.

## 20261114.1520: esportazione in Word
- **Salva Word** in Verbale, Documenti riservati, Dettatura e Traduzione; **Esporta in Word** nel Trascrittore.
- I documenti escono con titoli, elenchi e tabelle, un piè di pagina e una nota di trasparenza sul testo generato da AI.

## 20261114.1510: modello scelto in automatico
- Se il modello Ollama non è scelto, o non è più installato, Argo ne sceglie uno fra quelli presenti.
- Messaggi chiari quando Ollama è spento, quando non ci sono modelli o quando manca il modello per i documenti.

## 20261114.1500: da Trascrittore ad Argo
- Nuovi attrezzi con LLM locale (Ollama):
  - **Verbale**;
  - **Documenti riservati** (RAG con citazione delle fonti);
  - **Dettatura**;
  - **Traduzione con glossario**.
- Esempi fittizi (riunione, NDA, capitolato) per provare tutto subito.
- Manuale completo in `docs/MANUALE.md`.

## 20261114.1010: Trascrittore, prima pubblicazione
- Trascrizione delle riunioni con WhisperX, separazione dei parlanti e riconoscimento tramite un'anagrafe di impronte vocali.
- Coda di lavoro, revisione dei parlanti e installer per Windows (x64 e ARM) e macOS Apple Silicon.
