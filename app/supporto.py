"""supporto.py - «Chiedi supporto», finestra d'errore, avvio protetto e riquadri «Supporto» delle Impostazioni.

Il pacchetto di supporto si prepara su questo computer e l'utente lo vede, file per file, prima di mandarlo.
Non c'è nessun server: si allega a una mail per supporto@argo-net.it. Il supporto lo dà Luca (Argos New Dreams)
senza tempi garantiti: Argo è un esperimento.
"""
import json
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QWidget,
)

import diagnostica
import uscite

INDIRIZZO = "supporto@argo-net.it"
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O e 1/I: si legge e si detta senza equivoci
URGENZE = ["Bassa · quando puoi", "Normale", "Alta · mi blocca il lavoro"]
# Impostazioni che vanno nel pacchetto così come sono: tecniche, senza contenuti. Delle altre si dice solo se sono
# impostate (per esempio le parole chiave, il microfono, le cartelle, gli account).
IMPOSTAZIONI_TECNICHE = {
    "model", "language", "device", "soglia", "modello_chat", "modello_embed", "modello_dettatura", "modello_live",
    "controlla_aggiornamenti", "tema", "risorse", "registra_sistema", "registra_volume_mic",
    "registra_volume_sistema", "canale_aggiornamenti", "registrazione_modo", "modello_vision",
}


def codice_richiesta():
    return "ARGO-" + time.strftime("%Y%m%d") + "-" + "".join(secrets.choice(ALFABETO) for _ in range(4))


def _versione():
    return diagnostica.versione_di(diagnostica.CARTELLA_APP) or "?"


def _impostazioni():
    try:
        import voci_core as core
        imp = core.carica_impostazioni()
    except Exception as e:
        return {"errore": f"impostazioni non leggibili: {type(e).__name__}"}
    out = {}
    for k, v in sorted(imp.items()):
        if k in IMPOSTAZIONI_TECNICHE or isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            out[k] = v
        elif k == "ollama_url":
            out[k] = v if isinstance(v, str) and ("localhost" in v or "127.0.0.1" in v) else "<indirizzo remoto>"
        else:
            out[k] = "<impostato>" if v not in ("", None, [], {}) else "<vuoto>"
    return json.loads(diagnostica.maschera(json.dumps(out, ensure_ascii=False)))


def _ollama():
    d = {}
    try:
        import modelli_ollama
        d["installato"] = modelli_ollama.installato()
    except Exception as e:
        d["installato"] = f"non verificabile ({type(e).__name__})"
    try:
        import llm_locale
        import voci_core as core
        url = core.carica_impostazioni().get("ollama_url", llm_locale.DEFAULT_URL)
        dim = llm_locale.dimensioni(url)
        d["risponde"] = bool(dim) or bool(llm_locale.elenco_modelli(url)[0])
        d["modelli"] = {n: llm_locale.etichetta(n, b) for n, b in sorted(dim.items())}
    except Exception as e:
        d["risponde"] = False
        d["errore"] = diagnostica.maschera(str(e))[:200]
    return d


def _librerie():
    try:
        from importlib import metadata
        nomi = sorted({f"{(m.metadata['Name'] or '?')}=={m.version}" for m in metadata.distributions()},
                      key=str.lower)
        return "\n".join(nomi) + "\n"
    except Exception as e:
        return f"elenco non disponibile: {type(e).__name__}\n"


