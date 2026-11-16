"""prova_live.py - prove automatiche di Registra/Live, senza microfono né modelli.

    python strumenti/prova_live.py

Verifica con audio sintetico: ricampionamento senza clic, mixer, taglio sui silenzi, continuità dei parlanti
tra i blocchi, salvataggio del testo e cancellazione dei blocchi, recupero dopo un arresto, file finali
compatibili con Verbale e Revisione nomi, criteri IT. Non serve WhisperX: il motore è simulato.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

CASA = tempfile.mkdtemp(prefix="argo-prova-live-")
os.environ["TRASCRITTORE_HOME"] = CASA
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import numpy as np  # noqa: E402

import cattura_audio as ca  # noqa: E402
import live_core as live  # noqa: E402
import voci_core as core  # noqa: E402

SR = ca.SR
rng = np.random.default_rng(7)
esiti = []


def prova(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("✅ " if cond else "❌ ") + nome + (f"  ({dettaglio})" if dettaglio and not cond else ""))


def voce(secondi, ampiezza=0.2):
    """Parlato finto: rumore modulato a sillabe (4 Hz)."""
    t = np.arange(int(secondi * SR)) / SR
    return (rng.normal(0, ampiezza, len(t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32)


def silenzio(secondi):
    return rng.normal(0, 0.0008, int(secondi * SR)).astype(np.float32)


# ---------------------------------------------------------------- ricampionamento
sr = 48000
t = np.arange(sr * 2) / sr
seno = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
r = ca.Ricampionatore(sr)
pezzi, i = [], 0
while i < len(seno):
    n = int(rng.integers(100, 2000))
    pezzi.append(r(seno[i:i + n]))
    i += n
a = np.concatenate(pezzi)
b = ca.Ricampionatore(sr)(seno)
prova("48 kHz → 16 kHz a blocchi casuali = in un colpo solo", len(a) == len(b) and np.allclose(a, b, atol=1e-5),
      f"{len(a)} vs {len(b)}")
salti = np.max(np.abs(np.diff(a[200:])))
prova("nessun clic ai bordi dei blocchi", salti < 0.2, f"salto massimo {salti:.3f}")
prova("44,1 kHz gestito", abs(len(ca.Ricampionatore(44100)(np.zeros(44100, np.float32))) - SR) <= 1)

# ---------------------------------------------------------------- mixer
mx = ca.Mixer(lambda x: None)
m = np.full(1600, 0.1, np.float32)
x1 = mx.mescola(m, np.full(800, 0.2, np.float32))
prova("mixer: audio del computer in ritardo riempito di zeri", np.allclose(x1[:800], 0.3) and np.allclose(x1[800:], 0.1))
x2 = mx.mescola(m, np.full(4000, 0.2, np.float32))
prova("mixer: l'eccesso resta in attesa per il blocco dopo", np.allclose(x2, 0.3) and len(mx._attesa) == 2400)
mx.mescola(m, np.full(SR * 5, 0.2, np.float32))
prova("mixer: attesa limitata a 2 s (niente deriva)", len(mx._attesa) <= 2 * SR)

mx.g_mic, mx.g_sis = 0.5, 2.0
mx._attesa = np.zeros(0, np.float32)
x3 = mx.mescola(np.full(160, 0.2, np.float32), np.full(160, 0.1, np.float32))
prova("mixer: volumi per sorgente", np.allclose(x3, 0.3))
prova("sorgenti: «nessuna» = solo microfono", ca.sorgente_sistema("nessuna") == (None, ""))
prova("sorgenti: dispositivo scollegato segnalato", ca.sorgente_sistema("dev:Cuffie inesistenti")[1].startswith("dispositivo"))
el = [v for v, _ in ca.elenco_sistema()]
prova("sorgenti: elenco con Automatico e Nessuno", el[:2] == ["auto", "nessuna"])
prova("sorgenti: microfono predefinito sempre disponibile", ca.elenco_microfoni()[0][0] == "")

# ---------------------------------------------------------------- tagliatore
tg = live.Tagliatore()
flusso = np.concatenate([voce(12), silenzio(0.8), voce(15), silenzio(1.0), voce(30), silenzio(0.6),
                         voce(8), silenzio(40), voce(50), silenzio(5)])
blocchi = []
for k in range(0, len(flusso), 1600):  # come il mixer: 100 ms alla volta
    blocchi += tg.aggiungi(flusso[k:k + 1600])
blocchi += tg.svuota()
durate = [len(x) / SR for x, _ in blocchi]
prova("taglio: nessun campione perso", sum(len(x) for x, _ in blocchi) == len(flusso))
prova("taglio: blocchi con voce tra 20 e 45 s (l'ultimo può essere corto)",
      all(20 - 0.05 <= d <= 45 + 0.05 for (x, v), d in zip(blocchi[:-1], durate[:-1]) if v), str(durate))
prova("taglio: il primo taglio cade nel silenzio dopo 20 s", 27.5 < durate[0] < 29.0, f"{durate[0]:.2f} s")
prova("taglio: un pezzo di solo silenzio non viene trascritto", any(not v for _, v in blocchi),
      str([(round(d, 1), v) for (_, v), d in zip(blocchi, durate)]))
prova("taglio: parlato di 50 s senza pause spezzato entro 45 s", max(durate) <= 45.05)

# ---------------------------------------------------------------- parlanti
dim = 256
base = {n: core.norm(rng.normal(size=dim)) for n in ("Anna", "Bruno", "Ospite X", "Ospite Y")}


def come(n, rumore=0.25):
    return (base[n] + rumore * core.norm(rng.normal(size=dim))).tolist()


pl = live.Parlanti(voci={"Anna": base["Anna"], "Bruno": base["Bruno"]}, soglia=0.5)
m1 = pl.assegna({"SPEAKER_00": come("Anna"), "SPEAKER_01": come("Ospite X")})
m2 = pl.assegna({"SPEAKER_00": come("Ospite X"), "SPEAKER_01": come("Bruno"), "SPEAKER_02": come("Ospite Y")})
m3 = pl.assegna({"SPEAKER_00": come("Ospite Y"), "SPEAKER_01": come("Anna")})
nomi = pl.mappa_nomi()
prova("parlanti: chi è in anagrafe viene riconosciuto in ogni blocco",
      nomi[m1["SPEAKER_00"]] == "Anna" and nomi[m2["SPEAKER_01"]] == "Bruno" and nomi[m3["SPEAKER_01"]] == "Anna")
prova("parlanti: uno sconosciuto resta lo stesso da un blocco all'altro", m1["SPEAKER_01"] == m2["SPEAKER_00"])
prova("parlanti: un secondo sconosciuto riceve un nome nuovo e lo mantiene",
      m2["SPEAKER_02"] == m3["SPEAKER_00"] and nomi[m2["SPEAKER_02"]] == "Sconosciuto 2")
prova("parlanti: in un blocco due voci non finiscono sullo stesso nome", len(set(m2.values())) == 3)
m4 = pl.assegna({"SPEAKER_00": [float("nan")] * dim})
prova("parlanti: impronta non valida ignorata (Non attribuito)", m4 == {})

# ---------------------------------------------------------------- sessione: testo salvato, audio cancellato
for n in ("Anna", "Bruno"):  # anagrafe voci come sul computer dell'utente
    core.salva_impronta(n, base[n])
dest = Path(CASA) / "Registrazioni"
s = live.Sessione.nuova("Prova: call/cliente", dest)
f1 = s.aggiungi_blocco(voce(25))
s.avanza(40.0)
f2 = s.aggiungi_blocco(voce(22))
f3 = s.aggiungi_blocco(voce(21))
prova("sessione: cartella privata (solo l'utente)", os.name == "nt" or (s.dir.stat().st_mode & 0o077) == 0)
prova("sessione: orario del blocco dopo una pausa scartata", abs(live.Sessione.inizio_blocco(f2) - 65.0) < 0.01)
s.registra_risultato(f1, [{"start": 0.5, "end": 4.0, "text": " Buongiorno a tutti.", "speaker": "SPEAKER_00"},
                          {"start": 5.0, "end": 9.0, "text": "Ciao Anna.", "speaker": "SPEAKER_01"}],
                     {"SPEAKER_00": come("Anna"), "SPEAKER_01": come("Ospite X")})
prova("sessione: blocco cancellato appena il suo testo è salvato", not f1.exists())
# arresto improvviso: il testo di f2 è salvato ma il file non è stato cancellato
s.registra_risultato(f2, [{"start": 1.0, "end": 3.0, "text": "Partiamo.", "speaker": "SPEAKER_00"}],
                     {"SPEAKER_00": come("Ospite X")})
ca.scrivi_wav(f2, voce(1))  # simula il file rimasto
ripresa = live.Sessione.in_sospeso()
prova("recupero: sessione interrotta ritrovata", len(ripresa) == 1 and ripresa[0].meta["titolo"] == "Prova: call/cliente")
attesa = ripresa[0].blocchi_in_attesa()
prova("recupero: il blocco già trascritto non viene rifatto e viene cancellato", attesa == [f3] and not f2.exists())
prova("recupero: i parlanti della sessione sono ricordati",
      ripresa[0].parlanti.mappa_nomi() == s.parlanti.mappa_nomi())
r = ripresa[0]
r.registra_risultato(f3, [{"start": 0.0, "end": 2.0, "text": "Va bene.", "speaker": "SPEAKER_00"}],
                     {"SPEAKER_00": come("Anna")})
out = r.concludi()
prova("conclusione: trascrizione _nomi.txt scritta", out is not None and out.exists() and out.name.endswith("_nomi.txt"))
testo = out.read_text(encoding="utf-8")
prova("conclusione: nomi coerenti e orari assoluti",
      "[00:00:00] Anna: Buongiorno a tutti." in testo and "[00:00:05] Sconosciuto 1: Ciao Anna. Partiamo." in testo
      and "[00:01:27] Anna: Va bene." in testo, testo)
prova("conclusione: nessun file audio e cartella della sessione rimossa",
      not r.dir.exists() and not list(Path(CASA).rglob("*.wav")))
f_json = out.with_name(out.name.replace("_nomi.txt", ".json"))
dati = json.loads(f_json.read_text(encoding="utf-8"))
s2 = live.Sessione.nuova("Fantasmi", dest)
fb = s2.aggiungi_blocco(voce(21))
s2.registra_risultato(fb, [{"start": 0.0, "end": 2.0, "text": "Ciao.", "speaker": "SPEAKER_01"}],
                      {"SPEAKER_00": come("Ospite Y"), "SPEAKER_01": come("Ospite X")})
prova("parlanti: chi non ha frasi (musica, rumore) non diventa uno Sconosciuto",
      list(s2.parlanti.mappa_nomi().values()) == ["Sconosciuto 1"], str(s2.parlanti.mappa_nomi()))
s2.elimina()
prova("conclusione: JSON dichiara che l'audio non è conservato", dati["argo_live"]["audio_conservato"] is False)
_, mappa, _, _ = core.identifica(f_json)
prova("compatibile con Revisione nomi: Anna resta Anna, l'ospite resta sconosciuto",
      sorted(mappa.values()) == ["Anna", "Sconosciuto 1"], str(mappa))

# ---------------------------------------------------------------- criteri IT

fc = Path(CASA) / "criteri.json"
os.environ["ARGO_CRITERI"] = str(fc)
import registrazione  # noqa: E402

for valore, atteso in (("solo_live", ("live",)), ("nessuna", ()), ("completa", ("live", "archivia")),
                       ("boh", ("live", "archivia"))):
    fc.write_text(json.dumps({"registrazione": valore}), encoding="utf-8")
    prova(f"criteri: registrazione = {valore}", registrazione.modalita_consentite() == atteso)
fc.unlink()
prova("criteri: senza file entrambe le modalità", registrazione.modalita_consentite() == ("live", "archivia"))
prova("misuratore di livello in dB", registrazione.percentuale(1.0) == 100 and registrazione.percentuale(0.0) == 0)

# ---------------------------------------------------------------- Posta: HTML delle mail
import m365  # noqa: E402

h = ('<html><head><style>p{color:red}</style></head><body><p>Ciao <b>Luca</b>,</p><img src="https://t/x.gif">'
     '<p>vedi <a href="https://linkedin.com/x?lipi=1" onclick="x()">il messaggio</a></p><script>alert(1)</script>'
     '<table><tr><td>A</td><td>B</td></tr></table></body></html>')
pul = m365.pulisci_html(h)
prova("posta: niente script, immagini remote né eventi", all(x not in pul for x in ("<script", "<img", "onclick", "<style")))
prova("posta: formattazione e link conservati", "<b>Luca</b>" in pul and 'href="https://linkedin.com' in pul)
prova("posta: al modello va testo pulito senza indirizzi", m365.html_a_testo(h) == "Ciao Luca,\n\nvedi il messaggio\n\nA B",
      repr(m365.html_a_testo(h)))

print(f"\n{sum(esiti)}/{len(esiti)} prove superate")
sys.exit(0 if all(esiti) else 1)
