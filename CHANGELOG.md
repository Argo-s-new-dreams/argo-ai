# Novità di Argo · Cassetta degli attrezzi AI

Le versioni hanno il formato `AAAAMMGG.HHMM` (ora di Roma). Il manuale completo è in [docs/MANUALE.md](docs/MANUALE.md).

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