def sistema():
    d = {"versione": _versione(), "quando": time.strftime("%Y-%m-%d %H:%M"), "sessione": diagnostica.SESSIONE}
    d.update(diagnostica.descrizione_sistema(completa=True))
    try:
        import aggiornamenti
        import criteri
        import voci_core as core
        crit = criteri.carica()
        d["canale"] = aggiornamenti.canale_effettivo(core.carica_impostazioni(), crit)
        d["criteri_aziendali"] = crit
        d["ultimo_aggiornamento"] = json.loads(
            (diagnostica.CARTELLA_APP.parent / "ultimo_aggiornamento.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    attiva, motivo, fino = diagnostica.stato_trace()
    d["trace"] = {"attiva": attiva, "motivo": motivo,
                  "fino": time.strftime("%Y-%m-%d %H:%M", time.localtime(fino)) if fino else None}
    d["modalita_sicura"] = diagnostica.MODALITA_SICURA
    d["avvii_non_riusciti"] = diagnostica.avvii_non_riusciti()
    d["versione_precedente_salvata"] = diagnostica.versione_precedente()
    d["ollama"] = _ollama()
    return json.loads(diagnostica.maschera(json.dumps(d, ensure_ascii=False, default=str)))


def contenuti(richiesta, con_log=True, schermata=None):
    """Elenco dei file del pacchetto: [(nome, byte, descrizione)]. Tutto mascherato, niente chiavi e token."""
    righe = [f"Codice: {richiesta['codice']}", f"Urgenza: {richiesta.get('urgenza', '')}", "",
             "Cosa stavi facendo:", richiesta.get("facendo", "").strip(), "",
             "Cosa ti aspettavi:", richiesta.get("aspettavi", "").strip(), "",
             "Cosa è successo:", richiesta.get("successo", "").strip(), ""]
    out = [("richiesta.txt", "\n".join(righe).encode("utf-8"), "Le tue risposte, come le hai scritte"),
           ("sistema.json", json.dumps(sistema(), indent=2, ensure_ascii=False).encode("utf-8"),
            "Versione, canale, sistema operativo, CPU, RAM, uso del computer, stato di Ollama e modelli"),
           ("impostazioni.json", json.dumps(_impostazioni(), indent=2, ensure_ascii=False).encode("utf-8"),
            "Impostazioni tecniche; delle altre solo «impostato» o «vuoto». Mai token e chiavi"),
           ("librerie.txt", _librerie().encode("utf-8"), "Librerie Python installate e versioni")]
    if con_log:
        for f in diagnostica.file_di_log(3):
            try:
                testo = diagnostica.maschera(f.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            out.append(("log/" + f.name, testo.encode("utf-8"), "Registro degli ultimi 3 giorni (solo dati tecnici)"))
    if schermata:
        out.append(("schermata.png", schermata, "Schermata della finestra di Argo: controlla che non mostri "
                                                "dati riservati"))
    return out


def cartella_destinazione():
    for p in (Path.home() / "Desktop", Path.home() / "Scrivania", Path.home() / "Downloads"):
        if p.is_dir():
            return p
    return Path.home()


def crea_zip(file, codice, cartella=None):
    cartella = Path(cartella or cartella_destinazione())
    dest = cartella / f"argo-supporto-{time.strftime('%Y%m%d-%H%M')}-{codice[-4:]}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dati, _ in file:
            z.writestr(nome, dati)
    diagnostica.log.info("pacchetto di supporto %s creato · %d file · %.0f kB", codice, len(file),
                         dest.stat().st_size / 1024)
    return dest


def testo_mail(richiesta, zip_path):
    corpo = (f"Codice della richiesta: {richiesta['codice']}\nUrgenza: {richiesta.get('urgenza', '')}\n"
             f"Versione di Argo: {_versione()} · {platform.system()} {platform.release()}\n\n"
             f"Cosa stavo facendo:\n{richiesta.get('facendo', '').strip()}\n\n"
             f"Cosa mi aspettavo:\n{richiesta.get('aspettavi', '').strip()}\n\n"
             f"Cosa è successo:\n{richiesta.get('successo', '').strip()}\n\n"
             + (f"In allegato il pacchetto di supporto «{zip_path.name}» (è in {zip_path.parent.name}).\n"
                if zip_path else ""))
    oggetto = f"[{richiesta['codice']}] Argo · richiesta di supporto"
    return oggetto, corpo


def apri_mail(richiesta, zip_path):
    """Solo testo: un link mailto: non può portare allegati."""
    oggetto, corpo = testo_mail(richiesta, zip_path)
    url = f"mailto:{INDIRIZZO}?subject={urllib.parse.quote(oggetto)}&body={urllib.parse.quote(corpo)}"
    return QDesktopServices.openUrl(QUrl(url))


# ---------------------------------------------------------------------- invio con l'allegato
# Un link mailto: non può allegare file. Per allegare il pacchetto Argo usa un programma di posta che sa farlo:
# Outlook con Microsoft 365 (bozza via Graph), Mail di macOS (AppleScript), Outlook classico su Windows (COM).
_SCRIPT_MAIL = """on run argv
    set {oggetto, corpo, destinatario, percorso} to argv
    set allegato to POSIX file percorso
    tell application "Mail"
        set m to make new outgoing message with properties {subject:oggetto, content:corpo & return & return, visible:true}
        tell m
            make new to recipient at end of to recipients with properties {address:destinatario}
            make new attachment with properties {file name:allegato} at after the last paragraph
        end tell
        activate
    end tell
end run"""

_SCRIPT_OUTLOOK = """$ErrorActionPreference = 'Stop'
$o = New-Object -ComObject Outlook.Application
$m = $o.CreateItem(0)
$m.To = $env:ARGO_A
$m.Subject = $env:ARGO_OGGETTO
$m.Body = $env:ARGO_CORPO
[void]$m.Attachments.Add($env:ARGO_FILE)
$m.Display()"""


def _m365_collegato():
    try:
        import m365
        return bool(m365.configurato() and m365.account())
    except Exception:
        return False


def _outlook_classico():
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"))
        return True
    except Exception:
        return False


def modi_di_invio():
    """[(chiave, etichetta)] dal più comodo; l'ultimo c'è sempre."""
    modi = []
    if _m365_collegato():
        modi.append(("m365", "Outlook · Microsoft 365: bozza con il pacchetto già allegato"))
    if sys.platform == "darwin" and Path("/System/Applications/Mail.app").exists():
        modi.append(("mail_mac", "Mail di macOS: mail con il pacchetto già allegato"))
    if _outlook_classico():
        modi.append(("outlook_win", "Outlook classico: mail con il pacchetto già allegato"))
    modi.append(("mailto", "Altro programma di posta: alleghi tu il pacchetto"))
    return modi


def invia(modo, richiesta, zip_path):
    """Prepara la mail per supporto@argo-net.it. Ritorna (allegato_già_messo, messaggio per l'utente).
    Non invia mai da solo: l'ultimo clic su «Invia» resta all'utente."""
    oggetto, corpo = testo_mail(richiesta, zip_path)
    if modo == "m365":
        import m365
        link = m365.bozza_con_allegato(INDIRIZZO, oggetto, corpo, str(zip_path))
        if link:
            QDesktopServices.openUrl(QUrl(link))
        return True, ("Ho creato la bozza in Outlook (cartella Bozze) con il pacchetto allegato e l'ho aperta in "
                      "Outlook sul web. Controllala e premi Invia.")
    if modo == "mail_mac":
        r = subprocess.run(["/usr/bin/osascript", "-e", _SCRIPT_MAIL, oggetto, corpo, INDIRIZZO, str(zip_path)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:] or f"osascript ha risposto {r.returncode}")
        return True, ("Si è aperta una mail in Mail con il pacchetto allegato: controllala e premi Invia. "
                      "La prima volta macOS chiede se Argo può controllare Mail: serve per allegare il file.")
    if modo == "outlook_win":
        env = dict(os.environ, ARGO_A=INDIRIZZO, ARGO_OGGETTO=oggetto, ARGO_CORPO=corpo, ARGO_FILE=str(zip_path))
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT_OUTLOOK],
                           capture_output=True, text=True, timeout=90, env=env, creationflags=0x08000000)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:] or f"PowerShell ha risposto {r.returncode}")
        return True, "Si è aperta una mail in Outlook con il pacchetto allegato: controllala e premi Invia."
    apri_mail(richiesta, zip_path)
    return False, (f"Ho aperto una mail per {INDIRIZZO} con il codice {richiesta['codice']}. Un link di posta "
                   "non può portare allegati: trascina nella mail il pacchetto che ti ho mostrato e invia. Se non "
                   "si è aperto nessun programma di posta, scrivi a quell'indirizzo e allega il file.")


