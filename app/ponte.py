"""ponte.py - Ponte Argo: canale cifrato tra Argo desktop e Argo per iPhone, in rete locale.

Come funziona
- Argo desktop apre un piccolo server HTTPS sulla rete locale (solo mentre Argo è aperto).
- Il certificato è autofirmato e generato sul computer; l'iPhone lo riconosce per impronta (pinning),
  che riceve dal QR code mostrato durante l'abbinamento: niente terze parti, niente cloud.
- Abbinamento: il QR contiene indirizzi, porta, impronta del certificato e un codice monouso (5 minuti).
  L'iPhone lo scambia con un segreto suo; sul computer resta solo l'hash del segreto.
- Ogni richiesta successiva porta il segreto (Authorization: Bearer). Un iPhone si scollega dal computer.

Servizi (v1)
  POST /v1/abbina     {codice, nome}        → {segreto, id, nome}
  GET  /v1/stato                            → {nome, versione, servizi}
  GET  /v1/anagrafe                         → anagrafe voci scelte in Voci › Per iPhone (formato argo.voci)
  POST /v1/incontri   corpo: pacchetto .zip → {ok, id}   (formato argo.sessione, vedi argo-ios)

Cosa NON passa mai: audio (l'iPhone non lo conserva), file fuori dalla cartella degli incontri.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import voci_core as core

CARTELLA = core.APP_HOME / "ponte"
CERT = CARTELLA / "certificato.pem"
CHIAVE = CARTELLA / "chiave.pem"
INCONTRI = core.APP_HOME / "incontri"
PORTA_PREDEFINITA = 47321
DURATA_CODICE = 300          # secondi di validità del codice di abbinamento
MASSIMO_PACCHETTO = 512 * 1024 * 1024
VERSIONE_PROTOCOLLO = 1


class ErrorePonte(Exception):
    pass


# ---------------------------------------------------------------- identità e certificato
def identita():
    """Id stabile e nome di questo computer per il Ponte."""
    s = core.carica_impostazioni()
    if not s.get("ponte_id"):
        s["ponte_id"] = str(uuid.uuid4())
        core.salva_impostazioni(s)
    nome = socket.gethostname().replace(".local", "")
    return s["ponte_id"], nome


def assicura_certificato():
    """Crea (una volta) il certificato autofirmato del Ponte; restituisce l'impronta SHA-256 (hex)."""
    if not (CERT.exists() and CHIAVE.exists()):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        CARTELLA.mkdir(parents=True, exist_ok=True)
        chiave = ec.generate_private_key(ec.SECP256R1())
        _id, nome = identita()
        soggetto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Argo Ponte {nome}")])
        adesso = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(soggetto)
            .issuer_name(soggetto)
            .public_key(chiave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(adesso - timedelta(days=1))
            .not_valid_after(adesso + timedelta(days=3650))
            .sign(chiave, hashes.SHA256())
        )
        CHIAVE.write_bytes(chiave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.chmod(CHIAVE, 0o600)
        CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    der = ssl.PEM_cert_to_DER_cert(CERT.read_text(encoding="ascii"))
    return hashlib.sha256(der).hexdigest()


def indirizzi_locali():
    """Indirizzi IPv4 privati di questo computer + nome .local (in ordine di preferenza)."""
    trovati = []
    try:
        # Indirizzo usato per uscire in rete (non invia nulla: UDP senza pacchetti)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            trovati.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            trovati.append(info[4][0])
    except OSError:
        pass
    privati = []
    for ip in trovati:
        try:
            if ipaddress.ip_address(ip).is_private and not ip.startswith("127.") and ip not in privati:
                privati.append(ip)
        except ValueError:
            pass
    nome = socket.gethostname()
    if not nome.endswith(".local"):
        nome += ".local"
    return privati + [nome]


# ---------------------------------------------------------------- dispositivi abbinati
def dispositivi():
    return core.carica_impostazioni().get("ponte_dispositivi", [])


def _hash(segreto):
    return hashlib.sha256(segreto.encode("utf-8")).hexdigest()


def _registra_dispositivo(nome):
    segreto = secrets.token_urlsafe(32)
    s = core.carica_impostazioni()
    elenco = s.get("ponte_dispositivi", [])
    elenco.append({
        "id": str(uuid.uuid4()),
        "nome": nome[:60] or "iPhone",
        "hash": _hash(segreto),
        "aggiunto": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ultimo_contatto": None,
    })
    s["ponte_dispositivi"] = elenco
    core.salva_impostazioni(s)
    return segreto


def scollega(id_dispositivo):
    s = core.carica_impostazioni()
    s["ponte_dispositivi"] = [d for d in s.get("ponte_dispositivi", []) if d["id"] != id_dispositivo]
    core.salva_impostazioni(s)


def _autenticato(intestazione):
    if not intestazione or not intestazione.startswith("Bearer "):
        return None
    h = _hash(intestazione[7:].strip())
    for d in dispositivi():
        if hmac.compare_digest(d["hash"], h):
            return d
    return None


def _segna_contatto(id_dispositivo):
    s = core.carica_impostazioni()
    for d in s.get("ponte_dispositivi", []):
        if d["id"] == id_dispositivo:
            d["ultimo_contatto"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    core.salva_impostazioni(s)


# ---------------------------------------------------------------- incontri ricevuti
def elenco_incontri():
    """Incontri ricevuti, dal più recente: [(cartella, dati sessione.json)]."""
    if not INCONTRI.exists():
        return []
    out = []
    for c in INCONTRI.iterdir():
        f = c / "sessione.json"
        if c.is_dir() and f.exists():
            try:
                out.append((c, json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                pass
    return sorted(out, key=lambda x: x[1].get("creata", ""), reverse=True)


def importa_pacchetto(percorso_zip, origine="file"):
    """Importa un pacchetto Argo (.zip con sessione.json + foto/). Idempotente sull'id della sessione."""
    with zipfile.ZipFile(percorso_zip) as z:
        nomi = z.namelist()
        guida = next((n for n in nomi if n.endswith("sessione.json") and n.count("/") <= 1), None)
        if not guida:
            raise ErrorePonte("Il file non è un pacchetto Argo (manca sessione.json).")
        radice = guida[: -len("sessione.json")]
        dati = json.loads(z.read(guida).decode("utf-8"))
        if dati.get("formato") != "argo.sessione":
            raise ErrorePonte("Formato del pacchetto non riconosciuto.")
        id_sessione = str(uuid.UUID(str(dati["id"])))  # valida l'id: diventa il nome della cartella
        destinazione = INCONTRI / id_sessione
        temporanea = Path(tempfile.mkdtemp(prefix="argo-incontro-", dir=core.APP_HOME))
        try:
            for n in nomi:
                if not n.startswith(radice) or n.endswith("/"):
                    continue
                relativo = n[len(radice):]
                bersaglio = (temporanea / relativo).resolve()
                # Protezione dai percorsi malevoli (../, assoluti): tutto deve restare nella cartella
                if temporanea.resolve() not in bersaglio.parents:
                    raise ErrorePonte(f"Percorso non ammesso nel pacchetto: {n}")
                bersaglio.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as sorgente, open(bersaglio, "wb") as uscita:
                    shutil.copyfileobj(sorgente, uscita)
            (temporanea / "ricevuto.json").write_text(json.dumps({
                "ricevuto": datetime.now().strftime("%Y-%m-%d %H:%M"), "origine": origine,
            }, ensure_ascii=False), encoding="utf-8")
            INCONTRI.mkdir(parents=True, exist_ok=True)
            if destinazione.exists():
                # Reinvio dello stesso incontro: si tengono i lavori fatti sul computer (relazione, CRM)
                for extra in ("argo-relazione.json", "argo-crm.json"):
                    if (destinazione / extra).exists():
                        shutil.copy2(destinazione / extra, temporanea / extra)
                shutil.rmtree(destinazione)
            temporanea.rename(destinazione)
        finally:
            if temporanea.exists():
                shutil.rmtree(temporanea, ignore_errors=True)
    return id_sessione, dati


# ---------------------------------------------------------------- server
class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, indirizzo, gestore, contesto_tls, ponte):
        self.contesto_tls = contesto_tls
        self.ponte = ponte
        super().__init__(indirizzo, gestore)

    def finish_request(self, request, client_address):
        # Handshake TLS nel thread della singola richiesta, non in quello che accetta le connessioni
        try:
            request.settimeout(30)
            tls = self.contesto_tls.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        self.RequestHandlerClass(tls, client_address, self)


class _Gestore(BaseHTTPRequestHandler):
    server_version = "ArgoPonte/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *argomenti):  # niente log su console con indirizzi e percorsi
        pass

    def _json(self, codice, corpo):
        dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    def _corpo(self, massimo):
        lunghezza = int(self.headers.get("Content-Length") or 0)
        if lunghezza <= 0 or lunghezza > massimo:
            raise ErrorePonte("Dimensione non valida")
        return lunghezza

    def do_GET(self):
        ponte = self.server.ponte
        dispositivo = _autenticato(self.headers.get("Authorization"))
        if not dispositivo:
            return self._json(401, {"errore": "Dispositivo non abbinato"})
        _segna_contatto(dispositivo["id"])
        if self.path == "/v1/stato":
            id_desktop, nome = identita()
            return self._json(200, {"id": id_desktop, "nome": nome, "versione": ponte.versione_app,
                                    "protocollo": VERSIONE_PROTOCOLLO, "servizi": ["anagrafe", "incontri"]})
        if self.path == "/v1/anagrafe":
            scelte = core.carica_impostazioni().get("voci_iphone") or []
            if not scelte:
                return self._json(404, {"errore": "Nessuna voce scelta: Argo › Voci › 📱 Per iPhone…"})
            with tempfile.TemporaryDirectory() as t:
                p, _n = core.esporta_per_iphone(Path(t) / "anagrafe", scelte)
                dati = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(dati)))
            self.end_headers()
            self.wfile.write(dati)
            return None
        return self._json(404, {"errore": "Servizio sconosciuto"})

    def do_POST(self):
        ponte = self.server.ponte
        try:
            if self.path == "/v1/abbina":
                lunghezza = self._corpo(4096)
                richiesta = json.loads(self.rfile.read(lunghezza).decode("utf-8"))
                if not ponte.codice_valido(richiesta.get("codice", "")):
                    return self._json(403, {"errore": "Codice scaduto o non valido: rigenera il QR su Argo"})
                segreto = _registra_dispositivo(str(richiesta.get("nome", "iPhone")))
                ponte.consuma_codice()
                id_desktop, nome = identita()
                ponte.notifica("abbinato", str(richiesta.get("nome", "iPhone")))
                return self._json(200, {"segreto": segreto, "id": id_desktop, "nome": nome})

            dispositivo = _autenticato(self.headers.get("Authorization"))
            if not dispositivo:
                return self._json(401, {"errore": "Dispositivo non abbinato"})
            _segna_contatto(dispositivo["id"])

            if self.path == "/v1/incontri":
                lunghezza = self._corpo(MASSIMO_PACCHETTO)
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=core.APP_HOME) as tmp:
                    rimasti = lunghezza
                    while rimasti > 0:
                        blocco = self.rfile.read(min(1 << 20, rimasti))
                        if not blocco:
                            raise ErrorePonte("Trasferimento interrotto")
                        tmp.write(blocco)
                        rimasti -= len(blocco)
                try:
                    id_sessione, dati = importa_pacchetto(tmp.name, origine=dispositivo["nome"])
                finally:
                    os.unlink(tmp.name)
                ponte.notifica("incontro", dati.get("titolo", id_sessione))
                return self._json(200, {"ok": True, "id": id_sessione})
            return self._json(404, {"errore": "Servizio sconosciuto"})
        except (ErrorePonte, ValueError, KeyError, zipfile.BadZipFile) as e:
            return self._json(400, {"errore": str(e)})


