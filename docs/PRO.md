# Argo Pro · roadmap a due canali

*Versione 20261116.0951 · documento di lavoro, da rivedere*

Argo nasce come esperimento personale: funziona sul Mac di chi lo scrive, si aggiorna a ogni modifica, si fida di quello che scarica. **Argo Pro** è lo stesso codice, preso sul serio: funziona su macchine che non conosciamo, per persone che non ci conoscono, e regge le domande di un IT aziendale.

Non sono due prodotti. È **un solo repository con due canali**.

| | **Lab** | **Pro** |
|---|---|---|
| Per chi | Chi sperimenta (tu, i colleghi curiosi) | Clienti e colleghi che lo usano per lavoro |
| Sorgente degli aggiornamenti | Ramo `main` | Solo GitHub Releases con tag `vAAAAMMGG.HHMM` |
| Ritmo | Ogni commit | Quando si decide di rilasciare |
| Verifica del pacchetto | Nessuna | SHA-256 dal manifesto + firma Ed25519 |
| Librerie | `requisiti.txt` (ultima versione disponibile) | `requisiti.lock` (versioni fisse con hash) |
| Governo IT | — | `criteri.json` di sistema (Intune/Jamf) |
| Promessa | "Prova le novità" | "Non si rompe senza preavviso" |

**Il flusso:** si sviluppa su `main` (Lab). Quando una versione ha girato abbastanza ed è stata provata, la si promuove a Pro con un solo comando, che fa i controlli, mostra cosa arriverà agli utenti Pro e chiede conferma:

```bash
python strumenti/passa_a_pro.py --controlla   # solo controlli e riepilogo
python strumenti/passa_a_pro.py               # controlli, riepilogo, conferma [s/N], tag e push
```

Il push del tag avvia la GitHub Action *Rilascio Pro*, che pubblica la release: pacchetto, manifesto, firma e note prese dal CHANGELOG. Quando cambiano le librerie: `python strumenti/blocca_librerie.py [freeze.txt]`.

---

## Fase 1 · Fondamenta del canale Pro *(questa PR)*

- [x] Scelta del canale in *Impostazioni → Aggiornamenti* (predefinito Lab: chi usa già Argo non nota differenze)
- [x] Canale Pro: legge l'ultima release, verifica manifesto, firma e SHA-256 del pacchetto; un pacchetto che non supera i controlli non viene installato
- [x] Protezione dai percorsi malevoli nello ZIP (anche per Lab)
- [x] `requisiti.lock` universale (Mac, Windows, Linux · Python 3.12) con hash, installato con `--require-hashes`, vincolato all'ambiente collaudato sul Mac (`strumenti/ambiente-riferimento.txt`)
- [x] GitHub Action *Rilascio Pro* sul tag `v*`, con controllo che tag e `VERSIONE` coincidano
- [x] Criteri aziendali (`criteri.json`): l'IT può bloccare il canale su Pro o disattivare gli aggiornamenti dall'app
- [x] Prove automatiche della catena di verifica (`strumenti/prova_aggiornamenti.py`)

**Da fare a mano, una volta sola (Luca):**
1. ~~Allineare il lock all'ambiente collaudato~~ fatto: `requisiti.lock` è vincolato a `strumenti/ambiente-riferimento.txt` (freeze del Mac, 16/11/2026)
2. Generare le chiavi: `uv run --with cryptography strumenti/genera_chiavi.py`, caricare il segreto con `gh secret set ARGO_FIRMA_PRIVATA`, fare commit di `app/chiave_aggiornamenti.pub`
3. Primo rilascio: `git tag v<VERSIONE> && git push origin v<VERSIONE>`

## Fase 2 · Installazione da azienda

- **Firma del codice:** notarizzazione Apple con Developer ID per l'app «Argo AI»; firma Authenticode per gli script e il collegamento su Windows. Senza questa, Gatekeeper e SmartScreen restano un ostacolo.
- **Pacchetto offline:** ambiente Python, librerie e modelli scelti in un unico installer (o su un mirror interno), senza download al primo avvio.
- **Distribuzione gestita:** installazione silenziosa e `criteri.json` distribuiti via Intune/Jamf; guida per l'IT.
- **Modelli fissati:** versione/revisione dei modelli WhisperX, pyannote e Ollama dichiarata e verificata con un hash, come per le librerie.