def mostra_nel_finder(percorso):
    p = str(percorso)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", "-R", p])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", p])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))


# ====================================================================== dialogo «Chiedi supporto»
class DialogoSupporto(QDialog):
    """Due passi: 1) la richiesta, 2) cosa c'è nel pacchetto (si vede ogni file e si può togliere)."""

    def __init__(self, parent=None, successo="", schermata=None):
        super().__init__(parent)
        self.setWindowTitle("🛟 Chiedi supporto")
        self.resize(820, 600)
        self.codice = codice_richiesta()
        self.schermata = schermata
        self.file = []
        self.pile = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.pile, 1)

        # Passo 1: la richiesta
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        intro = QLabel(f"Codice della richiesta: <b>{self.codice}</b> · citalo nelle risposte.<br>"
                       f"La richiesta arriva a <b>{INDIRIZZO}</b>. Risponde Luca, al meglio delle possibilità: "
                       "Argo è un esperimento e non ci sono tempi garantiti.")
        intro.setWordWrap(True)
        l1.addWidget(intro)
        f = QFormLayout()
        self.e_facendo = QPlainTextEdit()
        self.e_facendo.setPlaceholderText("Es.: trascrivevo un file di un'ora con il modello large-v3")
        self.e_aspettavi = QPlainTextEdit()
        self.e_aspettavi.setPlaceholderText("Es.: la trascrizione con i nomi dei parlanti")
        self.e_successo = QPlainTextEdit(successo)
        self.e_successo.setPlaceholderText("Es.: dopo l'allineamento si è fermata con «Errore»")
        for e in (self.e_facendo, self.e_aspettavi, self.e_successo):
            e.setMaximumHeight(90)
        self.c_urgenza = QComboBox()
        self.c_urgenza.addItems(URGENZE)
        self.c_urgenza.setCurrentIndex(1)
        f.addRow("Cosa stavi facendo", self.e_facendo)
        f.addRow("Cosa ti aspettavi", self.e_aspettavi)
        f.addRow("Cosa è successo", self.e_successo)
        f.addRow("Urgenza", self.c_urgenza)
        l1.addLayout(f)
        self.cb_log = QCheckBox("Allega i log degli ultimi 3 giorni (solo dati tecnici, li vedi al passo dopo)")
        self.cb_log.setChecked(True)
        self.cb_schermata = QCheckBox("Allega una schermata della finestra di Argo")
        self.cb_schermata.setEnabled(schermata is not None)
        self.cb_schermata.setToolTip("Può mostrare dati riservati: la vedi al passo dopo e puoi toglierla.")
        l1.addWidget(self.cb_log)
        l1.addWidget(self.cb_schermata)
        nota = QLabel("Nel pacchetto non finiscono mai audio, trascrizioni, relazioni, documenti, token e chiavi. "
                      "Nessun invio automatico: al passo dopo vedi ogni file prima di creare il pacchetto.")
        nota.setWordWrap(True)
        nota.setProperty("ruolo", "tenue")
        l1.addWidget(nota)
        l1.addStretch(1)
        self.pile.addWidget(p1)

        # Passo 2: cosa c'è nel pacchetto
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        t2 = QLabel("Questo è il contenuto del pacchetto. Seleziona un file per leggerlo; togli la spunta per "
                    "lasciarlo fuori.")
        t2.setWordWrap(True)
        l2.addWidget(t2)
        div = QSplitter()
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._mostra)
        self.anteprima = QPlainTextEdit()
        self.anteprima.setReadOnly(True)
        self.anteprima.setLineWrapMode(QPlainTextEdit.NoWrap)
        div.addWidget(self.lista)
        div.addWidget(self.anteprima)
        div.setSizes([260, 540])
        l2.addWidget(div, 1)
        r_invio = QHBoxLayout()
        r_invio.addWidget(QLabel("Invia con"))
        self.c_invio = QComboBox()
        for chiave, etichetta in modi_di_invio():
            self.c_invio.addItem(etichetta, chiave)
        r_invio.addWidget(self.c_invio, 1)
        l2.addLayout(r_invio)
        self.pile.addWidget(p2)

        self.bottoni = QDialogButtonBox()
        self.b_indietro = self.bottoni.addButton("← Indietro", QDialogButtonBox.ResetRole)
        self.b_avanti = self.bottoni.addButton("Avanti: vedi il pacchetto →", QDialogButtonBox.AcceptRole)
        self.bottoni.addButton("Annulla", QDialogButtonBox.RejectRole)
        self.b_indietro.hide()
        self.b_indietro.clicked.connect(lambda: self._passo(0))
        self.b_avanti.clicked.connect(self._avanti)
        self.bottoni.rejected.connect(self.reject)
        lay.addWidget(self.bottoni)

    def richiesta(self):
        return {"codice": self.codice, "urgenza": self.c_urgenza.currentText(),
                "facendo": self.e_facendo.toPlainText(), "aspettavi": self.e_aspettavi.toPlainText(),
                "successo": self.e_successo.toPlainText()}

    def _passo(self, n):
        self.pile.setCurrentIndex(n)
        self.b_indietro.setVisible(n == 1)
        self.b_avanti.setText("Avanti: vedi il pacchetto →" if n == 0 else "Crea il pacchetto e scrivi la mail")

    def _avanti(self):
        if self.pile.currentIndex() == 0:
            if not self.e_successo.toPlainText().strip():
                QMessageBox.information(self, "Chiedi supporto", "Scrivi almeno cosa è successo.")
                return
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.file = contenuti(self.richiesta(), self.cb_log.isChecked(),
                                      self.schermata if self.cb_schermata.isChecked() else None)
            finally:
                QApplication.restoreOverrideCursor()
            self.lista.clear()
            for nome, dati, descr in self.file:
                v = QListWidgetItem(f"{nome}  ·  {max(1, len(dati) // 1024)} kB")
                v.setToolTip(descr)
                v.setFlags(v.flags() | Qt.ItemIsUserCheckable)
                v.setCheckState(Qt.Checked)
                self.lista.addItem(v)
            self.lista.setCurrentRow(0)
            self._passo(1)
            return
        scelti = [self.file[i] for i in range(self.lista.count())
                  if self.lista.item(i).checkState() == Qt.Checked]
        try:
            zip_path = crea_zip(scelti, self.codice)
        except Exception as e:
            QMessageBox.warning(self, "Chiedi supporto", f"Non riesco a creare il pacchetto: {e}")
            return
        modo = self.c_invio.currentData()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            allegato, messaggio = invia(modo, self.richiesta(), zip_path)
        except Exception as e:
            diagnostica.log.warning("invio del pacchetto con %s non riuscito: %s", modo, e)
            modo = "mailto"
            allegato, messaggio = invia(modo, self.richiesta(), zip_path)
            messaggio = f"Non sono riuscito a preparare la mail con l'allegato ({e}).\n\n" + messaggio
        finally:
            QApplication.restoreOverrideCursor()
        diagnostica.log.info("richiesta di supporto %s preparata con %s", self.codice, modo)
        if not allegato:
            mostra_nel_finder(zip_path)
        QMessageBox.information(self, "Quasi fatto", f"Pacchetto: «{zip_path.name}» in {zip_path.parent}.\n\n"
                                + messaggio)
        self.accept()

    def _mostra(self, riga):
        if 0 <= riga < len(self.file):
            nome, dati, descr = self.file[riga]
            if nome.endswith(".png"):
                self.anteprima.setPlainText(f"{descr}\n\n(immagine: aprila dal pacchetto per vederla)")
            else:
                testo = dati.decode("utf-8", "replace")
                self.anteprima.setPlainText(f"# {descr}\n\n" + (testo if len(testo) < 400_000
                                                                 else testo[-400_000:]))


