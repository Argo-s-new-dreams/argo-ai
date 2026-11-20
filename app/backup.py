"""backup.py - backup, ripristino e configurazione condivisa tra più computer (Mac e Windows).

Due livelli di backup (decisione di Luca, 20/11/2026):
    - «configurazione»: impostazioni (template delle relazioni compresi), glossario. Pochi KB.
    - «completo»: la configurazione più i dati: voci, incontri, clienti, Secondo cervello, indice dei Documenti,
      code di lavoro. Può pesare GB (audio e foto degli incontri).
Chiavi e token (Hugging Face, Claude, Ollama Cloud, accesso Microsoft 365) entrano nel backup solo CIFRATI con
la password dei backup (AES-256-GCM, chiave da scrypt); senza password impostata restano fuori. Mai nei backup:
abbinamenti con l'iPhone, registri, sessioni Live in corso.

Dove: una cartella a scelta. Argo trova da solo le cartelle sincronizzate di OneDrive e Google Drive per desktop
(Mac: ~/Library/CloudStorage; Windows: variabili OneDrive e unità/cartelle di Google Drive): niente accessi nuovi,
ci pensa l'app di sincronizzazione. Scrivere lì è un'uscita: finisce in «Cosa è uscito da questo computer».
L'IT può vietare le cartelle cloud con il criterio «backup_nel_cloud»: false.

Configurazione condivisa (automatica): un file «configurazione-condivisa.json» nella cartella scelta. All'avvio
Argo la legge e, se è più recente, la applica; alla chiusura scrive la propria se è cambiata. Le impostazioni del
singolo computer (modelli e indirizzo di Ollama, modello e calcolo della trascrizione, audio, uso del computer,
cartelle, canale) non si condividono mai. Criterio IT: «condivisione_configurazione»: false.
Solo libreria standard.
"""
import csv
import hashlib
import io
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import criteri
import uscite
import voci_core as core

log = logging.getLogger("argo")

LIVELLI = {"configurazione": "Configurazione", "completo": "Completo"}
SOTTOCARTELLA = "Argo"
FILE_CONDIVISO = "configurazione-condivisa.json"
PREFISSO = "Argo-backup"

# impostazioni che dipendono dal computer: non si condividono e, da un altro computer, non si ripristinano
PER_COMPUTER = {
    "ollama_url", "modello_chat", "modello_embed", "modello_vision", "modello_dettatura", "modello_live",
    "model", "device", "risorse", "registra_microfono", "registra_sistema", "registra_volume_mic",
    "registra_volume_sistema", "cartella_registrazioni", "canale_aggiornamenti", "trace", "id_computer",
    "modelli_consigliati_rifiutati", "modello_leggero_rifiutato", "backup_cartella", "backup_alla_chiusura",
    "backup_periodico", "backup_conserva", "backup_ultimo", "condivisione_attiva", "condivisione_cartella",
    "condivisione_impronta", "condivisione_letta",
}
# dati del backup completo (cartelle e file dentro la cartella dati di Argo)
DATI = ["voci", "incontri", "clienti", "secondo_cervello", "documenti_indice.json", "documenti_indice.npy",
        "trascrittore_coda.json", "incontri_coda.json"]
GLOSSARIO = "glossario.csv"


class ErroreBackup(RuntimeError):
    pass


# ---------------------------------------------------------------- identità del computer
def id_computer():
    """Identificativo casuale di questo computer (non è il nome né un dato dell'hardware)."""
    s = core.carica_impostazioni()
    if not s.get("id_computer"):
        s["id_computer"] = uuid.uuid4().hex[:12]
        core.salva_impostazioni(s)
    return s["id_computer"]


def nome_computer():
    return (platform.node() or "computer").split(".")[0][:40]


# ---------------------------------------------------------------- cartelle (locali e sincronizzate)
def _cartelle_mac():
    base = Path.home() / "Library" / "CloudStorage"
    trovate = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.name.startswith("OneDrive"):
                trovate.append(("OneDrive" + (f" · {d.name.split('-', 1)[1]}" if "-" in d.name else ""), d))
            elif d.name.startswith("GoogleDrive"):
                mio = next((d / n for n in ("Il mio Drive", "My Drive", "Mein Ablage", "Mon Drive") if (d / n).is_dir()), d)
                trovate.append(("Google Drive" + (f" · {d.name.split('-', 1)[1]}" if "-" in d.name else ""), mio))
    return trovate


