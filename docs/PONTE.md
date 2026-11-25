# Ponte Argo · canale tra Argo desktop e Argo per iPhone

Canale **cifrato, in rete locale, senza cloud** per tutto ciò che passa tra telefono e computer: oggi incontri (pacchetti `argo.sessione`) e anagrafe voci (`argo.voci`), domani altro.

## Sicurezza
| Aspetto | Scelta |
|---|---|
| Trasporto | HTTPS (TLS ≥ 1.2) su una porta della rete locale (predefinita 47321), solo mentre Argo è aperto |
| Identità del computer | Certificato autofirmato generato sul computer (`whisperx-env/ponte/`, chiave 600); l'iPhone accetta **solo** quel certificato, riconosciuto per impronta SHA-256 (pinning) |
| Abbinamento | QR mostrato in *Incontri › 📱 Collega iPhone…*: indirizzi, porta, impronta e **codice monouso valido 5 minuti** |
| Identità dell'iPhone | Segreto casuale rilasciato all'abbinamento; sul computer resta solo il suo hash; sull'iPhone sta nel Portachiavi (solo questo dispositivo) |
| Ritrovarsi su un'altra rete | Annuncio **Bonjour** `_argoponte._tcp` con `id=<id del computer>` nel record TXT (Mac: `dns-sd` di sistema; Windows: `dns-sd.exe` di Bonjour, se installato). L'iPhone lo cerca per id quando gli indirizzi salvati non rispondono; `/v1/stato` restituisce indirizzi e porta di adesso. L'indirizzo serve solo a **trovare** il computer: l'identità resta l'impronta del certificato. Il MAC non si usa (l'iPhone non può leggerlo e cambia da una rete all'altra) |
| Revoca | *Incontri › iPhone collegati › Scollega*, oppure *Scollega* sull'iPhone |
| Cosa non passa | Audio (l'iPhone non lo conserva). Le impronte vocali vanno solo dal computer all'iPhone, e solo quelle scelte in *Voci › Per iPhone* con consenso |

## Servizi (protocollo 1)
| Metodo | Percorso | Corpo / risposta |
|---|---|---|
| POST | `/v1/abbina` | `{codice, nome}` → `{segreto, id, nome}` |
| GET | `/v1/stato` | → `{id, nome, versione, protocollo, servizi, h, p}` (`h` indirizzi e nome `.local` di adesso, `p` porta: dalla 20261125.1224) |
| GET | `/v1/anagrafe` | → file `argo.voci` con le voci scelte (404 se nessuna) |
| POST | `/v1/incontri` | corpo: pacchetto `.zip` (`argo.sessione`) → `{ok, id}`; idempotente sull'id della sessione, conserva relazione e CRM già fatti sul computer |

Tutti tranne `abbina` richiedono `Authorization: Bearer <segreto>`.

## Contenuto del QR
`argo-ponte:` seguito da JSON compatto: `{"v":1,"n":nome,"p":porta,"h":[indirizzi],"f":impronta_base64url,"c":codice,"i":id}`. `h`: fino a 3 indirizzi IPv4 privati e il nome `.local` (sul Mac il LocalHostName di sistema, senza il dominio della rete). `i` (dalla 20261125.1224): id del computer per la ricerca Bonjour.

## Firewall
Al primo avvio del Ponte macOS (o Windows) può chiedere di consentire le connessioni in entrata ad Argo/Python: va consentito, solo per le reti private.