def chiedi_supporto(parent=None, successo=""):
    schermata = None
    finestra = parent.window() if parent is not None else None
    if finestra is not None and finestra.isVisible():
        try:
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            finestra.grab().save(buf, "PNG")
            schermata = bytes(buf.data())
        except Exception:
            schermata = None
    DialogoSupporto(parent, successo, schermata).exec()


# ====================================================================== errori e avvio protetto
class _Ponte(QObject):
    errore = Signal(str, str, str)
    uscita = Signal(str)


_ponte = None
_finestra_aperta = False
_ultimi = {}


def collega():
    """Da chiamare nel thread principale, dopo aver creato QApplication."""
    global _ponte
    _ponte = _Ponte()
    _ponte.errore.connect(_mostra, Qt.QueuedConnection)
    _ponte.uscita.connect(_avviso_uscita, Qt.QueuedConnection)
    uscite._avvisa = _ponte.uscita.emit  # i segnali Qt si possono emettere da qualunque thread
    diagnostica.collega_qt(mostra_errore)


def _avviso_uscita(testo):
    f = _finestra_principale()
    if f is not None:
        f.statusBar().showMessage(testo, 8000)
        pannello = getattr(f, "pannello_supporto", None)
        if pannello is not None:
            pannello.aggiorna_uscite()


