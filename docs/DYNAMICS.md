# Dynamics 365 Sales · collegamento degli Incontri

Argo invia a Dynamics 365 Sales solo ciò che confermi nella finestra **☁️ Invia a Dynamics…** di un incontro.

## Una volta sola: l'app Entra di Argo
Argo usa la stessa registrazione dell'app di Microsoft 365 (Impostazioni › Microsoft 365: Client ID e Tenant ID).
1. Portale Entra › **App registrations** › l'app di Argo › **API permissions** › **Add a permission**.
2. **Dynamics CRM** › *Delegated permissions* › **user_impersonation** › Add.
3. **Grant admin consent** per il tenant.
4. L'utente deve avere una licenza Dynamics 365 Sales e un ruolo di sicurezza che permetta di creare lead, note e attività e di leggere contatti e account.

## In Argo
1. Impostazioni › **Dynamics 365 Sales** › Ambiente: `https://<nome>.crm4.dynamics.com` (lo trovi in Power Platform admin center › Ambienti › URL dell'ambiente).
2. **Collega**: si apre il browser, accedi e accetta il permesso. Argo mostra il tuo nome in Dynamics (prova con `WhoAmI`).

## Cosa succede con «Invia a Dynamics»
Per ogni contatto della relazione Argo cerca:
- **contatti** attivi con la stessa email o lo stesso nome e cognome;
- **lead** aperti con la stessa email o lo stesso nome e cognome;
- **account** con un nome simile all'azienda (senza S.r.l., S.p.A., GmbH…).

Proposta automatica: contatto con la stessa email → lead aperto con la stessa email → **nuovo lead**. Puoi sempre cambiare destinazione o saltare il contatto.

| Destinazione | Cosa viene creato |
|---|---|
| Nuovo lead | Lead (argomento = opportunità o titolo, dati del contatto, descrizione con riassunto, prossimo passo, tempi e budget; origine «Fiera» se l'incontro è una fiera) |
| Contatto, lead o account esistente | Niente di nuovo sul record: solo note e attività collegate |
| Per ogni destinazione | Nota con la relazione (testo che hai rivisto) e una nota per ogni foto, con l'immagine allegata |
| Solo sulla prima destinazione | Un'attività (task) per ogni azione della relazione |

L'esito resta nell'incontro (`argo-crm.json`) con i link ai record; nella tabella degli Incontri compare ☁️.

## Dati che non vanno mai su Dynamics
Audio (l'iPhone non lo conserva), impronte vocali, trascrizione completa (salvo il testo della relazione che hai approvato).
