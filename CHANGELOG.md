# Novità di Argo · Cassetta degli attrezzi AI

Le versioni hanno il formato `AAAAMMGG.HHMM` (ora di Roma). Il manuale completo è in [docs/MANUALE.md](docs/MANUALE.md).

## 20261125.2039: foto al loro posto anche nelle relazioni a schede
- Nelle relazioni a schede (Fiera, Visita cliente, Intervista…) le foto che il modello non collega a nessuna voce non finiscono più tutte in fondo: Argo le mette sotto il **contatto** o l'**azienda** di cui mostrano l'email, il cognome o il nome, altrimenti nel **tema** di cui si stava parlando quando sono state scattate (il modello ora segna il minuto in cui inizia ogni tema).
- In fondo, in *Foto dell'incontro*, restano solo le foto senza un posto chiaro. Per le relazioni già scritte premi di nuovo **✨ Scrivi relazione**.

## 20261125.2023: relazioni come documento di lavoro, con le foto dentro il testo · template «Envision · Frontier Firm»
- Nuova **forma** dei template: oltre a *Schede (sezioni)*, **Documento con figure**. Il modello scrive un documento di lavoro libero, secondo la **struttura** del template: capitoli numerati, paragrafi pieni, tabelle (schede degli agenti, architettura, roadmap, KPI) e **le foto dentro il testo**, nel punto in cui aiutano a spiegare il contesto, ognuna con la sua didascalia «Figura - …». Le foto non utili non entrano; quelle inesistenti vengono scartate.
- Nuovo template standard **Envision · Frontier Firm**: copertina, executive summary con North Star e aree prioritarie, processo attuale fase per fase, un capitolo per ogni area critica con la scheda dell'agente AI proposto, architettura concettuale, roadmap a wave con PoC, KPI per il business case, messaggio conclusivo e nota sulla fonte. Le proposte sono scritte come proposte da validare; le cifre solo come dette.
- Per gli incontri lunghi, con la forma documento gli appunti a blocchi sono più dettagliati (fasi, strumenti, tempi, volumi, problemi) e conservano cosa mostra ogni foto e a quale passaggio si riferisce.
- Dopo il documento Argo estrae comunque titolo, contatti, aziende e azioni, così *Invia a Dynamics* e *Clienti* funzionano come prima.
- In *Impostazioni › Relazioni* i template hanno due campi nuovi: **Forma** e **Struttura del documento**. Il template Envision si duplica per farne una versione propria (per esempio per altri tipi di workshop).
- Funziona anche con la **relazione unica** di più incontri: il documento tiene insieme tutti gli incontri del gruppo.

## 20261125.1512: colonna «Template» negli Incontri
- Nuova colonna **Template** accanto a *Modello*: il template con cui è stata scritta la relazione; per quelle in coda, con «→», quello che verrà usato; per quella in corso, quello al lavoro. Si aggiorna se cambi il template scelto in alto.