def mostra_errore(tipo, messaggio, traccia):
    if threading.current_thread() is threading.main_thread():
        _mostra(tipo, messaggio, traccia)
    elif _ponte is not None:
        _ponte.errore.emit(tipo, messaggio, traccia)


def _finestra_principale():
    for w in QApplication.topLevelWidgets():
        if w.isVisible() and w.inherits("QMainWindow"):
            return w
    return None


def _mostra(tipo, messaggio, traccia):
    global _finestra_aperta
    if _finestra_aperta or QApplication.instance() is None:
        return
    if os.environ.get("ARGO_PROVA_AVVIO"):  # prova automatica senza schermo: nessuna finestra da cliccare
        print(f"ERRORE NON GESTITO: {tipo}: {messaggio}", file=sys.stderr, flush=True)
        if _finestra_principale() is None:
            QTimer.singleShot(0, QApplication.instance().quit)
        return
    if time.time() - _ultimi.get(tipo + messaggio, 0) < 30:  # lo stesso errore a raffica: una finestra sola
        return
    _ultimi[tipo + messaggio] = time.time()
    finestra = _finestra_principale()
    all_avvio = finestra is None
    _finestra_aperta = True
    try:
        m = QMessageBox(finestra)
        m.setIcon(QMessageBox.Critical)
        m.setWindowTitle("Argo · errore")
        m.setText(("Argo non è riuscito ad aprirsi." if all_avvio else "Si è verificato un errore imprevisto.")
                  + f"\n\n{tipo}: {messaggio}")
        m.setInformativeText("L'ho scritto nel registro di Argo, solo con dati tecnici. Se si ripete, chiedi "
                             "supporto: prepari un pacchetto che vedi prima di mandarlo.")
        m.setDetailedText(traccia)
        b_sup = m.addButton("🛟 Chiedi supporto…", QMessageBox.ActionRole)
        prec = diagnostica.versione_precedente() if all_avvio else None
        b_prec = m.addButton(f"Torna alla versione {prec}", QMessageBox.ActionRole) if prec else None
        m.addButton("Chiudi Argo" if all_avvio else "Continua", QMessageBox.RejectRole)
        m.exec()
        scelto = m.clickedButton()
        if scelto is b_sup:
            chiedi_supporto(finestra, successo=f"Errore: {tipo}: {messaggio}")
        elif b_prec is not None and scelto is b_prec:
            torna_alla_precedente(finestra, chiedi=False)
    finally:
        _finestra_aperta = False