class Ponte:
    """Il server del Ponte. `notifica(tipo, testo)` va collegato all'interfaccia (thread-safe a cura del chiamante)."""

    def __init__(self, versione_app, notifica=None):
        self.versione_app = versione_app
        self.notifica = notifica or (lambda _t, _x: None)
        self._server = None
        self._thread = None
        self._codice = None
        self._scadenza = 0
        self._blocco = threading.Lock()
        self.porta = None

    @property
    def attivo(self):
        return self._server is not None

    def avvia(self):
        if self._server:
            return self.porta
        assicura_certificato()
        contesto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contesto.minimum_version = ssl.TLSVersion.TLSv1_2
        contesto.load_cert_chain(CERT, CHIAVE)
        porta = int(core.carica_impostazioni().get("ponte_porta", PORTA_PREDEFINITA))
        try:
            self._server = _Server(("0.0.0.0", porta), _Gestore, contesto, self)
        except OSError:
            self._server = _Server(("0.0.0.0", 0), _Gestore, contesto, self)  # porta occupata: una libera
        self.porta = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="argo-ponte", daemon=True)
        self._thread.start()
        return self.porta

    def ferma(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- abbinamento
    def nuovo_codice(self):
        with self._blocco:
            self._codice = secrets.token_urlsafe(16)
            self._scadenza = time.time() + DURATA_CODICE
            return self._codice

    def codice_valido(self, codice):
        with self._blocco:
            return bool(self._codice) and time.time() < self._scadenza and hmac.compare_digest(self._codice, codice)

    def consuma_codice(self):
        with self._blocco:
            self._codice = None

    def contenuto_qr(self):
        """Testo del QR: «argo-ponte:» + JSON compatto (indirizzi, porta, impronta del certificato, codice monouso).

        L'impronta è il SHA-256 del certificato in base64url (43 caratteri): l'iPhone la confronta con quella
        del certificato che riceve. Il codice vale 5 minuti e una sola volta.
        """
        _id, nome = identita()
        impronta = base64.urlsafe_b64encode(bytes.fromhex(assicura_certificato())).decode("ascii").rstrip("=")
        dati = {
            "v": VERSIONE_PROTOCOLLO, "n": nome[:40], "p": self.porta,
            "h": indirizzi_locali()[:4], "f": impronta, "c": self.nuovo_codice(),
        }
        return "argo-ponte:" + json.dumps(dati, separators=(",", ":"), ensure_ascii=False)
