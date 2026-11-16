"""live_core.py - logica della trascrizione Live, senza interfaccia (si prova da sola).

Principio: l'audio non viene mai conservato. Esiste solo il blocco in attesa di trascrizione, in una
cartella privata dell'app; appena il suo testo è salvato, il blocco viene cancellato.

    Tagliatore   divide il flusso in blocchi di 20-45 s, tagliando sui silenzi (niente parole spezzate,
                 niente sovrapposizioni da ripulire); i blocchi senza voce vengono scartati subito
    Parlanti     tiene gli stessi nomi da un blocco all'altro: anagrafe voci prima, poi «Sconosciuto N»
                 riconosciuti per somiglianza con quanto sentito prima nella stessa sessione
    Sessione     cartella <APP_HOME>/live/<id>: blocchi in attesa, risultati.jsonl (testo già salvato),
                 parlanti.json; a fine sessione scrive <titolo>.json + <titolo>_nomi.txt e cancella tutto
"""
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

import cattura_audio as ca
import voci_core as core

SR = ca.SR
CARTELLA_LIVE = core.APP_HOME / "live"


# =============================================================== taglio sui silenzi
class Tagliatore:
    """Riceve audio a pezzi e restituisce blocchi completi (np.float32) quando trova un silenzio adatto."""
    FINESTRA = 0.03  # s, risoluzione dell'energia

    def __init__(self, min_s=20.0, max_s=45.0, silenzio_s=0.4, voce_min_s=0.6):
        self.min_n = int(min_s * SR)
        self.max_n = int(max_s * SR)
        self.f = int(self.FINESTRA * SR)
        self.sil_fin = max(1, int(silenzio_s / self.FINESTRA))
        self.voce_min_fin = max(1, int(voce_min_s / self.FINESTRA))
        self.buf = np.zeros(0, np.float32)
        self.scartati = 0  # blocchi senza voce, mai salvati

    def _energie(self, x):
        n = len(x) // self.f
        if not n:
            return np.zeros(0)
        return np.sqrt(np.mean(x[: n * self.f].reshape(n, self.f) ** 2, axis=1))

    @staticmethod
    def soglia(en):
        """Soglia del silenzio adattiva: sopra il rumore di fondo stimato, mai sotto un minimo assoluto."""
        if not len(en):
            return 0.004
        return max(0.004, 2.5 * float(np.percentile(en, 10)))

    def aggiungi(self, x):
        """Ritorna una lista di (blocco, ha_voce). I blocchi senza voce servono solo a tenere il conto del tempo."""
        self.buf = np.concatenate([self.buf, np.asarray(x, np.float32)])
        out = []
        while len(self.buf) >= self.min_n:
            taglio = self._punto_di_taglio()
            if taglio is None:
                break
            blocco, self.buf = self.buf[:taglio], self.buf[taglio:]
            voce = self.ha_voce(blocco)
            self.scartati += 0 if voce else 1
            out.append((blocco, voce))
        return out

    def _punto_di_taglio(self):
        en = self._energie(self.buf)
        s = self.soglia(en)
        silenzio = en < s
        primo = self.min_n // self.f
        run = 0
        for i in range(primo, len(en)):
            run = run + 1 if silenzio[i] else 0
            if run >= self.sil_fin:
                return (i - run // 2) * self.f  # a metà del silenzio
        if len(self.buf) >= self.max_n:  # niente silenzio lungo: taglia nel punto più quieto degli ultimi 10 s
            da = max(primo, (self.max_n - 10 * SR) // self.f)
            a = self.max_n // self.f
            return (da + int(np.argmin(en[da:a]))) * self.f
        return None

    def ha_voce(self, x):
        en = self._energie(x)
        return int(np.sum(en >= self.soglia(en) * 1.5)) >= self.voce_min_fin and float(en.max(initial=0)) > 0.008

    def svuota(self):
        """Fine registrazione: l'ultimo pezzo."""
        blocco, self.buf = self.buf, np.zeros(0, np.float32)
        return [(blocco, self.ha_voce(blocco))] if len(blocco) else []


# =============================================================== parlanti coerenti tra i blocchi
class Parlanti:
    """Ogni parlante della sessione ha un id stabile (SPEAKER_00, SPEAKER_01…), un nome e un'impronta media."""

    def __init__(self, voci=None, soglia=0.5, stato=None):
        self.voci = voci if voci is not None else core.carica_voci()
        self.soglia = soglia
        self.elenco = []  # [{"id","nome","noto","emb": list, "n": int}]
        if stato:
            self.elenco = stato

    def _nuovo_id(self):
        return f"SPEAKER_{len(self.elenco):02d}"

    def _riferimento(self, p):
        return self.voci[p["nome"]] if p["noto"] and p["nome"] in self.voci else core.norm(p["emb"])

    def assegna(self, emb_blocco):
        """emb_blocco: {etichetta_locale: vettore}. Ritorna {etichetta_locale: id_sessione}."""
        locali = {k: core.norm(v) for k, v in (emb_blocco or {}).items()
                  if v is not None and len(v) and np.all(np.isfinite(np.asarray(v, np.float32)))}
        bersagli = [("sessione", p) for p in self.elenco]
        nomi_in_sessione = {p["nome"] for p in self.elenco if p["noto"]}
        bersagli += [("anagrafe", n) for n in self.voci if n not in nomi_in_sessione]
        coppie = []
        for k, v in locali.items():
            for i, (tipo, b) in enumerate(bersagli):
                rif = self._riferimento(b) if tipo == "sessione" else self.voci[b]
                coppie.append((float(np.dot(v, rif)), k, i))
        coppie.sort(reverse=True)
        mappa, usati = {}, set()
        for sim, k, i in coppie:
            if sim < self.soglia or k in mappa or i in usati:
                continue
            tipo, b = bersagli[i]
            if tipo == "sessione":
                p = b
            else:
                p = {"id": self._nuovo_id(), "nome": b, "noto": True, "emb": locali[k].tolist(), "n": 0}
                self.elenco.append(p)
            usati.add(i)
            mappa[k] = p["id"]
            self._aggiorna(p, locali[k])
        for k in sorted(locali):
            if k not in mappa:
                ignoti = sum(1 for p in self.elenco if not p["noto"])
                p = {"id": self._nuovo_id(), "nome": f"Sconosciuto {ignoti + 1}", "noto": False,
                     "emb": locali[k].tolist(), "n": 0}
                self.elenco.append(p)
                mappa[k] = p["id"]
                self._aggiorna(p, locali[k])
        return mappa

    @staticmethod
    def _aggiorna(p, v):
        n = p.get("n", 0)
        p["emb"] = core.norm((np.asarray(p["emb"], np.float32) * n + v) / (n + 1)).tolist() if n else v.tolist()
        p["n"] = n + 1

    def nome(self, sid):
        for p in self.elenco:
            if p["id"] == sid:
                return p["nome"]
        return "Non attribuito"

    def mappa_nomi(self):
        return {p["id"]: p["nome"] for p in self.elenco}


# =============================================================== sessione su disco
def _cartella_privata(p):
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except Exception:
        pass
    return p


class Sessione:
    def __init__(self, cartella):
        self.dir = Path(cartella)
        self.meta = json.loads((self.dir / "sessione.json").read_text(encoding="utf-8"))
        stato = None
        if (self.dir / "parlanti.json").exists():
            stato = json.loads((self.dir / "parlanti.json").read_text(encoding="utf-8"))
        s = core.carica_impostazioni()
        self.parlanti = Parlanti(soglia=float(s.get("soglia", 0.5)), stato=stato)

    # ---- creazione e ritrovamento
    @classmethod
    def nuova(cls, titolo, destinazione):
        sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = _cartella_privata(_cartella_privata(CARTELLA_LIVE) / sid)
        meta = {"id": sid, "titolo": titolo.strip() or "Riunione", "inizio": datetime.now().isoformat(timespec="seconds"),
                "destinazione": str(destinazione), "prossimo": 1, "secondi": 0.0, "chiusa": False}
        (d / "sessione.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return cls(d)

    @staticmethod
    def in_sospeso():
        """Sessioni interrotte (Argo chiuso o bloccato durante una Live)."""
        if not CARTELLA_LIVE.exists():
            return []
        return [Sessione(d) for d in sorted(CARTELLA_LIVE.iterdir()) if (d / "sessione.json").exists()]

    def _salva_meta(self):
        tmp = self.dir / "sessione.json.tmp"
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / "sessione.json")

    # ---- blocchi
    def aggiungi_blocco(self, x):
        """Scrive un blocco in attesa. Ritorna il percorso (con l'inizio in secondi nel nome)."""
        n = self.meta["prossimo"]
        inizio = self.meta["secondi"]
        f = self.dir / f"blocco_{n:05d}_{int(round(inizio * 1000)):010d}.wav"
        ca.scrivi_wav(f, x)
        try:
            os.chmod(f, 0o600)
        except Exception:
            pass
        self.meta["prossimo"] = n + 1
        self.meta["secondi"] = inizio + len(x) / SR
        self._salva_meta()
        return f

    def avanza(self, secondi):
        """Tempo trascorso senza blocco (pezzi senza voce scartati): tiene allineati gli orari."""
        self.meta["secondi"] += secondi
        self._salva_meta()

    @staticmethod
    def inizio_blocco(f):
        return int(Path(f).stem.split("_")[2]) / 1000.0

    def blocchi_in_attesa(self):
        fatti = self.blocchi_fatti()
        out = []
        for f in sorted(self.dir.glob("blocco_*.wav")):
            if f.name in fatti:  # testo già salvato ma cancellazione interrotta
                elimina_sicuro(f)
            else:
                out.append(f)
        return out

    def blocchi_fatti(self):
        return {r.get("blocco") for r in self.risultati()}

    def risultati(self):
        f = self.dir / "risultati.jsonl"
        if not f.exists():
            return []
        out = []
        for riga in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(riga))
            except Exception:
                pass  # riga troncata da un arresto improvviso
        return out

    def registra_risultato(self, blocco, segmenti, emb):
        """Salva il testo di un blocco con i parlanti della sessione, POI cancella il blocco audio."""
        blocco = Path(blocco)
        t0 = self.inizio_blocco(blocco)
        # solo chi ha almeno una frase: musica o rumori senza testo non creano «Sconosciuti» fantasma
        con_testo = {s.get("speaker") for s in segmenti or [] if (s.get("text") or "").strip()}
        mappa = self.parlanti.assegna({k: v for k, v in (emb or {}).items() if k in con_testo})
        segs = []
        for s in segmenti or []:
            testo = (s.get("text") or "").strip()
            if not testo:
                continue
            segs.append({"start": round(t0 + float(s.get("start") or 0), 2), "end": round(t0 + float(s.get("end") or 0), 2),
                         "text": testo, "speaker": mappa.get(s.get("speaker"))})
        riga = json.dumps({"blocco": blocco.name, "segmenti": segs}, ensure_ascii=False)
        with open(self.dir / "risultati.jsonl", "a", encoding="utf-8") as fh:
            fh.write(riga + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp = self.dir / "parlanti.json.tmp"
        tmp.write_text(json.dumps(self.parlanti.elenco), encoding="utf-8")
        tmp.replace(self.dir / "parlanti.json")
        elimina_sicuro(blocco)
        return [(self.parlanti.nome(s["speaker"]), s) for s in segs]

    def scarta_blocchi(self):
        for f in self.dir.glob("blocco_*.wav"):
            elimina_sicuro(f)

    # ---- conclusione
    def nome_file(self):
        data = self.meta["inizio"][:16].replace("T", " ").replace(":", "")
        titolo = "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in self.meta["titolo"]).strip()[:60]
        return f"{data} {titolo or 'Riunione'} (live)"

    def concludi(self):
        """Scrive la trascrizione finale nella cartella di destinazione e cancella la cartella della sessione.
        Ritorna il percorso del file _nomi.txt (None se non è stato detto nulla)."""
        segs = sorted((s for r in self.risultati() for s in r["segmenti"]), key=lambda s: s["start"])
        out = None
        if segs:
            dest = Path(self.meta["destinazione"])
            dest.mkdir(parents=True, exist_ok=True)
            base = dest / self.nome_file()
            f_json = base.with_suffix(".json")
            i = 2
            while f_json.exists():
                f_json = dest / f"{self.nome_file()} {i}.json"
                i += 1
            dati = {
                "segments": segs,
                "language": core.carica_impostazioni().get("language") or "it",
                "speaker_embeddings": {p["id"]: p["emb"] for p in self.parlanti.elenco},
                core.NOMI_KEY: {p["id"]: p["nome"] for p in self.parlanti.elenco if p["noto"]},
                "argo_live": {"inizio": self.meta["inizio"], "durata_s": round(self.meta["secondi"], 1),
                              "audio_conservato": False},
            }
            f_json.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
            out = core.scrivi_trascrizione(dati, self.parlanti.mappa_nomi(), f_json)
        self.elimina()
        return out

    def elimina(self):
        self.scarta_blocchi()
        shutil.rmtree(self.dir, ignore_errors=True)


def elimina_sicuro(f):
    """Cancella un blocco audio: prima lo sovrascrive con zeri, poi lo rimuove.
    Sugli SSD la sovrascrittura non garantisce che il dato sparisca fisicamente: la vera protezione resta
    la cifratura del disco (FileVault, BitLocker), attiva di norma sui computer aziendali."""
    f = Path(f)
    try:
        n = f.stat().st_size
        with open(f, "r+b") as fh:
            fh.write(b"\0" * n)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        pass
    try:
        f.unlink()
    except FileNotFoundError:
        pass


def mmss(s):
    s = int(s)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


if __name__ == "__main__":
    for s in Sessione.in_sospeso():
        print(s.meta["id"], s.meta["titolo"], len(s.blocchi_in_attesa()), "blocchi in attesa")