## Fase 3 · Qualità misurabile

- **Set di prova audio** (italiano, accenti locali, call Teams con rumore, voci sovrapposte), con WER e accuratezza dei parlanti misurati a ogni cambio di modello o libreria.
- **CI su Mac e Windows** (runner GitHub): avvio dell'app offscreen, prove di installazione dal lock.
- **Matrice di supporto dichiarata:** Apple Silicon (16 GB minimo consigliato), Intel Mac, Windows x64 con/senza NVIDIA, Windows ARM. Modello più leggero scelto in automatico se la RAM non basta.
- **Log diagnostici** locali, senza contenuti sensibili, esportabili per il supporto.

## Fase 4 · Governance e compliance

- **Anagrafe voci:** le impronte vocali usate per identificare persone possono essere dati biometrici (art. 9 GDPR). Servono:
  - modello di DPIA;
  - informativa per i partecipanti;
  - tempi di conservazione e cancellazione;
  - cifratura a livello di app;
  - possibilità di disattivare l'anagrafe con un criterio IT.
- **Registrazione:** ✅ conferma dell'informativa prima di ogni registrazione, modalità Live senza audio conservato, criterio IT `registrazione` (dalla 20261116.1611).
- **AI Act:** trasparenza verso chi viene registrato; valutare il riconoscimento dei parlanti rispetto alle categorie biometriche; materiali per l'alfabetizzazione AI (art. 4).
- **Licenze:** SBOM generata in CI; registro delle licenze dei modelli (condizioni d'accesso di pyannote, licenze dei modelli Ollama) accanto a `THIRD_PARTY_LICENSES.md`.
- **Microsoft 365:** guida per l'admin del tenant (registrazione dell'app in Entra ID, permessi delegati minimi, consenso).

## Fase 5 · Opzione server on-prem

Per aziende con molti utenti: Ollama e la trascrizione su un server in LAN con GPU, Argo come client leggero. Il dato resta in azienda, i risultati sono uniformi e la gestione è centralizzata. Il bollino «🔒 100% locale» diventa «🏢 in azienda».

---

## Criteri aziendali · esempio

`/Library/Application Support/Argo/criteri.json` (Mac) oppure `%ProgramData%\Argo\criteri.json` (Windows):

```json
{
  "canale_aggiornamenti": "pro",
  "aggiornamenti_dall_app": false,
  "registrazione": "solo_live",
  "modelli_cloud": ["claude"]
}
```

- `canale_aggiornamenti`: blocca il canale. L'utente lo vede ma non lo può cambiare.
- `aggiornamenti_dall_app: false`: Argo non controlla e non installa aggiornamenti da solo, perché li distribuisce l'IT.
- `registrazione`: `"completa"` (predefinito, Live e Archivia), `"solo_live"` (l'audio delle riunioni non viene mai conservato) oppure `"nessuna"` (pagina Registra disattivata).
- `riconoscimento_voci`: `false` disattiva l'anagrafe voci: niente riconoscimento e niente impronte nuove (quelle salvate restano, inutilizzate). Di base il riconoscimento è spento e lo attiva l'utente, con il consenso voce per voce.
- `ricerca_web`: `false` toglie la ricerca web della pagina Clienti (scheda pubblica con Ollama Web Search).
- `secondo_cervello`: `false` toglie il Secondo cervello: niente cataloghi di aziende e funzioni, niente schede «con chi» sugli incontri (dalla 20261120.1206).
- `trace`: `true` tiene accesa la modalità trace su quel PC (log più dettagliati, mai contenuti), per un'analisi del supporto. Va tolto a lavoro finito: finché c'è, l'utente non la può spegnere.
- `modelli_cloud`: `"consentiti"` (predefinito), `"vietati"` (Argo usa solo Ollama locale e il riquadro *Modelli cloud* lo dice) oppure un elenco dei fornitori ammessi tra `"claude"` e `"ollama_cloud"`. Le scelte già fatte dall'utente su un fornitore non più ammesso tornano automaticamente in locale.