def _cartelle_windows():
    trovate, viste = [], set()
    for var, nome in (("OneDriveCommercial", "OneDrive aziendale"), ("OneDriveConsumer", "OneDrive personale"),
                      ("OneDrive", "OneDrive")):
        p = os.environ.get(var)
        if p and Path(p).is_dir() and Path(p).resolve() not in viste:
            viste.add(Path(p).resolve())
            trovate.append((nome, Path(p)))
    candidati = [Path.home() / "Google Drive"] + [Path(f"{u}:\\") for u in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    for c in candidati:
        for n in ("Il mio Drive", "My Drive"):
            if (c / n).is_dir():
                trovate.append(("Google Drive", c / n))
                break
    return trovate


def cartelle_cloud():
    """[(etichetta, percorso)] delle cartelle sincronizzate di OneDrive e Google Drive trovate su questo computer."""
    try:
        return _cartelle_mac() if sys.platform == "darwin" else _cartelle_windows() if os.name == "nt" else []
    except OSError:
        return []


def cartella_locale():
    """Documenti › Argo › Backup; se Documenti è dentro OneDrive (Windows con le cartelle spostate nel cloud) e
    l'IT vieta il cloud, la cartella dati di Argo."""
    documenti = Path.home() / "Documents" / SOTTOCARTELLA / "Backup"
    if cloud_vietato() and nel_cloud(Path.home() / "Documents"):
        return core.APP_HOME / "backup"
    return documenti


def nel_cloud(cartella):
    """Etichetta del servizio cloud se la cartella è dentro una cartella sincronizzata, altrimenti ''."""
    try:
        c = Path(cartella).resolve()
    except OSError:
        return ""
    for etichetta, base in cartelle_cloud():
        try:
            c.relative_to(base.resolve())
            return etichetta
        except (ValueError, OSError):
            continue
    testo = str(c).lower()
    for segno, nome in (("onedrive", "OneDrive"), ("googledrive", "Google Drive"), ("google drive", "Google Drive"),
                        ("dropbox", "Dropbox"), ("mobile documents", "iCloud Drive"), ("icloud", "iCloud Drive")):
        if segno in testo:
            return nome
    return ""


def cloud_vietato():
    return criteri.carica().get("backup_nel_cloud") is False


def condivisione_vietata():
    return criteri.carica().get("condivisione_configurazione") is False or cloud_vietato()


def cartella_backup():
    s = core.carica_impostazioni()
    c = Path(s["backup_cartella"]) if s.get("backup_cartella") else cartella_locale()
    if cloud_vietato() and nel_cloud(c):
        return cartella_locale()
    return c


def _controlla_destinazione(cartella, cosa):
    servizio = nel_cloud(cartella)
    if servizio and cloud_vietato():
        raise ErroreBackup("Le cartelle cloud sono disattivate dai criteri della tua azienda: scegli una cartella "
                           "su questo computer.")
    Path(cartella).mkdir(parents=True, exist_ok=True)
    if servizio:
        uscite.registra(f"{servizio} (cartella sincronizzata)", cosa)


# ---------------------------------------------------------------- impostazioni da condividere
def impostazioni_condivise(s=None):
    s = dict(s or core.carica_impostazioni())
    return {k: v for k, v in s.items() if k not in PER_COMPUTER}


def _glossario_testo():
    f = core.APP_HOME / GLOSSARIO
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        return ""


def impronta(condivise, glossario):
    dati = json.dumps(condivise, sort_keys=True, ensure_ascii=False) + "\n" + (glossario or "")
    return hashlib.sha256(dati.encode("utf-8")).hexdigest()[:16]


def _versione():
    import disinstalla
    return disinstalla.versione()


# ---------------------------------------------------------------- chiavi e token, cifrati
# Decisione di Luca (20/11/2026): nel backup anche chiavi e token, cifrati con una password scelta da lui.
# La password non si salva: si salva solo la chiave che ne deriva (scrypt), in un file locale con permessi 600,
# mai nei backup e mai condiviso. Così anche i backup automatici (alla chiusura, periodici) portano le chiavi,
# e chi trova il file nel cloud senza la password non le legge. Su un altro computer serve la password.
SEGRETI = [".hf_token", ".chiavi_cloud.json", ".ollama_web_key", "m365_token.bin"]
FILE_CHIAVE_BACKUP = core.APP_HOME / ".chiave_backup.json"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def _deriva(password, sale, n=SCRYPT["n"], r=SCRYPT["r"], p=SCRYPT["p"]):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=sale, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def imposta_password(password):
    """Imposta (o cambia) la password dei backup. Ritorna True. password vuota = niente chiavi nei backup."""
    if not password:
        FILE_CHIAVE_BACKUP.unlink(missing_ok=True)
        return False
    if len(password) < 8:
        raise ErroreBackup("La password deve avere almeno 8 caratteri.")
    import base64
    sale = os.urandom(16)
    dati = {"sale": base64.b64encode(sale).decode(), **SCRYPT,
            "chiave": base64.b64encode(_deriva(password, sale)).decode()}
    core.APP_HOME.mkdir(parents=True, exist_ok=True)
    FILE_CHIAVE_BACKUP.write_text(json.dumps(dati), encoding="utf-8")
    try:
        os.chmod(FILE_CHIAVE_BACKUP, 0o600)
    except OSError:
        pass
    return True


def password_impostata():
    return FILE_CHIAVE_BACKUP.exists()


def _cifra_segreti():
    """Il pacchetto cifrato dei segreti presenti, o None se manca la password o non ci sono segreti."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        k = json.loads(FILE_CHIAVE_BACKUP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    contenuto = {n: base64.b64encode((core.APP_HOME / n).read_bytes()).decode()
                 for n in SEGRETI if (core.APP_HOME / n).is_file()}
    if not contenuto:
        return None
    nonce = os.urandom(12)
    cifrato = AESGCM(base64.b64decode(k["chiave"])).encrypt(nonce, json.dumps(contenuto).encode(), b"argo-segreti")
    return {"kdf": "scrypt", "sale": k["sale"], "n": k["n"], "r": k["r"], "p": k["p"],
            "nonce": base64.b64encode(nonce).decode(), "dati": base64.b64encode(cifrato).decode(),
            "file": sorted(contenuto)}


def _decifra_segreti(pacchetto, password=None):
    """Ritorna {nome file: byte}. Prova prima la chiave salvata su questo computer, poi la password."""
    import base64
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    chiavi = []
    try:
        locale = json.loads(FILE_CHIAVE_BACKUP.read_text(encoding="utf-8"))
        if locale.get("sale") == pacchetto["sale"]:
            chiavi.append(base64.b64decode(locale["chiave"]))
    except (OSError, json.JSONDecodeError):
        pass
    if password:
        chiavi.append(_deriva(password, base64.b64decode(pacchetto["sale"]), pacchetto["n"], pacchetto["r"],
                              pacchetto["p"]))
    for k in chiavi:
        try:
            chiaro = AESGCM(k).decrypt(base64.b64decode(pacchetto["nonce"]), base64.b64decode(pacchetto["dati"]),
                                       b"argo-segreti")
            return {n: base64.b64decode(v) for n, v in json.loads(chiaro).items() if n in SEGRETI}
        except InvalidTag:
            continue
    raise ErroreBackup("Password sbagliata: chiavi e token non ripristinati." if password else "SERVE_PASSWORD")


def segreti_nel_backup(file_zip):
    try:
        with zipfile.ZipFile(file_zip) as z:
            return json.loads(z.read("segreti.cifrati")).get("file", [])
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return []


def serve_password(file_zip):
    """True se il backup ha chiavi cifrate che la chiave di questo computer non apre."""
    try:
        with zipfile.ZipFile(file_zip) as z:
            pacchetto = json.loads(z.read("segreti.cifrati"))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return False
    try:
        _decifra_segreti(pacchetto)
        return False
    except ErroreBackup:
        return True


# ---------------------------------------------------------------- backup
def _manifesto(livello, contenuto):
    return {"argo": "backup", "formato": 1, "livello": livello, "versione_app": _versione(),
            "creato": datetime.now().isoformat(timespec="seconds"), "computer": nome_computer(),
            "id_computer": id_computer(), "sistema": sys.platform, "contenuto": contenuto}


def _nome_file(livello):
    return f"{PREFISSO}-{livello}-{nome_computer()}-{datetime.now():%Y%m%d-%H%M%S}.zip"


def crea(livello="configurazione", cartella=None, stato=lambda _t: None, stop=None):
    """Crea un backup e ritorna il percorso del file .zip. Prima nella cartella temporanea, poi spostato: nella
    cartella sincronizzata non finisce mai un file a metà."""
    if livello not in LIVELLI:
        raise ErroreBackup(f"Livello sconosciuto: {livello}")
    cartella = Path(cartella) if cartella else cartella_backup()
    _controlla_destinazione(cartella, f"backup {LIVELLI[livello].lower()} di Argo")
    s = core.carica_impostazioni()
    contenuto = ["impostazioni"]
    tmp = Path(tempfile.mkdtemp(prefix="argo-backup-"))
    try:
        file_zip = tmp / _nome_file(livello)
        with zipfile.ZipFile(file_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("impostazioni_condivise.json", json.dumps(impostazioni_condivise(s), indent=1, ensure_ascii=False))
            z.writestr("impostazioni_computer.json", json.dumps({k: v for k, v in s.items() if k in PER_COMPUTER},
                                                                 indent=1, ensure_ascii=False))
            if (core.APP_HOME / GLOSSARIO).exists():
                z.write(core.APP_HOME / GLOSSARIO, GLOSSARIO)
                contenuto.append("glossario")
            if livello == "completo":
                for nome in DATI:
                    sorgente = core.APP_HOME / nome
                    if not sorgente.exists():
                        continue
                    stato(f"Copio {nome}…")
                    contenuto.append(nome)
                    file = [sorgente] if sorgente.is_file() else sorted(p for p in sorgente.rglob("*") if p.is_file())
                    for f in file:
                        if stop and stop():
                            raise ErroreBackup("Interrotto.")
                        z.write(f, "dati/" + f.relative_to(core.APP_HOME).as_posix())
            segreti = _cifra_segreti()
            if segreti:
                z.writestr("segreti.cifrati", json.dumps(segreti))
                contenuto.append("chiavi e token (cifrati)")
            z.writestr("argo-backup.json", json.dumps(_manifesto(livello, contenuto), indent=1, ensure_ascii=False))
        stato("Salvo il backup…")
        finale = cartella / file_zip.name
        shutil.move(str(file_zip), str(finale))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    s = core.carica_impostazioni()
    s.setdefault("backup_ultimo", {})[livello] = datetime.now().isoformat(timespec="seconds")
    core.salva_impostazioni(s)
    pulisci(cartella, livello, int(s.get("backup_conserva") or 10))
    log.info("backup %s creato · %s · %d KB", livello, nel_cloud(cartella) or "locale", finale.stat().st_size // 1024)
    return finale


def pulisci(cartella, livello, conserva=10):
    """Tiene gli ultimi `conserva` backup di questo computer per quel livello; quelli degli altri non li tocca."""
    miei = sorted(Path(cartella).glob(f"{PREFISSO}-{livello}-{nome_computer()}-*.zip"), reverse=True)
    for vecchio in miei[max(1, conserva):]:
        try:
            vecchio.unlink()
        except OSError:
            pass


def leggi_manifesto(file_zip):
    try:
        with zipfile.ZipFile(file_zip) as z:
            m = json.loads(z.read("argo-backup.json"))
            return m if m.get("argo") == "backup" else None
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def elenco(cartelle=None):
    """Backup trovati nella cartella scelta e nelle cartelle sincronizzate: [(percorso, manifesto, byte)], dal
    più recente."""
    if cartelle is None:
        cartelle = [cartella_backup()] + ([] if cloud_vietato() else [b / SOTTOCARTELLA / "Backup"
                                                                      for _e, b in cartelle_cloud()])
    trovati, visti = [], set()
    for c in cartelle:
        try:
            candidati = list(Path(c).glob(f"{PREFISSO}-*.zip"))
        except OSError:
            continue
        for f in candidati:
            chiave = f.resolve()
            if chiave in visti:
                continue
            visti.add(chiave)
            m = leggi_manifesto(f)
            if m:
                trovati.append((f, m, f.stat().st_size))
    return sorted(trovati, key=lambda x: x[1].get("creato", ""), reverse=True)


# ---------------------------------------------------------------- ripristino
def ripristina(file_zip, stato=lambda _t: None, anche_computer=None, password=None, segreti=True):
    """Ripristina un backup. Prima fa da solo un backup di sicurezza dello stesso livello (cartella locale).
    anche_computer: True/False per ripristinare anche le impostazioni del singolo computer; None = solo se il
    backup viene da questo stesso computer. Ritorna {"sicurezza": percorso, "livello": …}."""
    m = leggi_manifesto(file_zip)
    if not m:
        raise ErroreBackup("Questo file non è un backup di Argo.")
    if m.get("formato", 1) > 1:
        raise ErroreBackup("Il backup viene da una versione di Argo più recente: aggiorna prima Argo.")
    livello = m.get("livello", "configurazione")
    da_scrivere = {}
    if segreti:  # prima la password: se è sbagliata non si tocca nulla
        with zipfile.ZipFile(file_zip) as z:
            if "segreti.cifrati" in z.namelist():
                da_scrivere = _decifra_segreti(json.loads(z.read("segreti.cifrati")), password)
    stato("Backup di sicurezza dello stato attuale…")
    sicurezza = crea(livello, cartella_locale() / "Prima del ripristino")
    if anche_computer is None:
        anche_computer = m.get("id_computer") == id_computer()
    with zipfile.ZipFile(file_zip) as z:
        nomi = set(z.namelist())
        s = core.carica_impostazioni()
        condivise = json.loads(z.read("impostazioni_condivise.json"))
        for k in [k for k in s if k not in PER_COMPUTER]:
            s.pop(k)
        s.update({k: v for k, v in condivise.items() if k not in PER_COMPUTER})
        if anche_computer and "impostazioni_computer.json" in nomi:
            locali = json.loads(z.read("impostazioni_computer.json"))
            for k, v in locali.items():
                if k in PER_COMPUTER and not k.startswith(("backup_", "condivisione_")) and k != "id_computer":
                    s[k] = v
        core.salva_impostazioni(s)
        if GLOSSARIO in nomi:
            (core.APP_HOME / GLOSSARIO).write_bytes(z.read(GLOSSARIO))
        ripristinati = []
        if da_scrivere:
            stato("Ripristino chiavi e token…")
            for nome, dati in da_scrivere.items():
                f = core.APP_HOME / nome
                f.write_bytes(dati)
                try:
                    os.chmod(f, 0o600)
                except OSError:
                    pass
                ripristinati.append(nome)
        if livello == "completo":
            for nome in DATI:
                prefisso = f"dati/{nome}"
                membri = [n for n in nomi if n == prefisso or n.startswith(prefisso + "/")]
                if not membri:
                    continue
                stato(f"Ripristino {nome}…")
                destinazione = core.APP_HOME / nome
                if destinazione.is_dir():
                    shutil.rmtree(destinazione)
                elif destinazione.exists():
                    destinazione.unlink()
                for n in membri:
                    rel = Path(n).relative_to("dati")
                    if ".." in rel.parts or rel.is_absolute():
                        continue  # mai fuori dalla cartella dati
                    obiettivo = core.APP_HOME / rel
                    obiettivo.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as sorgente, open(obiettivo, "wb") as uscita:
                        shutil.copyfileobj(sorgente, uscita)
    log.info("ripristinato backup %s del %s da %s", livello, m.get("creato"), m.get("computer"))
    return {"sicurezza": sicurezza, "livello": livello, "computer": m.get("computer"), "creato": m.get("creato"),
            "segreti": ripristinati}


# ---------------------------------------------------------------- configurazione condivisa
def file_condiviso():
    s = core.carica_impostazioni()
    base = Path(s["condivisione_cartella"]) if s.get("condivisione_cartella") else None
    return base / FILE_CONDIVISO if base else None


def condivisione_attiva():
    s = core.carica_impostazioni()
    return bool(s.get("condivisione_attiva")) and bool(s.get("condivisione_cartella")) and not condivisione_vietata()


def leggi_condivisa():
    """All'avvio, prima di aprire la finestra: applica la configurazione condivisa se è cambiata da un altro
    computer. Ritorna il nome del computer da cui arriva, o '' se non ha cambiato nulla."""
    if not condivisione_attiva():
        return ""
    f = file_condiviso()
    try:
        dati = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""
    s = core.carica_impostazioni()
    if dati.get("impronta") in (None, s.get("condivisione_impronta")) or dati.get("id_computer") == id_computer():
        return ""
    locali = impostazioni_condivise(s)
    if impronta(locali, _glossario_testo()) != s.get("condivisione_impronta") and s.get("condivisione_impronta"):
        # cambiata anche qui dall'ultima volta: vince la più recente, ma la nostra resta in un backup
        try:
            crea("configurazione", cartella_locale() / "Prima della sincronizzazione")
        except Exception as e:
            log.warning("backup prima della sincronizzazione non riuscito: %s", e)
    for k in [k for k in s if k not in PER_COMPUTER]:
        s.pop(k)
    s.update({k: v for k, v in (dati.get("impostazioni") or {}).items() if k not in PER_COMPUTER})
    s["condivisione_impronta"] = dati["impronta"]
    s["condivisione_letta"] = datetime.now().isoformat(timespec="seconds")
    core.salva_impostazioni(s)
    if dati.get("glossario") is not None:
        (core.APP_HOME / GLOSSARIO).write_text(dati["glossario"], encoding="utf-8")
    log.info("configurazione condivisa applicata (da %s, %s)", dati.get("computer"), dati.get("aggiornata"))
    return dati.get("computer") or "un altro computer"


def scrivi_condivisa(forza=False):
    """Alla chiusura (o con «Sincronizza ora»): pubblica la configurazione di questo computer se è cambiata.
    Ritorna True se ha scritto."""
    if not condivisione_attiva():
        return False
    s = core.carica_impostazioni()
    condivise, glossario = impostazioni_condivise(s), _glossario_testo()
    nuova = impronta(condivise, glossario)
    if not forza and nuova == s.get("condivisione_impronta"):
        return False
    f = file_condiviso()
    _controlla_destinazione(f.parent, "configurazione condivisa di Argo")
    dati = {"argo": "configurazione-condivisa", "formato": 1, "impronta": nuova,
            "aggiornata": datetime.now().isoformat(timespec="seconds"), "computer": nome_computer(),
            "id_computer": id_computer(), "versione_app": _versione(),
            "impostazioni": condivise, "glossario": glossario}
    tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dati, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
    s["condivisione_impronta"] = nuova
    core.salva_impostazioni(s)
    log.info("configurazione condivisa pubblicata")
    return True


def stato_condivisa():
    """(computer, quando) dell'ultima configurazione condivisa, o None."""
    f = file_condiviso() if condivisione_attiva() else None
    try:
        dati = json.loads(f.read_text(encoding="utf-8"))
        return dati.get("computer"), dati.get("aggiornata")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------- programmazione
PERIODI = {"": 0, "giorno": 86400, "settimana": 7 * 86400}


def da_fare_periodico():
    """Livello del backup periodico da fare adesso, o ''."""
    s = core.carica_impostazioni()
    periodo, livello = PERIODI.get(s.get("backup_periodico") or "", 0), s.get("backup_periodico_livello") or "configurazione"
    if not periodo:
        return ""
    ultimo = (s.get("backup_ultimo") or {}).get(livello)
    try:
        trascorso = time.time() - datetime.fromisoformat(ultimo).timestamp() if ultimo else periodo + 1
    except ValueError:
        trascorso = periodo + 1
    return livello if trascorso >= periodo else ""


def glossario_righe(testo):
    """Utilità per le prove: righe del glossario."""
    return list(csv.reader(io.StringIO(testo)))