def finestra_emergenza(tipo, messaggio, traccia):
    """Errore prima che Argo abbia creato la sua finestra: apre Qt solo per mostrarlo."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Argo AI")
    _mostra(tipo, messaggio, traccia)


def torna_alla_precedente(parent=None, chiedi=True):
    v = diagnostica.versione_precedente()
    if not v:
        QMessageBox.information(parent, "Versione precedente", "Non c'è una versione precedente salvata: si crea "
                                "al primo aggiornamento fatto dall'app.")
        return False
    if chiedi and QMessageBox.question(
            parent, "Tornare alla versione precedente?",
            f"Argo torna alla versione {v}, salvata all'ultimo aggiornamento, e si riapre.\n\n"
            "Voci, incontri, impostazioni e dati restano dove sono. La versione attuale resta da parte "
            "(cartella app_scartata). Le librerie Python non cambiano.") != QMessageBox.Yes:
        return False
    try:
        diagnostica.torna_alla_precedente()
    except Exception as e:
        QMessageBox.warning(parent, "Versione precedente", f"Non sono riuscito a tornare indietro: {e}")
        return False
    QMessageBox.information(parent, "Versione precedente",
                            f"Fatto: al prossimo avvio parte la versione {v}. Argo si riapre ora.\n\n"
                            "Se vuoi restare su questa versione per un po', spegni il controllo automatico degli "
                            "aggiornamenti in Impostazioni › Aspetto e aggiornamenti.")
    try:
        import aggiornamenti
        aggiornamenti.riavvia()
    except Exception:
        pass
    app = QApplication.instance()
    if parent is not None and parent.window() is not None and parent.window().isVisible():
        QTimer.singleShot(300, parent.window().close)
    elif app is not None:
        QTimer.singleShot(300, app.quit)
    return True


def chiedi_avvio_protetto(non_riusciti):
    """Dopo avvii non riusciti di fila: 'sicura' | 'normale' | 'precedente' | 'esci'."""
    errore = diagnostica.ultimo_errore()
    prec = diagnostica.versione_precedente()
    m = QMessageBox()
    m.setIcon(QMessageBox.Warning)
    m.setWindowTitle("Argo · avvio protetto")
    m.setText(f"Gli ultimi {non_riusciti} avvii di Argo non sono arrivati alla finestra."
              + (f"\n\nUltimo errore: {errore}" if errore else ""))
    m.setInformativeText("In modalità sicura Argo parte senza Ponte, trascrizione Live, controllo degli "
                         "aggiornamenti e avvio automatico di Ollama: così puoi lavorare o chiedere supporto."
                         + (f"\n\nPuoi anche tornare alla versione {prec}, salvata all'ultimo aggiornamento."
                            if prec else ""))
    b_sicura = m.addButton("Avvia in modalità sicura", QMessageBox.AcceptRole)
    b_prec = m.addButton(f"Torna alla versione {prec}", QMessageBox.ActionRole) if prec else None
    b_norm = m.addButton("Avvia normalmente", QMessageBox.ActionRole)
    m.addButton("Esci", QMessageBox.RejectRole)
    m.setDefaultButton(b_sicura)
    m.exec()
    scelto = m.clickedButton()
    if scelto is b_sicura:
        return "sicura"
    if b_prec is not None and scelto is b_prec:
        return "precedente"
    if scelto is b_norm:
        return "normale"
    return "esci"


# ====================================================================== banda in alto e Impostazioni › Supporto
def _fino(fino):
    if not fino:
        return ""
    giorno = "oggi" if time.localtime(fino).tm_yday == time.localtime().tm_yday else "domani"
    return f"fino a {giorno} alle {time.strftime('%H:%M', time.localtime(fino))}"


class Banda(QFrame):
    """Una riga in cima alla finestra quando la trace è attiva o Argo è in modalità sicura."""

    def __init__(self, finestra):
        super().__init__()
        self.finestra = finestra
        self.setProperty("ruolo", "scheda")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 8, 6)
        self.testo = QLabel()
        self.b_azione = QPushButton()
        self.b_azione.clicked.connect(self._azione)
        lay.addWidget(self.testo, 1)
        lay.addWidget(self.b_azione)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.aggiorna)
        self._timer.start(60_000)  # la trace scade da sola: la banda se ne accorge entro un minuto
        self.aggiorna()

    def aggiorna(self):
        diagnostica._applica_livello()
        attiva, motivo, fino = diagnostica.stato_trace()
        if diagnostica.MODALITA_SICURA:
            self.testo.setText("🛟 Modalità sicura: Ponte, trascrizione Live, aggiornamenti automatici e avvio "
                               "di Ollama sono spenti.")
            self.b_azione.setText("Riavvia normalmente")
            self.b_azione.setVisible(True)
            self._cosa = "riavvia"
        elif attiva:
            quando = {"criteri": "impostata dall'IT", "riga_di_comando": "fino alla chiusura (--trace)"}.get(
                motivo, _fino(fino))
            self.testo.setText(f"🔍 Modalità trace attiva {quando}: log più dettagliati, mai contenuti.")
            self.b_azione.setText("Spegni")
            self.b_azione.setVisible(motivo == "utente")
            self._cosa = "spegni"
        self.setVisible(diagnostica.MODALITA_SICURA or attiva)

    def _azione(self):
        if self._cosa == "spegni":
            diagnostica.imposta_trace(False)
            self.aggiorna()
            agg = getattr(self.finestra, "_aggiorna_supporto", None)
            if agg:
                agg()
        else:
            import aggiornamenti
            aggiornamenti.riavvia()
            QTimer.singleShot(300, self.finestra.close)


class PannelloSupporto(QWidget):
    """Impostazioni › Supporto: richieste di supporto, modalità trace, registro, versione precedente."""

    def __init__(self, finestra):
        super().__init__()
        self.finestra = finestra
        self.gruppi = []

        g = QGroupBox("Chiedi supporto")
        lg = QVBoxLayout(g)
        t = QLabel(f"Prepara un pacchetto con i log e i dati tecnici di questo computer, te lo mostra file per "
                   f"file e apre una mail per {INDIRIZZO} con un codice ARGO-… da citare. Nessun invio automatico. "
                   "Risponde Luca, senza tempi garantiti: Argo è un esperimento.")
        t.setWordWrap(True)
        t.setProperty("ruolo", "tenue")
        lg.addWidget(t)
        r = QHBoxLayout()
        b = QPushButton("🛟 Chiedi supporto…")
        b.setProperty("primario", True)
        b.clicked.connect(lambda: chiedi_supporto(self.finestra))
        r.addWidget(b)
        r.addStretch(1)
        lg.addLayout(r)
        self.gruppi.append(("supporto", g))

        g = QGroupBox("Modalità trace")
        lg = QVBoxLayout(g)
        t = QLabel("Per un problema che si ripete: per un po' Argo scrive nel registro molti più dettagli tecnici "
                   "(righe di WhisperX, richieste a Ollama e ai modelli cloud con tempi e codici, passi degli "
                   "incontri). Mai contenuti. Si spegne da sola.")
        t.setWordWrap(True)
        t.setProperty("ruolo", "tenue")
        lg.addWidget(t)
        r = QHBoxLayout()
        self.cb_trace = QCheckBox("Attiva la modalità trace")
        self.c_durata = QComboBox()
        self.c_durata.addItems(["per 24 ore", "fino al prossimo riavvio di Argo (al massimo 24 ore)"])
        r.addWidget(self.cb_trace)
        r.addWidget(self.c_durata)
        r.addStretch(1)
        lg.addLayout(r)
        self.l_trace = QLabel()
        self.l_trace.setProperty("ruolo", "tenue")
        self.l_trace.setWordWrap(True)
        lg.addWidget(self.l_trace)
        self.cb_trace.toggled.connect(self._trace)
        self.gruppi.append(("trace", g))

        g = QGroupBox("Registro di Argo (log)")
        lg = QVBoxLayout(g)
        t = QLabel("Argo tiene un registro su questo computer: avvio e chiusura, versione, sistema, fasi dei lavori "
                   "con durata ed esito, errori, tempi di Ollama e dei modelli cloud (solo fornitore e modello), "
                   "aggiornamenti. Mai audio, testi trascritti, domande e risposte dei modelli, nomi dei tuoi file, "
                   "mail, chiavi e token. Non esce da qui se non lo mandi tu con «Chiedi supporto».")
        t.setWordWrap(True)
        t.setProperty("ruolo", "tenue")
        lg.addWidget(t)
        r = QHBoxLayout()
        b = QPushButton("Apri la cartella dei log")
        b.clicked.connect(self._apri_log)
        r.addWidget(b)
        self.l_log = QLabel()
        self.l_log.setProperty("ruolo", "tenue")
        r.addWidget(self.l_log, 1)
        lg.addLayout(r)
        self.gruppi.append(("log", g))

        g = QGroupBox("Versione precedente")
        lg = QVBoxLayout(g)
        self.l_prec = QLabel()
        self.l_prec.setWordWrap(True)
        self.l_prec.setProperty("ruolo", "tenue")
        lg.addWidget(self.l_prec)
        r = QHBoxLayout()
        self.b_prec = QPushButton()
        self.b_prec.clicked.connect(lambda: torna_alla_precedente(self.finestra))
        r.addWidget(self.b_prec)
        r.addStretch(1)
        lg.addLayout(r)
        self.gruppi.append(("precedente", g))

        g = QGroupBox("Cosa è uscito da questo computer")
        lg = QVBoxLayout(g)
        t = QLabel("Di base la conversazione resta qui. Escono solo i dati che decidi tu, e qui c'è l'elenco: verso "
                   "dove e che tipo di dato, mai il contenuto. Per esempio un modello cloud scelto per un attrezzo, "
                   "una ricerca web, una bozza in Outlook, un record in Dynamics. Non compaiono il Ponte verso il "
                   "tuo iPhone (rete locale), i download di modelli e aggiornamenti e le letture da Microsoft 365 e "
                   "Dynamics.")
        t.setWordWrap(True)
        t.setProperty("ruolo", "tenue")
        lg.addWidget(t)
        self.tab_uscite = QTableWidget(0, 4)
        self.tab_uscite.setHorizontalHeaderLabels(["Quando", "Verso", "Che cosa", "Volte"])
        self.tab_uscite.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tab_uscite.verticalHeader().setVisible(False)
        self.tab_uscite.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tab_uscite.setMinimumHeight(220)
        lg.addWidget(self.tab_uscite)
        r = QHBoxLayout()
        b = QPushButton("Aggiorna")
        b.clicked.connect(self.aggiorna_uscite)
        b2 = QPushButton("Svuota l'elenco")
        b2.clicked.connect(self._svuota_uscite)
        r.addWidget(b)
        r.addWidget(b2)
        self.l_uscite = QLabel()
        self.l_uscite.setProperty("ruolo", "tenue")
        r.addWidget(self.l_uscite, 1)
        lg.addLayout(r)
        self.gruppi.insert(0, ("uscite", g))
        self.aggiorna()

    def aggiorna(self):
        attiva, motivo, fino = diagnostica.stato_trace()
        self.cb_trace.blockSignals(True)
        self.cb_trace.setChecked(attiva)
        self.cb_trace.blockSignals(False)
        bloccata = motivo in ("criteri", "riga_di_comando")
        self.cb_trace.setEnabled(not bloccata)
        self.c_durata.setEnabled(not attiva)
        self.l_trace.setText({
            "criteri": "Attivata dall'IT con i criteri aziendali (chiave «trace»): la spegne l'IT.",
            "riga_di_comando": "Attivata con --trace: resta accesa fino alla chiusura di Argo.",
            "utente": f"Attiva {_fino(fino)}." if fino else "",
        }.get(motivo, "Spenta."))
        totale = sum(f.stat().st_size for f in diagnostica.CARTELLA.glob("*.log*")) if diagnostica.CARTELLA.is_dir() else 0
        self.l_log.setText(f"{diagnostica.CARTELLA} · {totale / 1e6:.1f} MB (al massimo circa 20 MB)")
        v = diagnostica.versione_precedente()
        self.l_prec.setText(
            f"All'ultimo aggiornamento dall'app Argo ha salvato la versione {v}. Se quella attuale ti dà problemi "
            "puoi tornarci: i dati restano dove sono." if v else
            "Nessuna versione precedente salvata: Argo ne salva una a ogni aggiornamento fatto dall'app.")
        self.b_prec.setText(f"Torna alla versione {v}…" if v else "Torna alla versione precedente…")
        self.b_prec.setEnabled(bool(v))
        self.aggiorna_uscite()

    def aggiorna_uscite(self):
        righe = uscite.elenco(200)
        self.tab_uscite.setRowCount(len(righe))
        for i, u in enumerate(righe):
            for j, v in enumerate((u.get("quando", ""), u.get("verso", ""), u.get("cosa", ""), str(u.get("volte", 1)))):
                self.tab_uscite.setItem(i, j, QTableWidgetItem(v))
        self.tab_uscite.resizeColumnToContents(0)
        self.tab_uscite.resizeColumnToContents(1)
        self.l_uscite.setText("Nessuna uscita registrata." if not righe else f"Ultime {len(righe)} uscite.")

    def _svuota_uscite(self):
        if QMessageBox.question(self.finestra, "Svuotare l'elenco?", "L'elenco delle uscite si cancella. "
                                "Le prossime uscite verranno registrate di nuovo.") == QMessageBox.Yes:
            uscite.svuota()
            self.aggiorna_uscite()

    def _trace(self, attiva):
        diagnostica.imposta_trace(attiva, al_riavvio=self.c_durata.currentIndex() == 1)
        self.aggiorna()
        banda = getattr(self.finestra, "banda", None)
        if banda:
            banda.aggiorna()

    def _apri_log(self):
        diagnostica.CARTELLA.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(diagnostica.CARTELLA)))

