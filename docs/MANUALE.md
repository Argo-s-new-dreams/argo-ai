# Manuale di Argo · Cassetta degli attrezzi AI

*Versione del manuale: 20261114.1510 · riferita all'app versione 20261114.1510*

Argo è una cassetta degli attrezzi di intelligenza artificiale che lavora **tutta sul tuo computer**. Contiene cinque attrezzi:

- **Trascrittore**: trascrive riunioni e riconosce chi parla.
- **Verbale**: trasforma una trascrizione in un verbale.
- **Documenti riservati**: risponde a domande su documenti riservati.
- **Dettatura**: trasforma la tua voce in testo già scritto bene.
- **Traduzione**: traduce rispettando il glossario aziendale.

Audio, documenti e testi non vengono mai inviati a servizi cloud.

---

## Indice

1. [Come è fatta Argo](#1-come-è-fatta-argo)
2. [Requisiti](#2-requisiti)
3. [Installazione](#3-installazione)
4. [Primo avvio e configurazione](#4-primo-avvio-e-configurazione)
5. [Trascrittore](#5-trascrittore)
6. [Anagrafe voci](#6-anagrafe-voci)
7. [Verbale](#7-verbale)
8. [Documenti riservati](#8-documenti-riservati)
9. [Dettatura](#9-dettatura)
10. [Traduzione con glossario](#10-traduzione-con-glossario)
11. [Impostazioni nel dettaglio](#11-impostazioni-nel-dettaglio)
12. [Dove stanno i dati](#12-dove-stanno-i-dati)
13. [Uso da riga di comando](#13-uso-da-riga-di-comando)
14. [Aggiornare e disinstallare](#14-aggiornare-e-disinstallare)
15. [Risoluzione dei problemi](#15-risoluzione-dei-problemi)
16. [Privacy, GDPR e AI Act](#16-privacy-gdpr-e-ai-act)
17. [Domande frequenti](#17-domande-frequenti)

---

## 1. Come è fatta Argo

Argo usa due "motori", entrambi locali.

| Motore | Cosa fa | Usato da |
| --- | --- | --- |
| **WhisperX + pyannote** (dentro Argo) | Trascrizione parlato → testo, allineamento parola per parola, separazione dei parlanti, impronte vocali | Trascrittore, Anagrafe voci |
| **faster-whisper** (dentro Argo) | Trascrizione semplice, senza parlanti | Dettatura, Traduzione (da audio) |
| **Ollama** (programma a parte) | Modello linguistico (LLM) che scrive e ragiona sui testi, più un modello di *embedding* per cercare nei documenti | Verbale, Documenti riservati, Dettatura, Traduzione |

**Quando serve Internet:**

- per installare i pacchetti;
- per scaricare i modelli la prima volta (WhisperX/pyannote da Hugging Face, LLM da Ollama).

Dopo l'installazione il lavoro avviene offline.

La barra in basso nella finestra mostra **🔒 100% locale** finché Ollama punta a questo computer (`localhost`). Se nelle impostazioni indichi un server Ollama su un'altra macchina, il badge te lo segnala.

---

## 2. Requisiti

### Sistemi supportati

| Sistema | Supporto | Note |
| --- | --- | --- |
| Windows 10/11 x64 | Sì | GPU NVIDIA facoltativa |
| Windows 11 ARM (es. Snapdragon) | Sì | Gira in emulazione x64: più lento, consigliato `large-v3-turbo` |
| macOS Apple Silicon (M1 e successivi) | Sì | Richiede [Homebrew](https://brew.sh) |
| macOS Intel | No | PyTorch non pubblica più versioni per Mac Intel |
| Linux | Non ancora | Il codice Python è portabile, ma manca l'installer |

### Spazio e memoria

- **Disco:** circa 10 GB per Python, librerie e modelli di trascrizione. Ogni modello Ollama occupa da qualche GB in su (per esempio `gemma3:12b` circa 8 GB).
- **RAM:** per il modello linguistico conta la memoria. Con 16 GB sono adatti modelli intorno ai 12-14 miliardi di parametri. Con meno memoria scegli modelli più piccoli.

### Account

- Un account gratuito [Hugging Face](https://huggingface.co), che serve solo per scaricare il modello di separazione dei parlanti.

---

## 3. Installazione

### 3.1 Token Hugging Face (una volta sola)

1. Accedi a Hugging Face.
2. Apri la pagina del modello [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) e accetta le condizioni d'uso.
3. Vai su [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → **Create new token** → tipo **Read** → copia il token (inizia con `hf_`).

> Tratta il token come una password: non incollarlo in chat, email o documenti condivisi. Se lo esponi per errore, revocalo e creane uno nuovo.

### 3.2 Scarica Argo

Da [github.com/Argo-s-new-dreams/argo-ai](https://github.com/Argo-s-new-dreams/argo-ai): **Code → Download ZIP**, poi estrai lo ZIP in una cartella qualsiasi (per esempio *Download*).

### 3.3 Avvia l'installer

**Windows**

1. Doppio clic su `Installa-Argo.bat`.
2. Se compare SmartScreen: *Ulteriori informazioni → Esegui comunque*.
3. L'installer:
   - sblocca i file scaricati;
   - installa `uv` e `ffmpeg` con winget se mancano;
   - crea l'ambiente Python 3.12 x64 in `%USERPROFILE%\whisperx-env`;
   - installa le librerie;
   - crea il collegamento **Argo AI** sul Desktop e nel menu Start.

**macOS (Apple Silicon)**

1. Installa prima [Homebrew](https://brew.sh), se non c'è.
2. Tasto destro su `Installa-Argo.command` → **Apri**. Se macOS lo blocca: *Impostazioni di Sistema → Privacy e sicurezza → Apri comunque*.
3. L'installer:
   - installa `ffmpeg` e `uv` con Homebrew;
   - crea l'ambiente in `~/whisperx-env`;
   - installa le librerie;
   - crea l'app **Argo AI** in `~/Applications`.

Gli installer non sono firmati digitalmente, per questo i sistemi mostrano un avviso. Il codice è tutto leggibile nel repository.

> Se hai una versione precedente chiamata "Trascrittore", l'installer la sostituisce. Voci, impostazioni e coda restano dove sono.

### 3.4 Installa Ollama (per Verbale, Documenti, Dettatura, Traduzione)

1. Scarica Ollama da [ollama.com](https://ollama.com) e avvialo.
2. Scarica almeno un modello per i testi e uno per gli embedding. Per esempio, da Terminale o PowerShell:

```bash
ollama pull gemma3:12b   # testi, circa 8 GB: adatto a 16 GB di RAM
ollama pull bge-m3       # embedding multilingue per i documenti
```

I modelli si possono scaricare anche dall'app (vedi [§11.4](#114-modello-linguistico-locale-ollama)).

Senza Ollama il Trascrittore e l'Anagrafe voci funzionano lo stesso. La Dettatura in modalità *Solo trascrizione* non ha bisogno di Ollama.

---

## 4. Primo avvio e configurazione

1. Apri **Argo AI**. Al primo avvio un messaggio ti ricorda di inserire il token.
2. Scheda **Impostazioni** → incolla il token in *Hugging Face* → **Salva e verifica**. Argo controlla il token sul sito di Hugging Face e ti dice se:
   - va bene;
   - è sbagliato o scaduto;
   - non hai ancora accettato le condizioni del modello.
3. In *Trascrizione* scegli modello e lingua (per cominciare: `large-v3-turbo`, Italiano) → **Salva impostazioni**.
4. In *Modello linguistico locale* premi **Verifica e aggiorna elenco**, scegli il modello per i testi e quello per gli embedding → **Salva modelli**.

**Per una prova veloce senza materiale tuo:** la cartella `app/esempi` contiene una riunione, un NDA e un capitolato, tutti **fittizi**. I pulsanti *Usa l'esempio* ed *Esempio* li caricano.

---

## 5. Trascrittore

La scheda principale: una **coda** di file audio o video da trascrivere, con riconoscimento dei parlanti.

### 5.1 Formati accettati

Audio: `wav`, `mp3`, `m4a`, `aac`, `flac`, `ogg`, `opus`, `wma`.
Video: `mp4`, `mov`, `mkv`, `webm` (Argo ne usa solo l'audio).

### 5.2 Aggiungere file

- Trascina file o intere cartelle nella finestra, oppure usa **➕ Aggiungi file…**.
- Nella colonna **Partecipanti** indica quante persone parlano. Se il numero è giusto, la separazione delle voci migliora molto. Con `0` decide il modello.

### 5.3 Avviare e seguire il lavoro

- **▶ Avvia coda** elabora uno dopo l'altro tutti i file *In attesa*.
- La colonna **Avanzamento** mostra le tre fasi: *Trascrizione*, *Allineamento*, *Riconoscimento parlanti*.
- Stati possibili:

| Stato | Significato |
| --- | --- |
| In attesa | Pronto da elaborare |
| In corso | In lavorazione |
| Completata | Trascrizione pronta |
| Errore | Qualcosa è andato storto: guarda il log in basso |
| Interrotta | Fermata da te o dalla chiusura dell'app |

- La coda viene salvata: se chiudi Argo, la ritrovi alla riapertura.
- **Rimetti in coda** riporta in *In attesa* un file con errore o interrotto. **Rimuovi** lo toglie dalla lista senza cancellare il file.

> La prima trascrizione scarica i modelli (alcuni GB): è normale che ci metta di più.

### 5.4 Risultati

Accanto al file audio Argo salva:

- `nomefile.json`: il risultato completo di WhisperX, con le impronte vocali dei parlanti;
- `nomefile_nomi.txt`: la trascrizione leggibile, con orario e nome.

```
[00:00:12] Luca: Partiamo dal primo punto...

[00:00:41] Marco: Ok, sul budget però...
```

I parlanti non riconosciuti compaiono come **Sconosciuto 1**, **Sconosciuto 2** e così via.

Pulsanti disponibili sulla riga selezionata:

- **Apri trascrizione**: apre il file `_nomi.txt`.
- **Rivedi parlanti…**: apre la revisione (vedi sotto).
- **Apri cartella**: apre la cartella del file.
- **Crea verbale →**: passa la trascrizione alla scheda Verbale.

### 5.5 Revisione parlanti

La finestra mostra, per ogni voce trovata:

- l'etichetta del modello (`SPEAKER_00`…);
- quanto tempo ha parlato;
- la somiglianza con la voce dell'anagrafe più vicina;
- il nome assegnato.

1. Passa il mouse su un nome per leggere una frase di quel parlante e capire chi è.
2. Correggi il nome dal menu a tendina, oppure scrivine uno nuovo.
3. Spunta **Memorizza** per salvare l'impronta di quella voce nell'anagrafe: dalla volta successiva verrà riconosciuta da sola.
4. Conferma: Argo riscrive il `_nomi.txt` con i nomi corretti.

### 5.6 Consigli per una buona trascrizione

- Registra vicino a chi parla. Un microfono da riunione o le registrazioni di Teams vanno bene.
- Imposta il numero esatto di partecipanti.
- In *Parole chiave* metti termini tecnici, nomi di aziende e nomi dei partecipanti: il modello li scrive meglio.
- Le voci sovrapposte restano il punto debole di qualsiasi sistema di separazione dei parlanti.

---

## 6. Anagrafe voci

L'anagrafe contiene un'**impronta vocale** (un vettore numerico) per ogni persona. Più campioni ha una persona, più il riconoscimento è stabile: Argo ne fa la media.

### Aggiungere una voce

- **➕ Nuova voce da audio…**: scegli un file in cui parla **solo** quella persona (bastano 20-60 secondi puliti) e dai un nome. Usa solo lettere, numeri, spazi, `-` e `_`.
- **Aggiungi campione…**: aggiunge un altro audio a una voce esistente, utile se la riconosce male.
- In alternativa, il modo più comodo: trascrivi una riunione, apri **Rivedi parlanti…** e spunta **Memorizza**.

### Gestire le voci

- **Rinomina…** cambia il nome di una voce.
- **Elimina** cancella la voce e tutti i suoi campioni. Viene chiesta conferma.

### La soglia di somiglianza

In *Impostazioni → Riconoscimento voci* trovi la **Somiglianza minima** (da 0,20 a 0,95, predefinita 0,50):

- **più alta**: meno nomi sbagliati, ma più "Sconosciuto";
- **più bassa**: riconosce di più, ma rischia di scambiare persone con voci simili.

Comincia da 0,50 e regola in base a quello che vedi nella revisione: la colonna *Somiglianza* ti dice quanto erano sicuri gli abbinamenti.

> Prima di registrare la voce di qualcuno chiedi il suo consenso: vedi [§16](#16-privacy-gdpr-e-ai-act).

---

## 7. Verbale

Trasforma una trascrizione con i nomi in un testo pronto da usare. Richiede un modello per i testi in Ollama.

1. Carica la trascrizione in uno di questi modi:
   - **Apri trascrizione…** (file `.txt` o `.md`);
   - incollala nel riquadro di sinistra;
   - premi **Crea verbale →** dal Trascrittore;
   - premi **Usa l'esempio**.
2. Scegli il **Formato**:

| Formato | Risultato |
| --- | --- |
| Verbale della riunione | Markdown con *Partecipanti, Argomenti trattati, Decisioni, Azioni* (tabella Azione/Responsabile/Scadenza), *Punti aperti* |
| Mail di sintesi al cliente | Mail cordiale e professionale, massimo 250 parole circa |
| Solo elenco delle azioni | Solo la tabella delle azioni |

3. Premi **▶ Genera**: il testo compare parola per parola. Premi di nuovo il pulsante per fermare la generazione.
4. **Copia** oppure **Salva .md**. Il nome proposto è `nomefile_verbale.md`, accanto alla trascrizione.

**Come lavora:**

- Al modello viene chiesto di usare *solo* le informazioni della trascrizione e di scrivere "non indicato" quando un dato manca.
- Le riunioni lunghe vengono divise in parti: Argo estrae gli appunti da ciascuna e poi li unisce nel risultato finale.

> Un LLM può comunque sbagliare o fraintendere. **Rileggi sempre il verbale** prima di inviarlo, soprattutto nomi, date e responsabilità.

---

## 8. Documenti riservati

Fai domande su contratti, NDA e capitolati senza caricarli nel cloud. Richiede in Ollama sia il modello per i testi sia quello di embedding.

### Indicizzare

- **➕ Aggiungi…** accetta file `pdf`, `docx`, `txt` e `md`.
- Argo:
  1. estrae il testo pagina per pagina;
  2. lo divide in estratti di circa 1.200 caratteri, parzialmente sovrapposti;
  3. calcola gli embedding con il modello scelto;
  4. salva l'indice nella cartella dati.
- **Esempio** carica i due documenti fittizi. **Svuota** cancella l'indice: i file originali non vengono toccati.
- I PDF scansionati (solo immagini, senza testo selezionabile) non vengono letti: Argo non fa OCR.
- Se cambi il modello di embedding, Argo svuota l'indice e lo ricostruisce: vettori calcolati con modelli diversi non sono confrontabili.

### Chiedere

1. Scrivi la domanda (es. *"Qual è la durata dell'obbligo di riservatezza? Ci sono penali?"*) e premi **Chiedi**.
2. Argo trova i 5 estratti più pertinenti e li passa al modello.
3. Il modello risponde citando le fonti con **[1]**, **[2]**… Se i documenti non contengono la risposta, deve dirlo chiaramente.
4. Nel riquadro **Fonti usate per la risposta** vedi, per ogni citazione:
   - il nome del file e la pagina;
   - il grado di somiglianza;
   - l'inizio dell'estratto.

   Usale per controllare la risposta sul documento originale.

> Le risposte sono un aiuto alla lettura, non un parere legale.

---

## 9. Dettatura

Parli e ottieni un testo già scritto bene.

1. Scegli il **Formato**:
   - Mail professionale;
   - Mail informale;
   - Appunto ordinato;
   - Messaggio breve (Teams/WhatsApp);
   - Solo trascrizione (non serve Ollama).
2. Premi **● Registra**, parla, poi **■ Stop**. In alternativa usa **Da file audio…**.
3. A sinistra compare la trascrizione grezza, a destra il testo riscritto. Puoi correggere la trascrizione e premere **Riscrivi**, oppure cambiare formato e riscrivere.
4. **Copia risultato** e incolla dove ti serve.

**Dettagli tecnici:**

- La dettatura usa faster-whisper (modello *Trascrizione rapida*, predefinito `large-v3-turbo`) senza separazione dei parlanti ed è impostata sull'italiano.
- La registrazione temporanea viene salvata come `argo_dettatura.wav` nella cartella temporanea del sistema.
- Il modello di riscrittura ha l'istruzione di non aggiungere fatti che non hai detto.

**Microfono:**

- **macOS:** alla prima registrazione il sistema chiede il permesso. Se l'hai negato, riattivalo da *Impostazioni di Sistema → Privacy e sicurezza → Microfono*.
- **Windows:** *Impostazioni → Privacy e sicurezza → Microfono*, con l'accesso per le app desktop attivo.

---

## 10. Traduzione con glossario

Traduce testi e trascrizioni in **inglese, tedesco o italiano** imponendo al modello la terminologia aziendale.

### Tradurre

1. Inserisci il testo in uno di questi modi:
   - incollalo nel riquadro;
   - **Apri testo…** (`.txt` o `.md`);
   - **Trascrivi audio…**, che trascrive un audio in lingua rilevata automaticamente.
2. Scegli **Traduci in:** e premi **▶ Traduci**.
3. Argo cerca nel testo i termini del glossario e li passa al modello come **glossario obbligatorio**. La barra di stato mostra quanti termini ha applicato.
4. Orari, nomi e formato delle righe `[ora] Nome: testo` vengono mantenuti: puoi tradurre direttamente un `_nomi.txt`.

I testi lunghi vengono tradotti a blocchi di circa 4.000 caratteri.

### Il glossario

- La tabella ha tre colonne: **it**, **en**, **de**. Ogni riga è un termine con le sue traduzioni.
- **+ Riga** e **− Riga** aggiungono e tolgono termini. Le celle si modificano direttamente.
- **Importa CSV…** accetta file con separatore `;` o `,`. Una riga d'intestazione `it;en;de` è facoltativa e viene ignorata.
- **Salva glossario** scrive `glossario.csv` nella cartella dati. Senza salvataggio le modifiche si perdono alla chiusura.

Esempio di CSV:

```
it;en;de
offerta;quotation;Angebot
ordine di acquisto;purchase order;Bestellung
```

> Il glossario guida il modello, ma non è una garanzia assoluta. Per testi contrattuali o tecnici critici fai rivedere la traduzione da una persona.

---

## 11. Impostazioni nel dettaglio

La scheda è scorrevole: le sezioni sono quattro.

### 11.1 Hugging Face

Contiene il token, il pulsante **Mostra** e **Salva e verifica**, più i link alle due pagine necessarie (condizioni del modello e creazione del token). Il token serve solo per scaricare i modelli.

### 11.2 Trascrizione

| Voce | Opzioni | Consiglio |
| --- | --- | --- |
| Modello | `large-v3` (massima qualità, lento), `large-v3-turbo` (ottimo compromesso), `medium`, `small` | `large-v3-turbo` per l'uso quotidiano |
| Lingua | Italiano, Inglese, Tedesco, Francese, Spagnolo, Rilevamento automatico | Indica la lingua se la conosci: è più affidabile |
| Calcolo su | CPU, GPU NVIDIA (CUDA) | Scegli GPU solo se hai una scheda NVIDIA con CUDA |
| Parole chiave | Testo libero | Nomi propri, sigle, termini di settore |

### 11.3 Riconoscimento voci

**Somiglianza minima**: vedi [§6](#6-anagrafe-voci).

### 11.4 Modello linguistico locale (Ollama)

- **Indirizzo Ollama:** predefinito `http://localhost:11434`.
- **Verifica e aggiorna elenco:** legge i modelli installati in Ollama.
- **Modello per testi:** usato da Verbale, Documenti, Dettatura e Traduzione.
- **Modello per documenti:** il modello di embedding usato dalla ricerca nei documenti, ad esempio `bge-m3`.
- **Trascrizione rapida:** il modello faster-whisper usato da Dettatura e Traduzione da audio (predefinito `large-v3-turbo`).
- **Scarica un modello:** scrivi il nome di un modello (es. `bge-m3`), premi **Scarica** e Argo lo scarica tramite Ollama, mostrando l'avanzamento.
- **Salva modelli:** memorizza le scelte.

**Scelta automatica.** Se non hai ancora scelto un modello, o quello scelto non è più installato, Argo ne sceglie uno da solo fra quelli presenti in Ollama e te lo segnala. Per i testi preferisce `gemma3`, poi `qwen3`, `llama3`, `mistral`, `phi`; per i documenti preferisce `bge-m3`. Puoi sempre cambiare la scelta qui.

Se il modello "ragiona" ad alta voce (per esempio `qwen3`), Argo nasconde automaticamente le parti `<think>…</think>`.

Per salvare tutto premi **Salva impostazioni**. **Apri cartella dati** apre la cartella descritta qui sotto.

---

## 12. Dove stanno i dati

Tutto sta nella cartella `whisperx-env` dentro la tua cartella utente:

- Windows: `C:\Users\<nome>\whisperx-env`
- macOS: `/Users/<nome>/whisperx-env`

Puoi spostarla impostando la variabile d'ambiente `TRASCRITTORE_HOME`.

| Elemento | Contenuto |
| --- | --- |
| `app/` | Il programma |
| `voci/<Nome>/campione_N.npy` | Impronte vocali (dati biometrici) |
| `.hf_token` | Il token Hugging Face |
| `trascrittore_impostazioni.json` | Impostazioni |
| `trascrittore_coda.json` | La coda delle trascrizioni |
| `documenti_indice.json` + `.npy` | Indice dei Documenti riservati, con gli estratti dei testi |
| `glossario.csv` | Glossario di traduzione |

Trascrizioni e verbali vengono salvati **accanto ai file audio**, non in questa cartella. I modelli scaricati stanno nelle cache di Hugging Face e di Ollama.

**Backup:** copia `voci/`, `glossario.csv` e le impostazioni. L'indice dei documenti si può ricreare.

---

## 13. Uso da riga di comando

Il motore delle voci si può usare anche senza interfaccia. Usa il Python dell'ambiente di Argo:

- macOS: `~/whisperx-env/bin/python`
- Windows: `%USERPROFILE%\whisperx-env\Scripts\python.exe`

```bash
cd ~/whisperx-env/app

# registra una voce (campione audio di una sola persona); device facoltativo: cpu o cuda
~/whisperx-env/bin/python voci_core.py iscrivi Luca luca.wav

# elenco delle voci registrate
~/whisperx-env/bin/python voci_core.py elenco

# assegna i nomi a una trascrizione WhisperX già fatta con --diarize --speaker_embeddings
~/whisperx-env/bin/python voci_core.py identifica riunione.json
```

Per `iscrivi` il token Hugging Face deve essere già salvato (lo fa l'app).

---

## 14. Aggiornare e disinstallare

**Aggiornare:** scarica la nuova versione dal repository e rilancia l'installer. Il programma viene sostituito; voci, glossario, impostazioni e indice restano.

**Disinstallare:**

1. Elimina il collegamento **Argo AI** (Desktop e menu Start) oppure `~/Applications/Argo AI.app`.
2. Elimina la cartella `whisperx-env`. Attenzione: dentro ci sono anche le impronte vocali e il glossario, quindi fai prima un backup se ti servono.
3. Facoltativo: rimuovi i modelli da Ollama (`ollama rm <modello>`) e la cache di Hugging Face (`~/.cache/huggingface`).

---

## 15. Risoluzione dei problemi

| Sintomo | Causa probabile | Soluzione |
| --- | --- | --- |
| Errore **401** / token non valido | Token sbagliato, revocato o con spazi | Creane uno nuovo di tipo Read e premi **Salva e verifica** |
| Errore **403** / accesso negato al modello | Condizioni di pyannote non accettate | Accettale sulla pagina del modello con lo stesso account |
| "File … is not digitally signed" (Windows) | File scaricato bloccato da Windows | Usa `Installa-Argo.bat`, che sblocca i file prima di procedere |
| "Accesso negato" a `python.exe` durante l'installazione | Argo o un Python dell'ambiente è ancora aperto | Chiudi Argo e rilancia: l'installer prova comunque a fermarli |
| Download dei modelli interrotto (`IncompleteRead`) | Connessione instabile | Riavvia la coda: il download riprende |
| Avviso su **torchcodec** nel log | Innocuo: l'audio viene decodificato con ffmpeg | Nessuna azione |
| Tutti "Sconosciuto" | Anagrafe vuota o soglia troppo alta | Registra le voci; prova con soglia 0,45-0,50 |
| Persone scambiate tra loro | Soglia troppo bassa o campioni poco puliti | Alza la soglia; aggiungi campioni puliti |
| "Ollama non è acceso" | Ollama non è avviato o l'indirizzo è sbagliato | Avvia Ollama (icona del lama nella barra dei menu) e riprova |
| "Nessun modello scaricato" | Ollama è acceso ma vuoto | `ollama pull gemma3:12b` dal Terminale, oppure *Impostazioni → Scarica un modello* |
| "Manca il modello per i documenti" | Nessun modello di embedding | `ollama pull bge-m3` |
| Nessuna risposta dai Documenti | Indice vuoto o PDF scansionato | Indicizza documenti con testo selezionabile |
| Il microfono non registra | Permessi negati | Vedi [§9](#9-dettatura) |
| Trascrizione molto lenta | CPU, modello `large-v3`, PC ARM | Passa a `large-v3-turbo` o `medium`; su NVIDIA usa CUDA |
| Il Mac Intel non installa | Non supportato | Serve un Mac Apple Silicon o un PC Windows |

Se un file va in **Errore**, il log in fondo alla scheda Trascrittore riporta il messaggio: è il primo posto dove guardare, e il testo da allegare a una segnalazione su GitHub.

---

## 16. Privacy, GDPR e AI Act

- **Tutto locale.** Audio e documenti non lasciano il computer. La telemetria anonima di pyannote è disattivata dall'app.
- **Informa sempre** i partecipanti che la riunione viene registrata e trascritta.
- **Le impronte vocali sono dati biometrici** (art. 9 GDPR). Registra le voci di altre persone solo con il loro consenso esplicito e cancellale quando non servono più (**Elimina** nell'Anagrafe).
- **Documenti riservati:** l'indice contiene estratti testuali dei documenti. Proteggi il computer (cifratura del disco, account con password) come faresti con gli originali.

### AI Act (Regolamento UE 2024/1689)

Riconoscere una persona confrontando la sua voce con un'anagrafe di impronte è **identificazione biometrica** (art. 3, punto 35).

- **Uso personale e non professionale:** gli obblighi per chi usa il sistema non si applicano (art. 2, par. 10).
- **Uso professionale** (riunioni di lavoro, clienti, colleghi): il riconoscimento dei partecipanti può rientrare tra i sistemi di identificazione biometrica remota ad alto rischio (Allegato III, punto 1(a)). I relativi obblighi si applicano dal 2 dicembre 2027, dopo l'Omnibus digitale. Valutalo con il tuo consulente prima di usarlo in azienda.
- **Da non aggiungere:** l'art. 5 vieta il riconoscimento delle emozioni sul luogo di lavoro e la categorizzazione biometrica su caratteristiche sensibili.
- **L'uso meno delicato** è la sola trascrizione con parlanti anonimi ("Sconosciuto 1, 2…"), senza anagrafe.
- I testi generati da Verbale, Dettatura e Traduzione sono prodotti da un'AI. Se li pubblichi o li condividi, valuta di dichiararlo (art. 50).

Queste note sono informative e non costituiscono consulenza legale.

---

## 17. Domande frequenti

**Serve una GPU?**
No. Su CPU funziona tutto, solo più lentamente. Sul Mac i modelli di Ollama sfruttano già la GPU Apple.

**Posso usare un modello Ollama diverso da quelli suggeriti?**
Sì, qualsiasi modello installato in Ollama. Modelli più grandi scrivono meglio ma richiedono più memoria e tempo.

**Le trascrizioni restano anche se cancello la coda?**
Sì: i file `.json` e `_nomi.txt` stanno accanto agli audio. Rimuovere una riga dalla coda non cancella nulla.

**Posso riconoscere le voci in una riunione già trascritta senza rifarla?**
Sì. Dopo aver aggiunto nuove voci all'anagrafe, apri **Rivedi parlanti…** sulla trascrizione: gli abbinamenti vengono ricalcolati dal file `.json`. In alternativa usa `voci_core.py identifica` (vedi [§13](#13-uso-da-riga-di-comando)).

**Il token Hugging Face viene usato durante le trascrizioni?**
Solo per scaricare o verificare i modelli. L'audio non viene mai inviato a Hugging Face.

**È un prodotto supportato?**
No. È un progetto personale open source (licenza MIT), fornito così com'è. Segnalazioni e suggerimenti sono benvenuti nelle [issue](https://github.com/Argo-s-new-dreams/argo-ai/issues).