## 20261125.1506: colonna «Modello» negli Incontri
- Nuova colonna **Modello** nella tabella degli Incontri: il modello con cui è stata scritta la relazione (passando il mouse: anche il modello per le foto e la data).
- Per le relazioni **in coda** mostra, con «→», il modello che verrà usato con le Impostazioni di adesso (anche un modello cloud, se l'hai scelto per gli Incontri); per quella **in corso**, il modello al lavoro.

## 20261125.1320: «Con chi stai parlando?» dagli Incontri non dà più errore
- Con il Secondo cervello attivo, il tasto destro su un incontro dava «AttributeError: 'SchedaIncontri' object has no attribute 'con_chi'» e il menu non si apriva. La funzione era finita per errore nell'editor dei template (dalla 20261120.1206). Ora **🧠 Con chi stai parlando?…** funziona anche negli Incontri.

## 20261125.1235: relazione unica di più incontri o trascrizioni
- **🧩 Relazione unica**: seleziona due o più incontri (⌘ o ⇧ + clic) e, dal tasto destro, **🧩 Relazione unica di N incontri…**. Argo li unisce in un **gruppo** e scrive **una sola relazione** sulla somma delle trascrizioni, in ordine di tempo, con le foto di tutti gli incontri al loro posto.
- **Uno a molti**: il primo incontro in ordine di tempo diventa il **capogruppo** e porta la relazione; gli altri restano incontri a sé, collegati sotto. Nell'elenco il gruppo è una riga sola, **▸ Titolo · N incontri**: clic su ▸ (o tasto destro › *Mostra gli incontri del gruppo*) per vederli rientrati sotto.
- Il dettaglio del capogruppo mostra partecipanti, foto e trascrizione di tutto il gruppo; **⬇️ Scarica trascrizione** scarica la somma, con un titoletto «=== Incontro k di n ===» all'inizio di ciascuno.
- **Anche dalla pagina Trascrivi**: seleziona due o più trascrizioni completate › tasto destro › **🧩 Relazione unica di N trascrizioni…**. Diventano incontri (senza trascrivere di nuovo, con i nomi dei parlanti già dati), si raggruppano e la relazione parte negli Incontri.
- **Separa il gruppo…** (tasto destro sul capogruppo): gli incontri tornano indipendenti e la relazione unica resta al capogruppo. Il gruppo resta anche se il telefono rimanda un incontro; un incontro eliminato esce dal gruppo da solo.
- Manuale (§ Incontri) aggiornato; testi nuovi tradotti in inglese, spagnolo e tedesco.

## 20261125.1224: l'iPhone ritrova il computer anche su un'altra rete
- Il **Ponte** si annuncia in rete locale con **Bonjour** (servizio `_argoponte._tcp`, con l'id del computer): Argo per iPhone dalla 1.1.1 lo ritrova anche quando cambiano rete, indirizzo IP o porta, senza rifare l'abbinamento. Sul Mac usa `dns-sd` di sistema; su Windows serve Bonjour installato (`dns-sd.exe`), altrimenti restano indirizzi e nome `.local`.
- **Nome .local corretto**: prima poteva contenere il dominio dato dal router (per esempio `Air-di-Luca.fritz.box.local`), che cambia da una rete all'altra e non risponde. Ora sul Mac è il nome locale di sistema (`scutil --get LocalHostName`), altrove la prima parte del nome del computer.
- Il QR porta anche l'id del computer; `/v1/stato` restituisce indirizzi e porta di adesso, così l'iPhone li aggiorna a ogni sincronizzazione.
- La sicurezza non cambia: l'iPhone riconosce il computer dall'impronta del certificato e si autentica con il segreto. Non si usa il MAC, che l'iPhone non può leggere e che cambia da una rete all'altra.

## 20261125.1219: incontri rinominabili anche sul computer
- **✏️ Rinomina…** negli Incontri (tasto destro sulla riga, doppio clic sul titolo o **F2**): il titolo dell'incontro si cambia anche dall'app per Mac e Windows, non solo dal telefono.
- Il titolo nuovo vale ovunque: tabella, dettaglio, relazione (anche quelle riscritte dopo), Word, trascrizione scaricata, pagina Clienti e note per Dynamics. Resta anche se il telefono rimanda lo stesso incontro.
- Sul telefono resta il titolo di prima: il Ponte porta gli incontri dal telefono al computer, non al contrario.

## 20261125.1205: le foto dell'incontro nella trascrizione e nella relazione
- **⬇️ Scarica trascrizione** degli Incontri (Word): ogni foto è inserita **nel punto esatto in cui è stata scattata**. Se la foto è stata fatta a metà di una frase, la frase viene divisa lì e riprende dopo la foto con l'orario. Sotto la foto: numero, orario e testo letto. Prima il Word conteneva solo il testo.
- **WebVTT**: le foto diventano note (`NOTE Foto 2 scattata a 00:12:34`) nello stesso punto, perché i sottotitoli non possono contenere immagini.
- **Relazione**: le foto sono dentro il testo, accanto alla voce che riguardano. Il modello indica per ogni contatto, azienda e tema le foto collegate (il biglietto da visita sotto quel contatto, il prodotto sotto quell'azienda, la lavagna sotto quel tema) e scrive una didascalia per ogni foto. Quelle senza una voce precisa vanno in fondo, in *Foto dell'incontro*, in ordine di scatto. Vale per le relazioni scritte da questa versione: per le altre basta riscriverle.
- La relazione mostra le foto anche nella vista di Argo (ruotate come le ha scattate il telefono e ridotte alla larghezza della finestra), nel **Word** (al massimo 12 × 10 cm, con didascalia) e nel **Markdown** (con il percorso completo delle foto). Nelle note per Dynamics, nella pagina Clienti e nel Secondo cervello la relazione va senza le righe delle foto.

## 20261123.1250: Secondo cervello, prepara l'incontro con la Base
- **💡 Prepara** (nuova scheda della pagina *Secondo cervello*): scegli il tipo di azienda, le funzioni delle persone e, se vuoi, l'argomento previsto. **💡 Suggerisci** propone **domande da fare**, **temi da toccare** e **cosa è emerso in casi simili**, presi dagli incontri simili della Base. Subito e senza modello.
- **✨ Scaletta su misura**: il modello su questo computer riordina i suggerimenti in una scaletta per quell'incontro, nella lingua dell'interfaccia. Usa solo le voci della Base, già anonime, e passa dal filtro etico.
- **💡 Suggerimenti** anche nel dialogo *Con chi stai parlando?* prima di registrare: si apre accanto con azienda e funzioni già scelte e resta aperto mentre registri.
- Incontri simili: stesso settore (conta di più), dimensione, tipo di attività e area dell'azienda; stessa area e livello delle funzioni; con l'argomento e il modello per i Documenti anche la somiglianza del testo. Nulla esce dal computer.
- Manuale §5quinquies aggiornato (*Prepara l'incontro*); testi nuovi tradotti in inglese, spagnolo e tedesco. I suggerimenti durante la Live arrivano in una prossima versione.

## 20261122.1237: Impostazioni tradotte anche nelle categorie
- Con l'interfaccia in inglese, tedesco o spagnolo, le categorie delle Impostazioni (*Trascrizione e voci*, *Modelli AI*, *Relazioni*, *Collegamenti*, *Backup e più computer*, *Supporto*) e le loro descrizioni restavano in italiano. Ora seguono la lingua scelta.

## 20261122.1114: Ollama spento anche uscendo con ⌘Q o dal Dock
- Lo spegnimento di Ollama alla chiusura vale per ogni modo di uscire: pulsante di chiusura della finestra (o Alt+F4), sul Mac anche ⌘Q, *Argo › Esci*, *Esci* dal Dock e spegnimento del computer. Una volta sola.
- Quando Argo si riavvia da solo dopo un aggiornamento, Ollama resta acceso per la nuova finestra.

## 20261122.1107: Ollama acceso all'avvio e spento alla chiusura, a scelta
- **Alla chiusura di Argo** (Impostazioni › Modelli AI): *Fermalo solo se l'ha avviato Argo* (predefinito), *Fermalo sempre* oppure *Lascialo acceso: lo usano anche altri programmi*. Prima Argo accendeva Ollama ma non lo spegneva mai, e la memoria restava occupata anche dopo la chiusura.
- Argo **si ricorda di aver acceso Ollama** anche dopo un riavvio per aggiornamento, ma non dopo un riavvio del computer: così non spegne un Ollama partito con il sistema o acceso da un altro programma.
- Con Ollama **condiviso con altri programmi**, prima di una trascrizione pesante Argo libera la memoria solo dei propri modelli.
- **Verifica e aggiorna elenco** accende Ollama se è spento, invece di dire solo di avviarlo.
- Spegnimento: Mac con l'uscita dall'app Ollama e la chiusura di `ollama serve`; Windows con la chiusura dell'icona di Ollama e del server. Mai un Ollama su un altro computer.
- Manuale §11.4 aggiornato; testi nuovi tradotti in inglese, spagnolo e tedesco.

## 20261122.0832: Argo in italiano, inglese, spagnolo e tedesco
- **Lingua dell'interfaccia** in Impostazioni › Aspetto e aggiornamenti › *Lingua*: Come il sistema, Italiano, English, Español, Deutsch. Vale dal prossimo avvio: Argo propone di riavviarsi subito. Con il sistema in un'altra lingua Argo resta in italiano.
- **Tradotti tutti i 953 testi delle schermate**: menu laterale, pagine, pulsanti, finestre di conferma, avvisi e barra in basso. Anche i pulsanti standard di Qt (OK, Annulla, Sì, No) seguono la lingua scelta.
- La lingua dell'interfaccia è **separata** da quella delle trascrizioni e delle relazioni, che non cambiano.
- Per gli sviluppatori: ogni testo passa da `tr("testo in italiano", campo=valore)` (`app/lingua.py`), le traduzioni sono in `app/traduzioni/en.json`, `es.json`, `de.json`. `strumenti/controlla_traduzioni.py` conta i testi tradotti e controlla i segnaposto; la GitHub Action *Prova di avvio* si ferma se manca una traduzione. `strumenti/avvolgi_testi.py` aiuta a passare a `tr()` i testi di un file nuovo.
- **Da rileggere**: le traduzioni sono una prima versione. Restano in italiano, per ora, i messaggi che arrivano dai moduli senza interfaccia (alcuni errori di Ollama, Dynamics e aggiornamenti), le etichette dei canali e dell'uso del computer, il manuale e le istruzioni ai modelli.

## 20261120.2033: scarica la trascrizione in Word e in WebVTT
- **⬇️ Scarica trascrizione**: **Word (.docx)**, **sottotitoli WebVTT (.vtt)** oppure **entrambi**. Si trova in *Trascrivi* (pulsante nel dettaglio e tasto destro, al posto di «Esporta in Word»), in *Registra* dopo una Live e negli *Incontri* (*Salva ▾*, dove le voci della relazione ora si chiamano «Relazione in…», e tasto destro).
- **WebVTT** standard W3C: una riga per frase con inizio e fine presi da WhisperX (al millesimo), il parlante nel tag di voce `<v Nome>`, le frasi lunghe divise. Senza il `.json` i tempi si ricavano dal `_nomi.txt`.
- **Word**: un paragrafo per intervento, con orario e parlante in grassetto, e la nota «trascrizione automatica».
- Manuale §4 e §5.4 aggiornati.

## 20261120.1854: backup, ripristino e configurazione condivisa tra più computer
- **Backup su richiesta, alla chiusura e programmati** (Impostazioni › 💾 Backup e più computer), in due livelli: *Configurazione* (impostazioni, template, glossario) e *Completo* (anche voci, incontri, clienti, Secondo cervello, indice dei Documenti). Di base, a ogni chiusura, un backup della configurazione in Documenti › Argo › Backup; si conservano gli ultimi 10 per livello.
- **OneDrive e Google Drive** tramite le loro cartelle sincronizzate (app OneDrive e Google Drive per desktop), trovate da sole su Mac e Windows: nessun accesso nuovo. Ogni scrittura nel cloud compare in «Cosa è uscito da questo computer» e nella barra in basso.
- **Chiavi e token cifrati nel backup** con una password scelta da te (AES-256-GCM, chiave da scrypt): la password non si salva, su un altro computer serve per ripristinarli. Senza password restano fuori.
- **Ripristino** dall'elenco dei backup (anche di altri computer e dalle cartelle cloud) o da un file, sempre preceduto da un backup di sicurezza; da un altro computer arrivano solo le impostazioni comuni; poi Argo si riavvia.
- **Configurazione condivisa tra Mac e Windows**: con la stessa cartella cloud, Argo la legge all'avvio e scrive la propria alla chiusura; modelli, Ollama, audio, prestazioni e cartelle restano di ogni computer. In caso di modifiche su due computer vince la più recente, l'altra resta in un backup.
- **Nuovi criteri IT**: `backup_nel_cloud` e `condivisione_configurazione`.
- Tolte due schermate di prova finite per errore nella versione precedente.
- Manuale §11.7 e PRO.md aggiornati.

## 20261120.1848: «Adatta a questo computer» e Secondo cervello nella barra in basso
- **🖥️ Adatta a questo computer…** (Impostazioni › Trascrizione): Argo legge sistema, processore, core, RAM e GPU NVIDIA e propone i cambi utili, con il motivo di ciascuno: uso del computer, calcolo su CPU o GPU, modello di trascrizione (large-v3-turbo sui computer leggeri) e modelli di Ollama per testi, foto e documenti (i migliori installati che stanno nella RAM, oppure il download di quello consigliato). Applichi solo quelli che lasci spuntati.
- **🧠 Secondo cervello attivo · N voci nella Base** nella barra in basso, accanto a «🔒 100% locale», quando è acceso; un clic apre la pagina.
- Manuale §5quinquies e §11 aggiornati.

## 20261120.1419: modelli adatti al computer su cui gira Argo
- **Argo legge la RAM** e capisce quali modelli di Ollama ci stanno (fino a tre quarti della RAM: con 8 GB `gemma3:4b` sì, `gemma3:12b` no; con 16 GB entrambi).
- **All'avvio, se il modello scelto per i testi o per le foto è troppo grande**, Argo passa da solo al migliore installato che ci sta e lo scrive in basso nella finestra (e nel registro tecnico). Se nessuno ci sta, propone di scaricare `gemma3:4b` spiegando perché, anche a chi aveva risposto «Non ora» ai modelli consigliati.
- Nelle tendine dei modelli (Impostazioni e Foto degli Incontri) i modelli troppo grandi hanno «⚠️ troppo grande per questo computer».
- Manuale §11.4 aggiornato.

## 20261120.1411: errori di Ollama più chiari
- **Ollama lento non è Ollama spento**: un tempo scaduto (Ollama acceso ma occupato a caricare un modello, o senza memoria) ora dice proprio questo, invece di «Ollama non raggiungibile… È avviato?». Se il modello scelto è troppo grande per la RAM del computer, il messaggio lo dice con le dimensioni e propone un modello più piccolo. Ollama davvero spento ha un messaggio a parte, con come avviarlo.
- Elenco e dettagli dei modelli aspettano fino a 30 secondi (prima 10) e l'elenco riprova una volta: su un Mac occupato a caricare un modello grande 10 secondi non bastavano, e la relazione falliva subito.
- Manuale §15: nuova riga nei problemi frequenti.

## 20261120.1230: Secondo cervello, secondo blocco · Distilla e Base anonima
- **✨ Distilla** (scheda *Incontri* della pagina Secondo cervello, anche **Distilla i nuovi**): il modello **locale** estrae da trascrizioni e relazioni solo fatti di lavoro: sintesi, temi, esigenze, problemi, come lavorano oggi, decisioni, domande che hanno funzionato, punti aperti. Testi lunghi a pezzi, poi uniti.
- **Anonimizzazione irreversibile in tre passi**: nomi noti tolti prima che il modello legga (aziende del catalogo e loro parole distintive, siti, parlanti, partecipanti, voci; mail, telefoni, partite IVA), categorie al posto dei nomi nel testo del modello, controllo finale dei nomi rimasti. Software e tecnologie restano.
- **Base**: ogni voce ha solo mese, categorie dell'azienda, funzioni e contenuti, senza alcun collegamento all'incontro. Si legge, si modifica (con nuovo controllo) e si elimina. Embedding con il modello dei Documenti, se c'è, per i suggerimenti del prossimo blocco.
- Manuale §5quinquies e §12 aggiornati.

## 20261120.1206: Secondo cervello, primo blocco · «Con chi stai parlando?»
- **Nuova pagina Secondo cervello**, facoltativa e **spenta di base**, con la spiegazione del metodo CODE. È la parte «Organizza»: la base anonimizzata e i suggerimenti arrivano nei prossimi blocchi.
- **«Con chi stai parlando?»**: con il Secondo cervello attivo, prima di ogni registrazione Argo chiede l'azienda e le persone **per funzione** (ruolo, area, livello: mai nomi). Si può saltare. Per gli incontri dall'iPhone e i file in *Trascrivi* c'è la voce **🧠 Con chi stai parlando?…** nel menu del tasto destro. La scheda segue la registrazione quando diventa trascrizione.
- **Catalogo aziende** (settore, dimensione, tipo di attività, area geografica, note) e **catalogo funzioni**, con modifica ed eliminazione. **🔎 Cataloga dal web** propone le categorie dalla scheda pubblica di *Clienti* o dalla ricerca web; le note passano dal filtro etico. Sulle persone nessuna ricerca.
- **Nuovo criterio IT**: `"secondo_cervello": false` lo vieta.
- Dati in `whisperx-env/secondo_cervello/`, solo su questo computer. Manuale §5quinquies, §12 e §16 e PRO.md aggiornati.

## 20261120.1152: il computer resta sveglio mentre Argo lavora
- **Niente sospensione automatica durante i lavori**: mentre Argo trascrive, registra o finisce la Live, scrive una relazione, crea un incontro da file o usa il modello linguistico, il computer non va in sospensione per inattività (Mac: `caffeinate`; Windows: `SetThreadExecutionState`). Lo schermo può spegnersi lo stesso; finito il lavoro, tutto torna come prima. Se Argo si chiude o si blocca, il blocco si toglie da solo.
- **Sospensione lo stesso** (coperchio chiuso, tasto di accensione): Argo se ne accorge. Una trascrizione fallita per questo torna **In attesa** e riparte da capo una volta; se ricapita, la nota spiega cosa è successo. Negli incontri da file l'errore dice che il computer è andato in sospensione. Nel registro tecnico: «il computer è stato in sospensione per circa N min».
- La prova di avvio automatica controlla anche il blocco della sospensione su macOS e Windows.
- Manuale §5.3 e §15 aggiornati.

## 20261120.1139: licenze verificate e allineamento con licenza commerciale
- **Allineamento delle parole**: per italiano, francese, tedesco e spagnolo WhisperX usava di base i modelli **VoxPopuli** di torchaudio, con licenza **CC BY-NC 4.0 (non commerciale)**: non adatti a un uso di lavoro. Argo ora usa i modelli wav2vec2 XLSR-53 di Jonatas Grosman, **Apache-2.0** (`app/whisperx_argo.py`), sia nel Trascrittore sia nel Live, anche con il rilevamento automatico della lingua. L'inglese resta il modello di torchaudio, MIT. La prima trascrizione dopo l'aggiornamento scarica il nuovo modello, circa 1,2 GB per lingua, una volta sola.
- **THIRD_PARTY_LICENSES.md riscritto**: cosa è incluso e cosa si scarica; Python (PSF), FFmpeg (installer e build LGPL del pacchetto Store, con i link ai sorgenti), Ollama, tutti i modelli con licenza e note (pyannote community-1 CC-BY-4.0, Gemma Terms of Use, BGE-M3 MIT, Qwen2.5-VL 7B Apache-2.0, Whisper MIT).
- **Elenco delle licenze di tutte le librerie Python** (`strumenti/elenco_licenze.py`), prodotto dalla GitHub Action «Prova di avvio» su macOS e Windows; la stessa Action controlla ora i modelli di allineamento sul WhisperX vero.
- Manuale §1 aggiornato.

## 20261120.1111: filtro etico e prova automatica di avvio su Mac e Windows
- **Filtro etico** su relazioni degli incontri, verbali (anche quelli da Agenda), mail di recap, riassunti e risposte della posta, schede dei clienti: solo fatti utili al lavoro. Niente questioni personali o private, giudizi sulle persone, pettegolezzi, parolacce, bestemmie, insulti o espressioni discriminatorie, anche se sono nella conversazione. Le regole arrivano al modello; in più un controllo finale toglie le parolacce più comuni rimaste («[…]») senza toccare parole normali come «cazzuola» o «Troia» (la città). Traduzioni e dettatura restano fedeli. Primo pezzo del «Secondo cervello».
- **Prova di avvio automatica** (GitHub Action «Prova di avvio») a ogni modifica dell'app:
  - controllo del codice con ruff sugli errori gravi: avrebbe fermato il problema del 18/11 (QTimer usato prima di essere assegnato);
  - avvio vero su **macOS** e **Windows** con le librerie di `requisiti.lock`: Argo deve arrivare alla finestra e chiudersi senza errori. Si lancia anche a mano: `python strumenti/prova_avvio.py`.
- In modalità di prova (`ARGO_PROVA_AVVIO`) gli errori finiscono nel registro invece di aprire una finestra da cliccare.

## 20261119.1720: la promessa, alla lettera
- **Riconoscimento delle voci spento per tutti** finché non lo attivi (*Voci › Attiva il riconoscimento…* o *Impostazioni › Trascrizione e voci*). Da spento: parlanti «Parlante 1, 2…», nessuna impronta calcolata o conservata (WhisperX gira senza `--speaker_embeddings`), Live senza anagrafe, niente voci per l'iPhone.
- **Consenso per ogni voce**, salvato con la data in `voci/<Nome>/consenso.json` e mostrato nella nuova colonna **Consenso**. Le voci salvate prima restano ma non si usano finché non confermi il consenso (all'attivazione o con **Conferma consenso…**). Senza consenso nessuna impronta viene salvata, nemmeno dalla Revisione.
- **Cosa è uscito da questo computer**: ogni uscita compare in basso («☁️ Uscito ora: … → …») e resta in un elenco in *Impostazioni › 🛟 Supporto*: modelli cloud, Ollama su un altro computer, ricerca web, bozze e task in Microsoft 365, record e ricerche in Dynamics. Solo destinazione e tipo di dato, mai il contenuto.
- **Nuovi criteri IT**: `"riconoscimento_voci": false` e `"ricerca_web": false`.
- **Ponte**: con il riconoscimento spento dice all'iPhone che non deve più usare le voci (l'app iPhone le elimina dalla 0.6.4).
- *Registra* partiva già in Live, con Archivia come scelta esplicita: invariato.
- Manuale (§6, §11.3, §11.6, §16) e PRO.md aggiornati.

## 20261119.1658: «Chiedi supporto» allega davvero il pacchetto
- Prima la mail si apriva con un link `mailto:`, che **non può portare allegati**: il pacchetto andava trascinato a mano. Ora nel passo 2 c'è **Invia con**:
  - **Outlook · Microsoft 365** (se è collegato): bozza nella cartella *Bozze* con il pacchetto allegato, aperta in Outlook sul web. Usa il permesso `Mail.ReadWrite` che Argo ha già; sopra i 3 MB carica l'allegato a pezzi, come indica Microsoft Graph.
  - **Mail di macOS**: mail con l'allegato via AppleScript. La prima volta macOS chiede il permesso ad Argo di controllare Mail.
  - **Outlook classico** su Windows: mail con l'allegato via COM. Il nuovo Outlook non lo permette.
  - **Altro programma di posta**: come prima, senza allegato.
- Argo non invia mai da solo. Se il modo scelto non riesce, lo dice e ripiega sull'ultimo.
- Manuale §11.6 aggiornato.

## 20261119.1648: registro locale, modalità trace, avvio protetto e «Chiedi supporto»
- **Registro di Argo** in `whisperx-env/log/` (5 file da 2 MB a rotazione): avvio, versione, canale, sistema, CPU, RAM, fasi dei lavori con durata ed esito, errori con traccia, tempi di Ollama e dei modelli cloud (solo fornitore e modello), aggiornamenti. **Mai contenuti**: niente audio, trascrizioni, prompt e risposte, nomi dei file e dei parlanti. Un filtro toglie anche mail, telefoni, chiavi, token e percorsi della cartella utente. Nessuna telemetria: il registro esce solo se lo mandi tu.
- **Errori non gestiti** (anche nei thread e prima della finestra) finiscono nel registro e aprono una finestra con **🛟 Chiedi supporto** e, all'avvio, **Torna alla versione …**. Un errore come quello della 20261118.1957 oggi si vede subito.
- **Avvio protetto**: dopo due avvii di fila che non arrivano alla finestra, Argo propone la **modalità sicura** (senza Ponte, Live, aggiornamenti automatici e avvio di Ollama), il ritorno alla versione precedente o l'avvio normale. Anche con `--sicura`.
- **Torna alla versione precedente** da *Impostazioni › 🛟 Supporto*: rimette `app_precedente` (salvata a ogni aggiornamento dall'app), tiene da parte quella attuale in `app_scartata` e riapre Argo.
- **Modalità trace**: per 24 ore o fino al riavvio, con una banda in alto e **Spegni**; righe tecniche di WhisperX e del Live, richieste HTTP con tempi e codici, passi delle relazioni. Anche con `--trace` o con il nuovo criterio IT `"trace": true`.
- **🛟 Chiedi supporto**: richiesta in tre domande più l'urgenza, codice `ARGO-AAAAMMGG-XXXX`, pacchetto zip sulla Scrivania che si vede file per file prima di crearlo, mail precompilata per supporto@argo-net.it. Nessun server: il file si allega a mano.
- Nuovo argomento *Impostazioni › 🛟 Supporto*. Manuale (§11.6, §12, §13, §15), PRO.md e README aggiornati.

## 20261119.1626: l'installer installa anche Ollama
- **Nuovo ultimo passo [6/6]** negli installer: chiede «Installo Ollama adesso? [S/n]» e, se c'è già, lo salta.
  - **Windows**: `winget install Ollama.Ollama` (circa 1,5 GB, per l'utente, senza diritti di amministratore).
  - **macOS**: scarica `Ollama.dmg` dalla pagina ufficiale delle versioni su GitHub e copia l'app in `/Applications`, o in `~/Applications` se la cartella non è scrivibile; poi lo avvia. Su macOS precedenti a Sonoma (14) non lo installa e lo spiega.
- Se rispondi no o il download non riesce, l'installazione di Argo finisce lo stesso e alla fine ti dice dove scaricare Ollama.
- Argo trova e accende Ollama anche quando è in `~/Applications`.
- Manuale (§3.3, §3.4) e README aggiornati.

## 20261119.1540: disinstallare senza scaricare niente
- **Dentro Argo**: *Impostazioni › Aspetto e aggiornamenti › Disinstallare Argo › «Disinstalla Argo…»*, su Mac e Windows. Si apre il disinstallatore in una finestra a parte e Argo si chiude.
- **Windows**: Argo compare in *Impostazioni › App › App installate* con il suo **Disinstalla**, e nel menu Start c'è **«Disinstalla Argo»**. È registrato solo per l'utente, senza diritti di amministratore. Lo fa l'installer e anche Argo all'avvio, quindi vale anche per chi si aggiorna dall'app.
- Il disinstallatore si copia in una cartella temporanea e parte da lì, così può cancellare anche la cartella di Argo. Su Windows toglie anche la voce tra le app installate.
- Gli script stanno ora in `app/disinstallatore/` e arrivano con gli aggiornamenti; `Disinstalla-Argo.bat` e `.command` nel pacchetto restano per quando Argo non si apre.

## 20261119.1523: disinstallatori per Mac e Windows
- **`Disinstalla-Argo.command`** (macOS) e **`Disinstalla-Argo.bat`** (Windows), nel pacchetto accanto agli installer:
  - mostrano cosa verrà eliminato e chiedono conferma;
  - propongono un backup sulla Scrivania di voci, incontri, clienti, glossario, indice dei documenti e impostazioni, senza token e chiavi;
  - chiudono Argo ed eliminano l'app o i collegamenti e la cartella `whisperx-env`;
  - chiedono se eliminare anche le registrazioni archiviate.
- Non toccano Ollama, i suoi modelli, uv, FFmpeg e le cache dei modelli condivise: alla fine dicono come toglierli a mano.
- `Disinstalla-Argo.bat` trova lo script anche se è accanto a lui (file scaricati sciolti) e non solo nella cartella `installer`. Il manuale spiega cosa fare con l'errore «is not digitally signed» se si lancia direttamente il `.ps1`.
- Manuale (§14) e README aggiornati.

## 20261119.1011: schede «Maggiori info» sui modelli cloud, GB dei modelli locali, addio a GitHub Models
- **ℹ️ Maggiori info** accanto a ogni fornitore cloud: sito, come creare la chiave passo per passo, **dove vengono elaborati i dati** (Europa o no), per quanto vengono conservati, se finiscono nell'addestramento, con i link alle pagine ufficiali e la data della verifica (19/11/2026).
  - **Claude**: con l'API diretta l'elaborazione è «global» o solo USA e i dati salvati stanno negli USA: nessuna garanzia di restare in Europa. Input e output vengono cancellati entro 30 giorni e non sono usati per l'addestramento.
  - **Ollama Cloud**: soprattutto USA, a volte Europa o Singapore. Ollama dichiara nessun log, nessuna conservazione e nessun addestramento.
- **Dimensione in GB dei modelli locali** nelle tendine di *Impostazioni › Ollama* e in *Incontri › Foto* (es. `gemma3:12b · 8,1 GB`), letta da Ollama.
- **Tolto GitHub Models**: GitHub l'ha chiuso il 30 luglio 2026 (API, catalogo e chiavi non funzionano più). Gli attrezzi che lo usavano tornano in locale; criteri e documenti aggiornati.

## 20261119.0801: template delle relazioni e Impostazioni per argomento
- **Template delle relazioni**, nel nuovo argomento *Impostazioni › 📝 Relazioni*: sezioni da spuntare e riordinare trascinandole, lunghezza (breve, media, dettagliata) e **«Come la voglio»**, le tue indicazioni in parole tue.
- **Cinque template standard**: *Fiera · primo contatto* (★ predefinito, come le relazioni di prima), *Visita cliente*, *Riunione interna · verbale*, *Intervista · assessment* (temi, risposte e citazioni fedeli), *Nota rapida · CRM o mail*. Gli standard si duplicano; i tuoi si creano, modificano ed eliminano, e uno diventa il ★ predefinito.
- **Nuove sezioni**: Esigenze del cliente, Temi e risposte, Decisioni, Punti aperti, Rischi e criticità.
- **In Incontri**, tendina **Template:** accanto a «✨ Scrivi relazione»: ogni incontro in coda tiene il suo template, anche se chiudi Argo. *Clienti › Dalla call* usa il predefinito. Il piè della relazione dice quale template è stato usato.
- Contatti, aziende e azioni si estraggono sempre, anche quando il template non li mostra: Dynamics e Clienti non perdono nulla.
- **Impostazioni per argomento**: colonna a sinistra con *Trascrizione e voci*, *Modelli AI*, *Relazioni*, *Collegamenti*, *Aspetto e aggiornamenti*; a destra solo l'argomento scelto. «Salva impostazioni» resta sempre in vista; i «Collega…» delle altre pagine aprono l'argomento e il riquadro giusti.

## 20261119.0746: Incontri da audio e video, e file aggiunti agli incontri
- **🎙 Nuovo da audio/video…** nella pagina *Incontri*: ogni registrazione o video (MP3, M4A, WAV, MP4, MOV, MKV…) diventa un incontro come quelli dell'iPhone. Trascrizione WhisperX, parlanti e voci note sul computer, rispettando «Uso del computer»; avanzamento sotto i pulsanti, **■ Ferma** per interrompere. Nome e data dal file.
- **L'audio non resta**: copia di lavoro e JSON con le impronte vocali si cancellano alla fine; il file originale non viene toccato.
- **📎 Aggiungi file…** su un incontro (anche dal menu col tasto destro):
  - **foto e immagini**, convertite in JPEG (anche HEIC), che il modello vision descrive nella relazione;
  - **documenti** PDF, Word, TXT, MD e CSV, il cui testo entra nella relazione come «📎 ALLEGATO»;
  - **altri audio o video**, trascritti in coda all'incontro, con le voci sconosciute numerate di seguito.
- **Trascina i file** sulla pagina Incontri: audio e video diventano incontri nuovi, oppure, a scelta, il seguito dell'incontro selezionato; foto e documenti si aggiungono all'incontro selezionato.
- Relazione, Word ed esportazioni dicono «modello cloud» invece di «AI locale» quando un attrezzo usa il cloud.

## 20261118.2030: correzione · Argo non partiva dopo l'aggiornamento
- La 20261118.1957 si fermava all'avvio (errore `UnboundLocalError: QTimer` in `main()`), prima ancora di aprire la finestra. Corretto. Chi è rimasto bloccato deve sostituire a mano `app/trascrittore.py`: l'aggiornamento automatico parte solo dall'app aperta.

## 20261118.1957: modelli cloud facoltativi, attrezzo per attrezzo
Di base Argo resta tutto in locale. Ora, se vuoi, puoi usare un modello cloud per alcuni attrezzi.
- **Nuovo riquadro *Impostazioni › Modelli cloud***: collega **Claude** (chiave API Anthropic), **GitHub Models** (token GitHub con permesso *Models: read*) e **Ollama Cloud** (chiave di ollama.com, anche quella della Ricerca web). **Collega e verifica** controlla la chiave e legge i modelli.
- **Scelta per attrezzo**: Verbale, Documenti, Dettatura, Traduzione, Agenda, Posta, Incarichi, Incontri (relazione e foto, separati) e Clienti. Ogni riga è **🖥 Locale** oppure un modello **☁️**; a ogni scelta cloud Argo chiede conferma e dice quali dati usciranno.
- **Sempre visibile**: lo stato della pagina scrive ☁️ fornitore e modello quando i dati vanno nel cloud; il badge in alto elenca gli attrezzi nel cloud invece di «100% locale»; le relazioni degli incontri riportano il modello ☁️.
- **Restano sempre in locale**: audio, trascrizione WhisperX, impronte vocali, indice dei documenti.
- **Criteri aziendali**: nuova chiave `"modelli_cloud"` in `criteri.json`, cioè `"vietati"` oppure l'elenco dei fornitori ammessi (vedi docs/PRO.md).
- Le chiavi stanno in `.chiavi_cloud.json`, leggibile solo dal tuo utente.

## 20261118.1710: Ollama pronto al primo avvio
- **Ollama acceso da Argo**: all'avvio, se Ollama è installato ma spento, Argo lo avvia (sul Mac l'app con l'icona del lama, su Windows l'icona nella barra) e aspetta che risponda.
- **Modelli consigliati**: se mancano un modello per i testi o per i documenti, Argo propone di scaricarli, con nomi e pesi: `gemma3:4b` (circa 3,3 GB) sui PC leggeri o con meno di 16 GB di RAM, altrimenti `gemma3:12b` (circa 8,1 GB), più `bge-m3` (circa 1,2 GB). L'avanzamento compare in basso nella finestra.
- **Già scelti**: dopo il download (o all'avvio, se i modelli c'erano già) Argo sceglie i modelli per testi, documenti e **foto degli Incontri**; si cambiano in *Impostazioni › Ollama*.
- Con «Non ora» Argo non lo richiede più all'avvio; nuovo pulsante **Scarica modelli consigliati** in *Impostazioni › Ollama*.

## 20261118.1645: Argo non blocca più i PC meno potenti
Su computer con CPU modeste, trascrizioni e riassunti prendevano tutti i core e la memoria, e il PC smetteva di rispondere. Ora Argo si regola da solo.
- **Nuova impostazione «Uso del computer»** (*Impostazioni › Trascrizione*): **Automatico** (predefinito), **Leggero**, **Bilanciato**, **Massima velocità**. Sotto la scelta, Argo dice cosa ha trovato (core e RAM) e cosa farà.
- **Automatico** sceglie *Leggero* sui computer con 4 core logici o meno, oppure con 8 GB di RAM o meno; altrimenti *Bilanciato*.
- **Core limitati**: WhisperX (trascrizione, allineamento, parlanti), dettatura e traduzione, modalità Live e Ollama usano solo una parte dei core (es. 8 core: 2 in Leggero, 4 in Bilanciato, 7 in Massima velocità).
- **Priorità bassa** per i calcoli (tranne in Massima velocità): mouse, Teams e Office hanno sempre la precedenza.
- **Profilo Leggero**: un lavoro pesante alla volta (una trascrizione e un riassunto non partono più insieme: il secondo aspetta e lo dice); prima di trascrivere Argo toglie dalla memoria il modello di Ollama; Ollama lo rilascia dopo 1 minuto invece di 5; WhisperX lavora a lotti più piccoli (meno RAM).
- Su GPU NVIDIA la trascrizione resta com'era.

## 20261117.2025: manutenzione UX (Stile Argo)
Revisione di tutte le pagine con le regole dello Stile Argo; nessuna funzione cambia.
- **Stati vuoti uguali ovunque**: Agenda, Posta, Incontri, Clienti e Voci mostrano logo in filigrana, motto e cosa fare; Agenda e Posta tengono titolo e sottotitolo anche prima di collegare Microsoft 365.
- **«Collega…» porta al riquadro giusto**: da Agenda, Posta e Clienti le Impostazioni si aprono già su Microsoft 365, Dynamics o Ricerca web. In cima alle Impostazioni c'è un indice «Vai a»; **Salva impostazioni** è il pulsante principale, in fondo.
- **Azioni solo quando servono**: in Incontri, senza incontri, il primario è «📱 Collega iPhone…» e «Scrivi relazione», «Foto» e «Apri cartella» compaiono col primo incontro; in Clienti «Crea account…» e «Apri in Dynamics» compaiono quando servono; in Trascrivi «Rimuovi» e «Rimetti in coda» con un file scelto e il registro tecnico solo quando ha qualcosa da dire; in Impostazioni «Scollega» solo se collegato.
- **Documenti riservati**: «Svuota indice» in disparte e solo con documenti nell'indice.
- **Controlli più leggibili**: pallini di Live/Archivia visibili in entrambi i temi; schede (Cliente/Dalla call, risultati degli Incarichi) nello stile Argo; «Aggiorna elenco» dei dispositivi al posto del simbolo ↻ che Roboto non disegna.
- Nomi coerenti col menu: «Trascrivi» al posto di «Trascrittore» nei testi; Microsoft 365 «per Agenda, Posta e Incarichi», Dynamics «per Incontri e Clienti».
- Cambiando tema, le filigrane si ridisegnano con i colori nuovi.

## 20261117.1345: rilascio Lab · Argo per iPhone, Incontri e Clienti
Prima versione Lab con tutto il percorso dalla fiera al CRM. Le voci qui sotto, dalla 20261117.1108 in poi, dicono cosa c'è nel dettaglio.
- **Ponte Argo**: colleghi Argo per iPhone con un QR (Incontri › Collega iPhone…); incontri e impronte vocali passano in rete locale, cifrati.
- **Incontri**: relazione con il modello locale, anche dalle foto, coda che riprende dopo la chiusura, invio a Dynamics 365 Sales.
- **Clienti**: account in Dynamics, scheda pubblica con le regole di Client Intel Scout, partecipanti e task in Planner o Dynamics.
- Librerie nuove, installate da sole con l'aggiornamento: `segno` (QR); `cryptography` ora è dichiarata esplicitamente.
- Da configurare: Dynamics in *Impostazioni › Dynamics 365 Sales*, chiave di Ollama Web Search in *Impostazioni › Ricerca web*.

## 20261117.1330: indirizzo diviso nei campi del nuovo account
- *Clienti › Crea account*: l'indirizzo trovato dalla scheda pubblica viene diviso in **via, CAP, città, provincia e nazione** con regole fisse (niente modello); la provincia si completa quando la città è un capoluogo. Se manca, il **sito** è quello ufficiale individuato dalla ricerca.
- La descrizione dell'account si modifica su più righe.

## 20261117.1310: errori della ricerca web più chiari
- *Impostazioni › Ricerca web*: se Ollama rifiuta la ricerca, Argo mostra anche il **motivo dato dal servizio** (es. 402 = serve un piano o un credito sull'account), non solo il codice.

## 20261117.1254: nuova pagina Clienti (Dynamics 365 Sales)
- **Clienti › Cliente**: cerca l'account in Dynamics (nome, sito o dominio) con i suoi contatti; se non c'è, **🌐 Scheda pubblica** con le regole di **Client Intel Scout** in locale (10 sezioni, fonte e data su ogni dato, `[DATO NON DISPONIBILE]`, stop sugli omonimi) e **➕ Crea account…** precompilato da confermare, con la scheda come nota.
- Ricerca web con **Ollama Web Search** (account gratuito, chiave in *Impostazioni › Ricerca web*): esce solo il nome dell'azienda; il modello locale scrive **solo** dalle pagine scaricate, con URL e data.
- **Clienti › Dalla call**: incontri dall'iPhone, **trascrizioni del computer** (Dal computer ▾) e **invitati dal calendario**; per ogni partecipante l'azienda proposta dal CRM (email, dominio, biglietto da visita), Interno per i colleghi; relazione, **contatti e note in Dynamics**, **task in Planner o attività di Dynamics**, scegliendo ogni volta.
- Le trascrizioni del computer portate tra le call compaiono anche negli **Incontri**.
- Guida: [docs/CLIENTI.md](docs/CLIENTI.md).

## 20261117.1216: Incontri → Dynamics 365 Sales
- **☁️ Invia a Dynamics…** su un incontro con la relazione: per ogni contatto Argo cerca in Dynamics contatti, lead e account già presenti e **propone la destinazione** (contatto con la stessa email → lead aperto → nuovo lead). Tu scegli caso per caso, correggi i dati o salti il contatto.
- Su ogni destinazione: **nota con la relazione** (la versione che hai rivisto), **foto allegate**; sulla prima anche le **azioni come attività**. I nuovi lead hanno argomento, dati del biglietto da visita, riassunto, prossimo passo, tempi e budget, origine «Fiera» per le fiere.
- Nella tabella degli Incontri la colonna **CRM** mostra ☁️ per gli incontri inviati (con i link ai record); un reinvio chiede conferma e tiene lo storico.
- **Impostazioni › Dynamics 365 Sales**: indirizzo dell'ambiente e **Collega** (stessa app Entra di Microsoft 365, con in più il permesso *Dynamics CRM · user_impersonation*). Guida: [docs/DYNAMICS.md](docs/DYNAMICS.md).
- Su Dynamics non vanno mai audio né impronte vocali.

## 20261117.1205: relazione impaginata
- **Incontri › Relazione** ora mostra il testo **impaginato** (titoli, elenchi, grassetti, link) invece del Markdown grezzo.
- **✏️ Modifica** passa al testo da correggere, **👁 Anteprima** torna alla vista impaginata; **Salva modifiche** come prima.
- Corsivi e note dei contatti resi correttamente (anche nelle relazioni già scritte).

## 20261117.1200: la coda degli Incontri sopravvive alla chiusura
- La coda delle relazioni viene **salvata a ogni modifica** (`incontri_coda.json`), come quella delle trascrizioni.
- Alla riapertura: l'incontro che era in lavorazione risulta **«Interrotta - app chiusa durante l'elaborazione»**, gli altri restano **«In coda»** e ripartono con **▶ Riprendi coda (N)**.
- **■ Ferma coda** ora mette in pausa senza svuotare la coda (come nelle trascrizioni); per togliere un incontro: tasto destro › Togli dalla coda. Gli incontri «Interrotta» o «Errore» si rimettono in coda con ✨ Scrivi relazione.
- Chiudendo Argo durante una relazione compare una conferma; la chiusura non resta più appesa in attesa di Ollama.

## 20261117.1152: Incontri con la coda, come le trascrizioni
- **Elenco a tabella**: incontro, data, **durata**, numero di foto e di persone, stato della relazione e avanzamento.
- **Coda delle relazioni**: selezioni uno o più incontri e **✨ Scrivi relazione (N)** li mette in coda; Argo li elabora uno alla volta con **barra di avanzamento** e stato a colori («In coda», «In corso - foto 2 di 5…», «Pronta», «Errore»). **■ Ferma coda** interrompe; tasto destro: togli dalla coda, apri cartella, elimina incontro.
- La barra segue i passi reali (foto, blocchi, relazione finale) e avanza piano durante le chiamate lunghe al modello.

## 20261117.1144: relazione degli incontri, anche guardando le foto
- **Incontri › ✨ Scrivi relazione**: Ollama in locale legge la trascrizione con i nomi e le foto, e scrive una relazione strutturata con **contatti** (dai biglietti da visita), **aziende**, **interessi**, **opportunità** (prodotti, budget, tempi, decisori, prossimo passo), punti chiave e **azioni**. Nessun dato inventato: i campi sconosciuti restano vuoti.
- **Foto con un modello vision** (menu «Foto:»): se in Ollama c'è un modello che vede le immagini (es. gemma3, qwen2.5vl) Argo descrive ogni foto e ne estrae i dati leggibili; altrimenti usa il testo letto dall'iPhone. Le descrizioni restano in cache nell'incontro.
- Incontri lunghi: appunti a blocchi, poi la relazione.
- Relazione **modificabile** con «Salva modifiche», **Salva ▾** in Word o Markdown; scheda «Trascrizione e foto» con la cronologia completa.
- Solo Ollama locale: con un indirizzo non locale la relazione degli incontri non parte.
- Dati pronti per il prossimo passo: Dynamics 365 Sales.

## 20261117.1135: Ponte con l'iPhone e pagina Incontri
- **Nuova pagina Incontri** (gruppo Riunioni): fiere e visite ai clienti registrate con **Argo per iPhone**, con trascrizione divisa per persona, foto e testo letto dalle foto. Importa anche pacchetti `.zip` arrivati per altre vie.
- **Ponte Argo**: canale cifrato in rete locale tra iPhone e computer, al posto di AirDrop. Si collega con **📱 Collega iPhone…** inquadrando un QR (codice monouso, 5 minuti). L'iPhone accetta solo il certificato di questo computer (pinning); niente cloud. Gli incontri arrivano da soli quando l'iPhone è sulla stessa rete e Argo è aperto. Dettagli in [docs/PONTE.md](docs/PONTE.md).
- **Voci › 📱 Per iPhone…**: la scelta delle persone ora arriva all'iPhone dal Ponte; il file `.argovoci` resta come alternativa.
- Nuova libreria **segno** (QR code, pura Python). Per il canale Pro va rigenerato `requisiti.lock` con `strumenti/blocca_librerie.py`.
- Prossimi passi: relazione dell'incontro con Ollama (testo, foto e modello vision) e invio a Dynamics 365 Sales.

## 20261117.1108: le voci dell'anagrafe anche sull'iPhone
- **Voci › 📱 Per iPhone…**: esporta le persone scelte in un file `anagrafe.argovoci` da passare con AirDrop ad **Argo per iPhone**, che le riconosce negli incontri (registrati in fiera o in riunione direttamente dal telefono).
- Prima di esportare: spunte sulle persone da portare (la scelta viene ricordata) e **conferma del consenso** obbligatoria, perché le impronte vocali sono dati biometrici. Il file è leggibile solo dal tuo utente; dopo il trasferimento va cancellato dal Mac.
- Nessun ricalcolo: si usano le impronte già presenti. Il test di compatibilità tra pyannote (Mac) e FluidAudio (iPhone) ha dato somiglianza 0,94 sullo stesso audio e 0,85–0,88 tra registrazioni diverse della stessa persona.
- Nuovo comando: `python voci_core.py esporta-iphone FILE [NOME ...]`.

## 20261116.1818: più facile da usare, ogni pagina allo stesso modo
- **Menu in due gruppi**, nell'ordine del lavoro: **Riunioni** (Agenda → Registra → Trascrivi → Verbale → Incarichi) e **Attrezzi** (Posta, Documenti, Dettatura, Traduci); Voci e Impostazioni in fondo. Il nome nel menu è lo stesso del titolo della pagina.
- **Barra dei comandi uguale ovunque:** l'azione principale (pulsante terracotta) è sempre la prima a sinistra, poi le scelte e i file da aprire; a destra Copia e Salva. Un solo pulsante principale per pagina.
- **Agenda → Registra:** il pulsante «● Registra» dell'Agenda ora apre la pagina Registra con il titolo della riunione. Prima usava un registratore a parte, **solo microfono**: nelle call Teams mancavano le voci degli altri partecipanti.
- **Registra:** prima scegli il modo e le sorgenti («Microfono (tu)», «Audio del computer (gli altri)»), poi **Avvia**, con il titolo accanto.
- **Verbale:** «Salva ▾» con Word o Markdown al posto di due pulsanti.
- **Voci:** un solo pulsante **＋ Nuova voce ▾** con i tre modi; Aggiungi campione, Rinomina ed Elimina compaiono quando scegli una voce.
- **Trascrivi:** le azioni sul file compaiono quando servono, invece di cinque pulsanti spenti.
- **Pannelli vuoti** di Verbale, Dettatura, Traduzione e Documenti con il logo in filigrana e il passo da fare.
- Tolte le righe introduttive che ripetevano il sottotitolo; la barra di stato dice solo cosa sta succedendo (la località la indica il bollino 🔒).
- Nessuna funzione tolta: cambiano solo posizione e nomi di alcuni pulsanti (vedi manuale).

## 20261116.1725: contrasti secondo lo Stile Argo
- Colori allineati al design system **Stile Argo**, con contrasti verificati secondo WCAG 2.2 AA in entrambi i temi:
  - **bordi dei campi** di testo, dei menu a tendina e delle caselle più marcati (almeno 3:1 sul fondo), così si vede subito dove scrivere;
  - **testo segnaposto** (es. «Titolo della riunione») più leggibile: ora usa il colore delle note invece di quello dei disattivati;
  - nel tema Carta, verde «ok», arancio «attenzione» e rosso «errore» un filo più scuri (almeno 4,5:1 anche sui fondi chiari); terracotta più scuro per il testo delle selezioni e delle voci di menu evidenziate;
  - il **focus da tastiera** sui pulsanti è ora un bordo terracotta di 2 px;
  - settimo colore dei parlanti più scuro nel tema Carta.
- Nessun cambiamento di funzioni.

## 20261116.1701: stile Argo's New Dreams e Posta leggibile
- **Nuovo aspetto dal Brand Book** di Argo's New Dreams («Dove il fantastico è il quotidiano»):
  - due temi, **Notte** (antracite) e **Carta** (contenuto su carta calda, menu antracite come le sfere del logo), con accento terracotta;
  - pannelli bianco caldo che si staccano dal fondo, pulsanti secondari contornati, pulsanti disattivati chiaramente sbiaditi;
  - il **logo intero**, quadrato, in cima al menu; **icona dell'app** dal disco con le due sfere di `Icona_AND.psd` (Brand Book);
  - nei pannelli vuoti il logo compare come **filigrana molto tenue**, sfumata ai bordi, con il motto e l'indicazione di cosa fare;
  - carattere **Roboto**, incluso nell'app: stesso aspetto su Mac e Windows;
  - titoli più decisi e pulsanti principali arrotondati come le sfere del logo.
- **Posta AI:** la mail si vede **formattata** (grassetti, paragrafi, tabelle, link cliccabili) invece del testo grezzo con gli indirizzi dei link. Script e moduli vengono tolti; le **immagini remote non vengono scaricate**, quindi niente pixel di tracciamento. Al modello locale va il testo pulito, senza indirizzi dei link.
- La nuova icona dell'app compare nel Dock o nella barra delle applicazioni dopo aver rilanciato l'installer; la finestra la usa subito.

## 20261116.1611: Registra, con Live senza audio conservato
- **Nuova pagina Registra** per riunioni in presenza e **call Teams**: Argo prende il microfono e l'**audio del computer**, cioè le voci degli altri partecipanti.
  - Windows: WASAPI loopback, senza installare nulla;
  - macOS 13+: ScreenCaptureKit, solo audio, con il permesso *Registrazione schermo e audio di sistema*;
  - ripiego automatico su BlackHole, Missaggio stereo o VB-CABLE, se presenti.
- **Sorgenti gestibili:** scelta del microfono e dell'audio del computer (automatico, nessuno, metodo nativo o dispositivo preciso), **volume di ciascuna sorgente** regolabile anche durante la registrazione, livelli in tempo reale. Le scelte vengono ricordate.
- **Modalità Live:** trascrive mentre registri, a blocchi di 20-45 secondi tagliati sui silenzi, e **cancella ogni blocco audio appena il suo testo è salvato**. Alla fine resta solo la trascrizione con i nomi, pronta per il Verbale. I parlanti restano coerenti da un blocco all'altro: anagrafe voci prima, poi «Sconosciuto N» riconosciuti nella sessione.
- Musica o rumori senza parole (per esempio un video in sottofondo) non creano «Sconosciuti» senza frasi.
- **Modalità Archivia:** registrazione completa in `Documenti/Argo/Registrazioni` e **Metti in coda nel Trascrittore**.
- **Consenso:** prima di ogni registrazione Argo chiede di confermare che i partecipanti sono informati e prepara l'avviso da incollare in chat.
- **Recupero:** se Argo si chiude durante una Live, al prossimo ingresso in Registra propone di trascrivere il resto o di cancellare l'audio rimasto.
- **Criterio IT** `registrazione`: `completa`, `solo_live` o `nessuna`.
- Nuove librerie: `PyAudioWPatch` (solo Windows) e `pyobjc-framework-ScreenCaptureKit` (solo macOS). L'aggiornamento dall'app le installa se trova `uv`.
- Prove automatiche in `strumenti/prova_live.py` (42 prove, anche su Posta e criteri), eseguite anche dalla GitHub Action del rilascio Pro.
- Provata dal vivo su Mac (Apple Silicon): cattura dell'audio di sistema con ScreenCaptureKit e trascrizione Live a blocchi.

## 20261116.0951: canali Lab e Pro
- **Due canali di aggiornamento** in *Impostazioni → Aggiornamenti*:
  - **Lab** (predefinito): segue ogni novità appena pubblicata, come finora;
  - **Pro**: solo versioni rilasciate. Il pacchetto si installa solo se impronta SHA-256 e firma corrispondono al manifesto, e le librerie arrivano a versione fissa da `requisiti.lock`.
- **Criteri aziendali**: con un file `criteri.json` di sistema l'IT può bloccare il canale su Pro o disattivare gli aggiornamenti dall'app (vedi [docs/PRO.md](docs/PRO.md)).
- Più sicurezza anche per Lab: vengono scartati i file con percorsi che escono dalla cartella del programma.
- Roadmap di Argo Pro in [docs/PRO.md](docs/PRO.md).

## 20261115.1415: riapertura dopo l'aggiornamento (Mac)
- Corretto di nuovo: sul Mac Argo non si riapriva dopo **Aggiorna ora**. macOS chiudeva il comando di riavvio insieme alla vecchia finestra; ora la nuova istanza viene chiesta subito a macOS (`open -n`), prima di chiudere quella vecchia.
- La correzione vale dall'aggiornamento **successivo**: questo aggiornamento usa ancora il vecchio codice di riavvio, quindi dopo averlo installato riapri Argo a mano.

## 20261115.1400: Agenda e Posta AI
- **Agenda** (Microsoft 365): riunioni per giorno, con
  - **Prepara**: briefing locale con i verbali precedenti che citano i partecipanti e le azioni aperte;
  - **Registra**: registrazione dal microfono nella cartella `Documenti/Argo/Registrazioni`;
  - **Incarico →**: passa la registrazione e i partecipanti alla ricetta Call → recap + task;
  - **Partecipa** (Teams) e **Apri in Outlook**.
- **Posta AI** (Microsoft 365, lettura da attivare in *Impostazioni*): non lette o ultime 40, **Riassumi**, **Cosa mi si chiede**, **Scrivi risposta** col modello locale, **Salva come bozza in Outlook** (mai inviata), **Crea task in Planner**, **Segna come letta**.
- Le mail vengono elaborate solo sul computer, col modello locale; nessun nuovo permesso Microsoft 365.
- Connettore Microsoft 365 più robusto: errori di rete spiegati e filtri delle richieste codificati correttamente.

## 20261114.2030: accesso a Microsoft 365 dal browser
- **Collega** apre il browser di sistema (codice di autorizzazione con PKCE, risposta su `http://localhost`) invece del codice dispositivo, che molti tenant bloccano con l'accesso condizionale (errore AADSTS53003).
- Messaggi chiari per gli errori più comuni: 53003 (accesso condizionale), 50011 (redirect URI mancante), 65001 (consenso mancante).
- Nella registrazione dell'app serve il redirect URI `http://localhost` (Mobile and desktop applications).

## 20261114.2015: riavvio dopo l'aggiornamento
- Corretto: sul Mac, dopo **Aggiorna ora**, Argo si chiudeva senza riaprirsi. Ora si riapre dall'app «Argo AI», due secondi dopo la chiusura; il nuovo processo è del tutto separato da quello vecchio.

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
