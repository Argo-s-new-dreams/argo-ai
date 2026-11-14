# Novità di Argo · Cassetta degli attrezzi AI

Le versioni hanno il formato `AAAAMMGG.HHMM` (ora di Roma). Il manuale completo è in [docs/MANUALE.md](docs/MANUALE.md).

## 20261114.2000: Microsoft 365 negli Incarichi (facoltativo)
- **Collegamento a Microsoft 365** in *Impostazioni*, con accesso tramite codice dispositivo (MSAL) e permessi delegati.
- Negli Incarichi:
  - **Dal calendario** compila titolo e partecipanti della riunione;
  - **Bozza in Outlook**, sempre con conferma e mai inviata;
  - **Task in Planner**, con scelta del piano, scadenze e assegnazione solo quando il responsabile è certo.
- Il bollino in basso indica quando Microsoft 365 è collegato.
- Nuova libreria `msal` in `requisiti.txt`: l'aggiornamento dall'app la installa se trova `uv`.

## 20261114.1945: nuova interfaccia «Studio» e Incarichi
- **Nuova grafica:**
  - menu laterale a icone;
  - tema scuro predefinito, oppure chiaro o come il sistema, da *Impostazioni → Aspetto*;
  - titoli di pagina, pulsanti principali evidenziati, stati della coda colorati.
- **Trascrittore:** pannello di dettaglio con le **corsie colorate dei parlanti** e la trascrizione con i nomi colorati; azioni a portata di clic.
- **Incarichi**, in stile Cowork, con la ricetta **Call → recap + task**:
  - trascrizione, conferma dei nomi, verbale, Word, mail di recap e task;
  - i risultati sono file nuovi nella cartella della call, con un registro dei passi;
  - nulla viene sovrascritto o inviato.
- Revisione dei nomi richiamabile anche dagli Incarichi.
- Nuovi screenshot nel README e nel manuale.

## 20261114.1930: coda più affidabile
- Corretto: dopo **Ferma coda** alcune righe *Interrotta* restavano bloccate, senza poterle rimuovere né rimettere in coda.
- **Ferma** chiude anche i processi figli di WhisperX; se dopo 3 secondi sono ancora attivi, li chiude d'autorità.
- Se premi **Avvia** mentre l'elaborazione precedente si sta ancora chiudendo, Argo chiede di attendere qualche secondo invece di mescolare i lavori.
- **Menu col tasto destro** sulle righe della coda: trascrizione, nomi, Word, verbale, Marca voci, rimetti in coda, cartella, rimuovi.
- Tasto **Canc** (o ⌫ sul Mac) per rimuovere le righe selezionate.

## 20261114.1910: aggiornamenti più robusti
- Il download dell'aggiornamento usa prima i certificati di sistema (funziona anche dietro i proxy aziendali con ispezione HTTPS), poi quelli di certifi.
- Prima versione distribuibile con l'aggiornamento automatico: chi ha la 1900 se la vede proporre all'avvio.

## 20261114.1900: aggiornamenti dall'app
- All'avvio Argo controlla su GitHub se c'è una versione nuova. Se c'è, mostra le novità e propone **Aggiorna ora**, **Più tardi** o **Apri GitHub**.
- **Aggiorna ora**:
  - scarica il pacchetto e salva la versione attuale in `app_precedente`;
  - sostituisce solo i file del programma;
  - se servono, installa le nuove librerie con `uv`;
  - propone il riavvio.
- In *Impostazioni → Aggiornamenti* trovi la versione installata, **Controlla ora** e la casella per disattivare il controllo all'avvio.
- Le librerie sono elencate in `app/requisiti.txt`, usato anche dagli installer.

## 20261114.1845: installazione su Mac senza Homebrew
- L'installer per Mac non richiede più Homebrew:
  - se Homebrew c'è, lo usa;
  - altrimenti scarica `uv` dall'installer ufficiale e prende FFmpeg dal pacchetto `imageio-ffmpeg`, dentro la cartella di Argo.
- Non servono password di amministratore.
- La versione mostrata nelle informazioni dell'app ora è quella reale.

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
