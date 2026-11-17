# Clienti · Dynamics 365 Sales, scheda pubblica e call

## Scheda «Cliente»
1. Scrivi nome, sito o dominio email e premi **🔍 Cerca in Dynamics**: account attivi con contatti.
2. Se non c'è: **🌐 Scheda pubblica**. Se esistono omonimi Argo si ferma e chiede quale (oppure indica sito, sede o P.IVA nel secondo campo).
3. Rileggi la scheda e premi **➕ Crea account…**: i campi sono precompilati dalla scheda e li confermi tu; la scheda può andare come nota sull'account.

### La scheda pubblica è «Client Intel Scout» in locale
Stesse regole dell'agente Copilot Studio (istruzioni v20260819.0334 in AIFirst › Sviluppo AI › Copilot Studio › Agents › Client Intel Scout):
- 10 sezioni fisse; la 9 «Dati non reperiti» e la 10 «Elenco fonti consultate» sono sempre presenti;
- ogni dato con fonte `[n]`; la tabella delle fonti ha URL, data di consultazione e livello di affidabilità (1 sito ufficiale, 2 registri istituzionali, 3 testate, 4 aggregatori, 5 altro);
- `[DATO NON DISPONIBILE]` invece di valori verosimili, `[DATO POTENZIALMENTE SUPERATO]` oltre i 24 mesi;
- omonimia: ci si ferma e si chiede;
- niente profili di persone, niente valutazioni, niente stime, niente stack tecnologico dedotto.

Differenze di architettura rispetto all'agente:
| | Client Intel Scout (Copilot Studio) | Argo |
|---|---|---|
| Ricerca web | Web search di Copilot Studio | **Ollama Web Search** (account Ollama gratuito, chiave in Impostazioni) |
| Modello | GPT nel cloud Microsoft | Modello locale di Ollama |
| Cosa esce dal computer | — | Solo le query con il nome dell'azienda |
| Da dove scrive | Web search durante la risposta | **Solo** dalle pagine scaricate e passate al modello con URL e data |
| Costo | 5 Copilot Credits per invocazione da EVO | Free tier di Ollama Web Search |

Le schede restano in `whisperx-env/clienti/<azienda>/scheda-AAAAMMGG-HHMM.md` (+ `.json` con fonti e dati proposti).

## Scheda «Dalla call»
Sorgenti: **📱 incontri dall'iPhone**, **💻 trascrizioni del computer** («Dal computer ▾» porta una trascrizione completata di Trascrivi tra le call e tra gli Incontri), **📅 calendario** (invitati con email della riunione di Outlook più vicina all'orario della call).

1. **🏢 Proponi aziende dal CRM**: per ogni partecipante Argo cerca, nell'ordine, il contatto con la stessa email (e la sua azienda), gli account del dominio email (sito o email dei contatti), l'azienda letta dal biglietto da visita. Chi ha il dominio della tua azienda, o si chiama «Io», è **Interno**.
2. Correggi la colonna **Azienda**: «Altra azienda in Dynamics…» cerca di nuovo, «Nuovo cliente…» porta alla scheda «Cliente».
3. **✨ Relazione** (la stessa degli Incontri), poi **☁️ Salva in Dynamics**: contatti nuovi per i partecipanti spuntati (non si duplicano quelli con email già presente) e relazione come nota sugli account scelti.
4. **✅ Crea task…**: Argo chiede ogni volta **dove** creare le azioni: **Planner** (piano e bucket, assegnazione ai partecipanti con account Microsoft 365) oppure **attività di Dynamics** sull'account scelto. Dynamics non ha un planner, ma le attività (task) con scadenza e responsabile, legate al cliente.

Le scelte sui partecipanti restano nell'incontro (`argo-clienti.json`).
