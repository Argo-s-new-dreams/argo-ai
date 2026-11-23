"""Argo · Cassetta degli attrezzi AI - trascrittore con anagrafe voci, verbale, documenti riservati, dettatura e traduzione.
Tutto gira in locale: l'audio non lascia il computer.
"""
import json
import logging
import os
import threading
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
VERSIONE = "20261123.1250"
import diagnostica  # noqa: E402  per primo: così finiscono nel registro anche gli errori negli import qui sotto
if __name__ == "__main__":
    diagnostica.inizia(VERSIONE)

from PySide6.QtCore import QPoint, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

import voci_core as core  # noqa: E402
import argo_attrezzi as attrezzi  # noqa: E402
import llm_locale  # noqa: E402
import voci_strumenti  # noqa: E402
import aggiornamenti  # noqa: E402
import criteri  # noqa: E402
import tema  # noqa: E402
import lingua  # noqa: E402
from lingua import tr  # noqa: E402
import dettaglio  # noqa: E402
import m365  # noqa: E402
import risorse  # noqa: E402
import modelli_ollama  # noqa: E402
import cloud  # noqa: E402
import disinstalla  # noqa: E402
import supporto  # noqa: E402
import consenso_voci  # noqa: E402
import veglia  # noqa: E402
import adatta_computer  # noqa: E402
import backup  # noqa: E402
import backup_ui  # noqa: E402
import esporta_trascrizione  # noqa: E402
import secondo_cervello as cervello  # noqa: E402
import secondo_cervello_ui as cervello_ui  # noqa: E402
import cervello_base  # noqa: E402

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
             ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv"}
MODELLI = [
    ("large-v3", "large-v3 - massima qualità (lento)"),
    ("large-v3-turbo", "large-v3-turbo - ottimo compromesso (consigliato)"),
    ("medium", "medium - più veloce"),
    ("small", "small - prove rapide"),
]
LINGUE = [("it", "Italiano"), ("en", "Inglese"), ("de", "Tedesco"), ("fr", "Francese"), ("es", "Spagnolo"), ("", "Rilevamento automatico")]
FASI = {  # testo nel log -> (nome fase, inizio %, fine %)
    "Ricalcolo dei parlanti": ("Ricalcolo parlanti", 5, 98),
    "Performing transcription": ("Trascrizione", 5, 60),
    "Performing alignment": ("Allineamento", 60, 80),
    "Performing diarization": ("Riconoscimento parlanti", 80, 98),
}
RE_PROGRESS = re.compile(r"Progress:\s*([\d.]+)%")
RE_LOG = re.compile(r"^\d{4}-\d{2}-\d{2} ")
RUMORE_RIGHE = ("Lightning automatically upgraded", "Xet Storage is enabled", "symlinks", "Developer Mode",
                "warnings.warn(message)")


class FiltroRumore:
    """Toglie dal registro gli avvisi innocui (torchcodec, Lightning, symlink) lasciando fasi ed errori."""

    def __init__(self):
        self.in_blocco = False

    def e_rumore(self, testo):
        if self.in_blocco:
            if testo.startswith("warnings.warn(") or RE_LOG.match(testo) or "Performing" in testo:
                self.in_blocco = False
                return testo.startswith("warnings.warn(")
            return True
        if (testo.endswith("UserWarning:") and "pyannote" in testo) or "torchcodec is not installed" in testo:
            self.in_blocco = True
            return True
        return any(r in testo for r in RUMORE_RIGHE)


# =============================================================== processo in background
class ProcessWorker(QThread):
    """Esegue un comando in un processo separato e ne inoltra l'output riga per riga."""
    riga = Signal(str)
    finito = Signal(int)

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.proc = None
        self.interrotto = False

    def run(self):
        # niente sospensione automatica finché lavora; profilo Leggero: un lavoro pesante alla volta,
        # e la RAM di Ollama liberata prima di trascrivere
        with veglia.tieni("trascrizione"), risorse.turno(on_attesa=self.riga.emit):
            if self.interrotto:  # «Ferma» premuto mentre aspettava il turno
                self.finito.emit(-1)
                return
            if risorse.profilo() == "leggero":
                risorse.libera_ollama()
            self._esegui()

    def _esegui(self):
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW su Windows
        flags |= risorse.flag_windows()  # priorità sotto il normale: il PC resta reattivo
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=core.env_processo(), creationflags=flags,
                start_new_session=(os.name != "nt"),  # gruppo di processi: si ferma anche ciò che lancia
            )
        except Exception as e:
            self.riga.emit(f"ERRORE avvio processo: {e}")
            self.finito.emit(-1)
            return
        if os.name != "nt":
            risorse.abbassa_priorita(self.proc.pid)
        if self.interrotto:  # «Ferma» premuto prima che il processo partisse
            self._uccidi()
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            parti = re.split(rb"[\r\n]", buf)
            buf = parti.pop()
            for p in parti:
                testo = p.decode("utf-8", "replace").strip()
                if testo:
                    self.riga.emit(testo)
        if buf.strip():
            self.riga.emit(buf.decode("utf-8", "replace").strip())
        self.finito.emit(self.proc.wait())

    def ferma(self):
        self.interrotto = True
        self._uccidi()

    def _uccidi(self):
        """Ferma il processo e i suoi figli; se dopo 3 secondi è ancora vivo, lo chiude d'autorità."""
        p = self.proc
        if not p or p.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                               creationflags=0x08000000)
            else:
                import signal
                os.killpg(p.pid, signal.SIGTERM)

                def forza():
                    if p.poll() is None:
                        try:
                            os.killpg(p.pid, signal.SIGKILL)
                        except Exception:
                            pass
                import threading
                threading.Timer(3.0, forza).start()
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


# =============================================================== dialogo revisione parlanti
class RevisioneDialog(QDialog):
    """Mostra chi è stato riconosciuto, permette di correggere i nomi e memorizzare nuove voci."""

    def __init__(self, file_json, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Revisione parlanti'))
        self.resize(860, 480)
        self.file_json = file_json
        self.dati = core.leggi_json(file_json)
        self.emb = self.dati.get("speaker_embeddings") or {}
        soglia = core.carica_impostazioni()["soglia"]
        if self.emb:
            self.mappa, self.migliori, _ = core.abbina(self.emb, core.carica_voci(), soglia)
        else:
            self.mappa = {s: f"Parlante {i}" for i, s in enumerate(core.parlanti_senza_embedding(self.dati), 1)}
            self.migliori = {}
        for s, n in (self.dati.get(core.NOMI_KEY) or {}).items():  # nomi già corretti in passato
            if s in self.mappa:
                self.mappa[s] = n
        esempi, durate = {}, {}
        for seg in self.dati.get("segments", []):
            s = seg.get("speaker")
            if not s:
                continue
            durate[s] = durate.get(s, 0) + (seg.get("end", 0) - seg.get("start", 0))
            t = (seg.get("text") or "").strip()
            if len(t) > len(esempi.get(s, "")) and len(esempi.get(s, "")) < 60:
                esempi[s] = t
        nomi_noti = [n for n, _ in core.elenco_voci()]

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            tr("Controlla i nomi: puoi correggerli scrivendo o scegliendo dall'elenco. I nomi restano salvati.\nDue etichette sono la stessa persona? Dai loro lo stesso nome e verranno unite.\nMancano persone o ce ne sono troppe? Chiudi e cambia «Partecipanti» nella coda: Argo rifà solo i parlanti.\nSpunta «Memorizza» per salvare l'impronta di quella voce nell'anagrafe: le prossime volte verrà riconosciuta da sola.")))
        self.tab = QTableWidget(len(self.mappa), 5)
        self.tab.setHorizontalHeaderLabels([tr('Etichetta'), tr('Parla per'), tr('Somiglianza'), tr('Nome'), tr('Memorizza'), ])
        self.tab.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tab.verticalHeader().setVisible(False)
        self.righe = []
        for r, spk in enumerate(sorted(self.mappa)):
            self.tab.setItem(r, 0, QTableWidgetItem(spk))
            self.tab.setItem(r, 1, QTableWidgetItem(core.hms(durate.get(spk, 0))))
            best = self.migliori.get(spk)
            self.tab.setItem(r, 2, QTableWidgetItem(f"{best[0]} {best[1]:.2f}" if best else "-"))
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(sorted(set(nomi_noti + [self.mappa[spk]]), key=str.lower))
            combo.setCurrentText(self.mappa[spk])
            combo.setToolTip("Esempio: «" + esempi.get(spk, "")[:200] + "»")
            self.tab.setCellWidget(r, 3, combo)
            chk = QCheckBox()
            chk.setEnabled(spk in self.emb)
            if not self.emb:
                chk.setToolTip(tr('Per memorizzare le voci attiva il riconoscimento delle voci (pagina Voci) e rifai i parlanti'))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(chk, alignment=Qt.AlignCenter)
            self.tab.setCellWidget(r, 4, box)
            self.righe.append((spk, combo, chk))
        lay.addWidget(self.tab)
        self.esempio = QLabel(tr('Passa il mouse su un nome per leggere una frase di quel parlante.'))
        self.esempio.setWordWrap(True)
        lay.addWidget(self.esempio)
        self.tab.cellClicked.connect(lambda r, c: self.esempio.setText(
            f"{self.righe[r][0]}: «{esempi.get(self.righe[r][0], '')[:300]}»"))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr('Applica e salva'))
        bb.accepted.connect(self.applica)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def applica(self):
        nuova, memorizzate, da_memorizzare = {}, [], []
        for spk, combo, chk in self.righe:
            nome = combo.currentText().strip() or self.mappa[spk]
            nuova[spk] = nome
            if chk.isChecked():
                if nome.startswith(("Sconosciuto", "Parlante")) or not core.nome_valido(nome):
                    QMessageBox.warning(self, tr('Nome mancante'), tr('Dai un nome vero a {spk} prima di memorizzarlo.', spk=spk))
                    return
                da_memorizzare.append((spk, nome))
        if da_memorizzare:
            ok = consenso_voci.chiedi([n for _, n in da_memorizzare], self)
            for spk, nome in da_memorizzare:
                if nome in ok:
                    core.salva_impronta(nome, self.emb[spk])
                    memorizzate.append(nome)
        core.salva_nomi(self.file_json, nuova)
        self.dati[core.NOMI_KEY] = nuova
        self.out = core.scrivi_trascrizione(self.dati, nuova, self.file_json)
        msg = f"Trascrizione aggiornata:\n{self.out}"
        if memorizzate:
            msg += "\n\nVoci memorizzate: " + ", ".join(memorizzate)
        QMessageBox.information(self, tr('Fatto'), msg)
        self.accept()


# =============================================================== finestra principale
class Finestra(QMainWindow):
    COL_FILE, COL_PARL, COL_STATO, COL_AVANZ = range(4)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr('Argo · Cassetta degli attrezzi AI - versione {versione}', versione=VERSIONE))
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self.jobs = []
        self.worker = None          # trascrizione in corso
        self.job_corrente = None
        self.worker_voce = None     # iscrizione voce in corso
        self.in_esecuzione = False
        self.t_inizio = 0

        self.tabs = QTabWidget()
        self.tab_verbale = attrezzi.SchedaVerbale()
        import agenda_posta
        import incarichi
        import clienti
        import incontri
        import registrazione
        self.tab_incarichi = incarichi.SchedaIncarichi(self)
        self.tab_incontri = incontri.SchedaIncontri(self, VERSIONE)
        self.tab_clienti = clienti.SchedaClienti(self)
        self.tab_agenda = agenda_posta.SchedaAgenda(self)
        self.tab_posta = agenda_posta.SchedaPosta(self)
        self.tab_registra = registrazione.SchedaRegistra(self)
        self.tab_cervello = cervello_ui.PaginaCervello(self)
        self.pag_coda = self._tab_coda()
        self.tab_documenti = attrezzi.SchedaDocumenti()
        self.tab_dettatura = attrezzi.SchedaDettatura()
        self.tab_traduzione = attrezzi.SchedaTraduzione()
        self.tab_imp = self._pagina(self._tab_impostazioni(), tr('Impostazioni'),
                                    tr('Argo versione {versione} · scegli un argomento a sinistra', versione=VERSIONE))
        self.pag_voci = self._pagina(self._tab_voci(), tr('Voci'), tr('Anagrafe delle impronte vocali, solo con il consenso delle persone'))
        # Menu in tre gruppi, nell'ordine del lavoro (Stile Argo · Organizzazione): il flusso delle riunioni,
        # gli attrezzi indipendenti, la configurazione. Le pagine nel QTabWidget seguono lo stesso ordine.
        pagine = [
            (tr("RIUNIONI"), None, None, None),
            ("agenda", tr("Agenda"), tr("Agenda"), self.tab_agenda),
            ("registra", tr("Registra"), tr("Registra"), self._pagina(
                self.tab_registra, tr('Registra'),
                tr('Riunioni e call Teams: Live (resta solo il testo) o in archivio. Per brevi note tue usa Dettatura.'))),
            ("trascrittore", tr("Trascrivi"), tr("Trascrivi"), self.pag_coda),
            ("verbale", tr("Verbale"), tr("Verbale"), self._pagina(
                self.tab_verbale, tr('Verbale'),
                tr('Dalla trascrizione con i nomi al verbale, con il modello locale. Per verbale, mail e task in un colpo: Incarichi.'))),
            ("incarichi", tr("Incarichi"), tr("Incarichi"), self.tab_incarichi),
            ("incontri", tr("Incontri dall'iPhone"), tr("Incontri"), self._pagina(
                self.tab_incontri, tr('Incontri'),
                tr('Fiere e visite ai clienti registrate con Argo per iPhone: trascrizione con i nomi, foto e testo letto.'))),
            ("clienti", tr("Clienti"), tr("Clienti"), self._pagina(
                self.tab_clienti, tr('Clienti'),
                tr('Dynamics 365 Sales: cerca il cliente o prepara la scheda pubblica; dalla call partecipanti, aziende, relazione e task.'))),
            ("cervello", tr("Secondo cervello"), tr("Cervello"), self._pagina(
                self.tab_cervello, tr('Secondo cervello'),
                tr('Con chi parli in ogni incontro: aziende catalogate e persone per funzione, solo su questo computer.'))),
            (tr("ATTREZZI"), None, None, None),
            ("posta", tr("Posta AI"), tr("Posta"), self.tab_posta),
            ("documenti", tr("Documenti riservati"), tr("Documenti"), self._pagina(
                self.tab_documenti, tr('Documenti riservati'),
                tr('Domande su contratti, NDA e capitolati, con le fonti: documenti e indice restano su questo computer.'))),
            ("dettatura", tr("Dettatura"), tr("Dettatura"), self._pagina(
                self.tab_dettatura, tr('Dettatura'),
                tr('Parli, Argo scrive: per note e mail tue. Per le riunioni usa Registra.'))),
            ("traduzione", tr("Traduzione"), tr("Traduci"), self._pagina(
                self.tab_traduzione, tr('Traduzione'),
                tr('Testi e trascrizioni in IT · EN · DE, con i termini imposti dal glossario aziendale.'))),
            ("voci", tr("Anagrafe voci"), tr("Voci"), self.pag_voci),
            ("impostazioni", tr("Impostazioni"), tr("Impostaz."), self.tab_imp),
        ]
        for chiave, etichetta, _breve, widget in pagine:
            if widget is not None:
                self.tabs.addTab(widget, etichetta)
        self.tabs.tabBar().hide()
        self.nav = tema.NavLaterale([(c, e, br) for c, e, br, _w in pagine])
        self.nav.scelto.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.nav.seleziona)
        self.tabs.currentChanged.connect(
            lambda i: self.tab_cervello.aggiorna() if self.tabs.widget(i) is self._pagine.get(id(self.tab_cervello)) else None)
        centro = QWidget()
        cl = QHBoxLayout(centro)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.nav)
        cl.addWidget(self.tabs, 1)
        contenitore = QWidget()  # banda (trace, modalità sicura) sopra a tutto, visibile solo quando serve
        vl = QVBoxLayout(contenitore)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.banda = supporto.Banda(self)
        vl.addWidget(self.banda)
        vl.addWidget(centro, 1)
        self.setCentralWidget(contenitore)
        self.tabs.setCurrentWidget(self.pag_coda)
        self.nav.seleziona(self.tabs.indexOf(self.pag_coda))
        self.badge_cervello = QToolButton()  # 🧠 Secondo cervello attivo: un clic apre la sua pagina
        self.badge_cervello.setAutoRaise(True)
        self.badge_cervello.setCursor(Qt.PointingHandCursor)
        self.badge_cervello.clicked.connect(lambda: self.vai_a(self.tab_cervello))
        self.statusBar().addPermanentWidget(self.badge_cervello)
        self.tab_cervello.cambiato.connect(self._aggiorna_badge)
        self.badge = QLabel()
        self.statusBar().addPermanentWidget(self.badge)
        self._aggiorna_badge()
        self.statusBar().showMessage(tr('Pronto.'))  # la località la dice il bollino 🔒 a destra, senza ripeterla

        self._carica_coda()
        self._aggiorna_voci()
        self._stato_m365()
        if not core.leggi_token():
            self.vai_a_impostazioni("hf")
            QMessageBox.information(self, tr('Primo avvio'),
                                    tr('Benvenuto! Inserisci il token Hugging Face nelle Impostazioni e premi «Verifica».'))

    def _pagina(self, contenuto, titolo, sottotitolo=""):
        w = QWidget()
        w.setObjectName("pagina")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 12)
        lay.setSpacing(10)
        tl = QLabel(titolo)
        tl.setProperty("ruolo", "titolo")
        lay.addWidget(tl)
        if sottotitolo:
            sl = QLabel(sottotitolo)
            sl.setProperty("ruolo", "tenue")
            lay.addWidget(sl)
        if contenuto.layout():
            contenuto.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(contenuto, 1)
        self._pagine = getattr(self, "_pagine", {})
        self._pagine[id(contenuto)] = w
        return w

    def vai_a(self, contenuto):
        self.tabs.setCurrentWidget(self._pagine.get(id(contenuto), contenuto))

    def vai_a_impostazioni(self, sezione=None):
        """Apre le Impostazioni già sulla sezione giusta (es. «m365», «dynamics», «web»): chi arriva da un invito
        «Collega…» non deve cercare il riquadro in una pagina lunga."""
        self.tabs.setCurrentWidget(self.tab_imp)
        gruppo = getattr(self, "_sezioni_imp", {}).get(sezione)
        if gruppo is not None:
            n = self._pagina_di_sezione[sezione]
            self.nav_imp.setCurrentRow(n)
            scorri_area = self._scorri_imp[n]

            def scorri():
                y = gruppo.mapTo(scorri_area.widget(), QPoint(0, 0)).y()
                scorri_area.verticalScrollBar().setValue(max(0, y - 12))
            QTimer.singleShot(0, scorri)

    # ------------------------------------------------------------ tab coda
    def _tab_coda(self):
        w = QWidget()
        w.setObjectName("pagina")
        esterno = QHBoxLayout(w)
        esterno.setContentsMargins(0, 0, 0, 0)
        sinistra = QWidget()
        lay = QVBoxLayout(sinistra)
        lay.setContentsMargins(20, 16, 12, 12)
        testa = QHBoxLayout()
        tit = QLabel(tr('Trascrivi'))
        tit.setProperty("ruolo", "titolo")
        sotto = QLabel(tr('Trascina qui audio o video · nulla esce da questo computer'))
        sotto.setProperty("ruolo", "tenue")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(tit)
        col.addWidget(sotto)
        testa.addLayout(col)
        testa.addStretch()
        lay.addLayout(testa)

        self.tab_coda = QTableWidget(0, 4)
        self.tab_coda.setHorizontalHeaderLabels([tr('File'), tr('Partecipanti'), tr('Stato'), tr('Avanzamento')])
        h = self.tab_coda.horizontalHeader()
        h.setSectionResizeMode(self.COL_FILE, QHeaderView.Stretch)
        h.setSectionResizeMode(self.COL_STATO, QHeaderView.Interactive)
        self.tab_coda.setColumnWidth(self.COL_PARL, 92)
        self.tab_coda.setColumnWidth(self.COL_STATO, 170)
        self.tab_coda.setColumnWidth(self.COL_AVANZ, 110)
        self.tab_coda.verticalHeader().setVisible(False)
        self.tab_coda.setShowGrid(False)
        self.tab_coda.verticalHeader().setDefaultSectionSize(40)
        self.tab_coda.setWordWrap(False)
        self.tab_coda.itemSelectionChanged.connect(self._aggiorna_dettaglio)
        self.tab_coda.itemSelectionChanged.connect(self._azioni_coda)
        self.tab_coda.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_coda.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_coda.customContextMenuRequested.connect(self._menu_coda)
        QShortcut(QKeySequence.Delete, self.tab_coda, activated=self.rimuovi_job)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.tab_coda, activated=self.rimuovi_job)
        self.tab_coda.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab_coda.doubleClicked.connect(lambda _: self.apri_risultato())

        bar = QHBoxLayout()
        self.b_agg = QPushButton(tr('+ Aggiungi file…'))
        self.b_rim = QPushButton(tr('Rimuovi'))
        self.b_rip = QPushButton(tr('Rimetti in coda'))
        self.b_avvia = QPushButton(tr('▶ Avvia coda'))
        self.b_avvia.setProperty("primario", True)
        self.b_ris = QPushButton(tr('Apri trascrizione'))
        self.b_rev = QPushButton(tr('✏️ Nomi dei parlanti…'))
        self.b_cart = QPushButton(tr('Apri cartella'))
        self.b_verb = QPushButton(tr('Crea verbale →'))
        self.b_word = QPushButton(tr('Esporta in Word'))
        self.b_marca_job = QPushButton(tr('🎧 Marca voci…'))
        for b in (self.b_agg, self.b_rim, self.b_rip):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.b_avvia)
        # Stile Argo · Organizzazione: barra dei comandi sotto il sottotitolo, azione principale per prima
        comandi = QHBoxLayout()
        comandi.addWidget(self.b_avvia)
        comandi.addWidget(self.b_agg)
        comandi.addStretch()
        lay.insertLayout(1, comandi)  # subito sotto titolo e sottotitolo
        bar.removeWidget(self.b_agg)
        bar.removeWidget(self.b_avvia)
        for b in (self.b_ris, self.b_rev, self.b_marca_job, self.b_word, self.b_verb):
            b.setVisible(False)  # le azioni stanno nel pannello di dettaglio e nel menu col tasto destro
        self.b_agg.clicked.connect(self.scegli_file)
        self.b_rim.clicked.connect(self.rimuovi_job)
        self.b_rip.clicked.connect(self.rimetti_in_coda)
        self.b_avvia.clicked.connect(self.avvia_o_ferma)
        self.b_ris.clicked.connect(self.apri_risultato)
        self.b_rev.clicked.connect(self.rivedi_parlanti)
        self.tab_coda.cellDoubleClicked.connect(
            lambda r, c: self.rivedi_parlanti() if r < len(self.jobs) and self.jobs[r]["stato"] == "Completata" else None)
        self.b_cart.clicked.connect(self.apri_cartella)
        self.b_verb.clicked.connect(self.crea_verbale)
        self.b_word.clicked.connect(self.esporta_word)
        self.b_marca_job.clicked.connect(lambda: (lambda j: j and self.marca_voci(j["file"]))(self._job_selezionato()))

        self.fase = QLabel("")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setFont(QFont("Consolas" if os.name == "nt" else "Menlo", 9))
        self.fase.setProperty("ruolo", "tenue")
        # Il registro tecnico compare solo quando c'è qualcosa da leggere (Stile Argo: niente pannelli vuoti)
        self.log.setVisible(False)
        self.log.textChanged.connect(lambda: self.log.setVisible(not self.log.document().isEmpty()))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tab_coda)
        split.addWidget(self.log)
        split.setSizes([420, 120])
        lay.addWidget(split, 1)
        lay.addWidget(self.fase)
        lay.addLayout(bar)
        self.b_cart.setParent(sinistra)
        bar.insertWidget(3, self.b_cart)

        self._azioni_coda()
        self.dettaglio = dettaglio.DettaglioTrascrizione()
        self.dettaglio.nomi.connect(self.rivedi_parlanti)
        self.dettaglio.marca.connect(lambda: (lambda j: j and self.marca_voci(j["file"]))(self._job_selezionato()))
        self.dettaglio.word.connect(lambda: self._menu_scarica().exec(QCursor.pos()))
        self.dettaglio.verbale.connect(self.crea_verbale)
        self.dettaglio.apri.connect(self.apri_risultato)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(sinistra)
        sp.addWidget(self.dettaglio)
        sp.setSizes([560, 620])
        esterno.addWidget(sp)
        return w

    def _azioni_coda(self):
        """Rimuovi e Rimetti in coda servono solo su un file scelto: fino ad allora restano nascosti."""
        if hasattr(self, "b_rim"):
            scelto = bool(self.tab_coda.selectionModel().selectedRows())
            self.b_rim.setVisible(scelto)
            self.b_rip.setVisible(scelto)

    def _aggiorna_dettaglio(self):
        if not hasattr(self, "dettaglio"):
            return
        sel = self._selezionati()
        self.dettaglio.mostra(sel[0] if sel else None)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.aggiungi_file([u.toLocalFile() for u in e.mimeData().urls()])

    def scegli_file(self):
        filtro = "Audio/video (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ");;Tutti i file (*)"
        files, _ = QFileDialog.getOpenFileNames(self, tr('Scegli i file audio'), str(Path.home()), filtro)
        self.aggiungi_file(files)

    def aggiungi_file(self, files):
        aggiunti = 0
        for f in files:
            p = Path(f)
            if p.is_dir():
                self.aggiungi_file([str(x) for x in sorted(p.iterdir())])
                continue
            if p.suffix.lower() not in AUDIO_EXT or not p.exists():
                continue
            self.jobs.append({"id": uuid.uuid4().hex, "file": str(p), "parlanti": 2,
                              "stato": "In attesa", "progresso": 0, "json": "", "txt": "", "nota": ""})
            aggiunti += 1
        if aggiunti:
            self._ridisegna_coda()
            self._salva_coda()
            self.statusBar().showMessage(tr('{aggiunti} file aggiunti alla coda.', aggiunti=aggiunti))

    def _ridisegna_coda(self):
        t = self.tab_coda
        t.setRowCount(len(self.jobs))
        for r, j in enumerate(self.jobs):
            it = QTableWidgetItem(Path(j["file"]).name)
            it.setToolTip(j["file"])
            t.setItem(r, self.COL_FILE, it)
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setSpecialValueText("Auto")
            spin.setValue(j["parlanti"])
            spin.setEnabled(j["stato"] in ("In attesa", "Errore", "Interrotta", "Completata"))
            spin.setToolTip(tr('Numero di persone che parlano. Su una trascrizione completata, cambiarlo rifà solo la separazione dei parlanti.'))
            spin.valueChanged.connect(lambda v, jid=j["id"]: self._set_parlanti(jid, v))
            t.setCellWidget(r, self.COL_PARL, spin)
            stato = j["stato"] + (f" - {j['nota']}" if j.get("nota") else "")
            t.setItem(r, self.COL_STATO, self._item_stato(j["stato"], stato))
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 0, 10, 0)
            pb = QProgressBar()
            pb.setFixedHeight(8)
            pb.setTextVisible(False)
            pb.setValue(int(j.get("progresso", 0)))
            pb.setVisible(j["stato"] == "In corso")
            bl.addWidget(pb)
            box.pb = pb
            t.setCellWidget(r, self.COL_AVANZ, box)

    def _item_stato(self, stato, testo):
        c = tema.colori()
        it = QTableWidgetItem(("●  " if stato in ("In corso", "Completata", "Errore", "Interrotta") else "○  ") + testo)
        it.setToolTip(testo)
        colore = {"Completata": c["ok"], "In corso": c["accento"], "Errore": c["err"], "Interrotta": c["warn"]}.get(stato, c["tenue"])
        it.setForeground(QColor(colore))
        return it

    def _set_parlanti(self, jid, v):
        j = next((x for x in self.jobs if x["id"] == jid), None)
        if j is None:
            return
        if j["stato"] == "Completata" and j.get("json") and Path(j["json"]).exists():
            n = "automatico" if v == 0 else str(v)
            r = QMessageBox.question(
                self, tr('Cambiare i partecipanti?'),
                tr('Rifaccio solo la separazione dei parlanti di «{name}» con partecipanti: {n}.\n\nIl testo trascritto resta lo stesso, ci vuole meno tempo di una trascrizione completa. I nomi corretti a mano finora andranno riassegnati.', name=Path(j['file']).name, n=n),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                self._ridisegna_coda()  # rimette il numero di prima
                return
            j.update(parlanti=v, stato="In attesa", progresso=0, nota="solo parlanti", solo_parlanti=True)
            self._ridisegna_coda()
            self._salva_coda()
            if not self.in_esecuzione:
                self.avvia_o_ferma()
            return
        j["parlanti"] = v
        self._salva_coda()

    def _riga_di(self, job):
        return self.jobs.index(job) if job in self.jobs else -1

    def _aggiorna_riga(self, job):
        r = self._riga_di(job)
        if r < 0:
            return
        stato = job["stato"] + (f" - {job['nota']}" if job.get("nota") else "")
        self.tab_coda.setItem(r, self.COL_STATO, self._item_stato(job["stato"], stato))
        box = self.tab_coda.cellWidget(r, self.COL_AVANZ)
        pb = getattr(box, "pb", None)
        if pb:
            pb.setValue(int(job.get("progresso", 0)))
            pb.setVisible(job["stato"] == "In corso")
        spin = self.tab_coda.cellWidget(r, self.COL_PARL)
        if spin:
            spin.setEnabled(job["stato"] in ("In attesa", "Errore", "Interrotta", "Completata"))

    def _selezionati(self):
        righe = sorted({i.row() for i in self.tab_coda.selectedIndexes()})
        return [self.jobs[r] for r in righe if r < len(self.jobs)]

    def _menu_coda(self, pos):
        r = self.tab_coda.rowAt(pos.y())
        if r < 0:
            return
        if r not in {i.row() for i in self.tab_coda.selectedIndexes()}:
            self.tab_coda.selectRow(r)
        j = self.jobs[r]
        m = QMenu(self)
        if j["stato"] == "Completata":
            m.addAction(tr('Apri trascrizione'), self.apri_trascrizione if hasattr(self, "apri_trascrizione") else self.b_ris.click)
            m.addAction(tr('✏️ Nomi dei parlanti…'), self.rivedi_parlanti)
            m.addMenu(self._menu_scarica()).setText(tr('⬇️ Scarica trascrizione'))
            m.addAction(tr('Crea verbale →'), self.crea_verbale)
            m.addSeparator()
        m.addAction(tr('🎧 Marca voci…'), lambda: self.marca_voci(j["file"]))
        if cervello.attivo():
            m.addAction(tr('🧠 Con chi stai parlando?…'),
                        lambda: cervello_ui.collega(self, j["file"], Path(j["file"]).stem, "file"))
        m.addAction(tr('Rimetti in coda'), self.rimetti_in_coda)
        m.addAction(tr('Apri cartella'), self.b_cart.click)
        m.addSeparator()
        m.addAction(tr('Rimuovi dalla coda'), self.rimuovi_job)
        m.exec(self.tab_coda.viewport().mapToGlobal(pos))

    def _in_lavorazione(self, j):
        return j is self.job_corrente and self.worker is not None and self.worker.isRunning()

    def rimuovi_job(self):
        sel = [j for j in self._selezionati() if not self._in_lavorazione(j)]
        if not sel and self._selezionati():
            QMessageBox.information(self, tr('In lavorazione'), tr('Questo file è in elaborazione: ferma prima la coda.'))
            return
        for j in sel:
            self.jobs.remove(j)
        self._ridisegna_coda()
        self._salva_coda()

    def rimetti_in_coda(self):
        sel = [j for j in self._selezionati() if not self._in_lavorazione(j)]
        solo = False
        if any(j["stato"] == "Completata" and j.get("json") and Path(j["json"]).exists() for j in sel):
            box = QMessageBox(self)
            box.setWindowTitle(tr('Rimetti in coda'))
            box.setText(tr('Cosa vuoi rifare per le trascrizioni già completate?'))
            b_parl = box.addButton(tr('Solo i parlanti'), QMessageBox.AcceptRole)
            b_tutto = box.addButton(tr('Tutta la trascrizione'), QMessageBox.DestructiveRole)
            box.addButton(tr('Annulla'), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (b_parl, b_tutto):
                return
            solo = box.clickedButton() is b_parl
        for j in sel:
            if not self._in_lavorazione(j):
                da_json = solo and j["stato"] == "Completata" and j.get("json") and Path(j["json"]).exists()
                j.update(stato="In attesa", progresso=0, nota="solo parlanti" if da_json else "", solo_parlanti=bool(da_json))
        self._ridisegna_coda()
        self._salva_coda()

    def _salva_coda(self):
        try:
            core.APP_HOME.mkdir(parents=True, exist_ok=True)
            core.QUEUE_FILE.write_text(json.dumps(self.jobs, indent=1, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.log.appendPlainText(f"Impossibile salvare la coda: {e}")

    def _carica_coda(self):
        try:
            self.jobs = json.loads(core.QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.jobs = []
        for j in self.jobs:
            if j.get("stato") == "In corso":
                j.update(stato="Interrotta", nota="app chiusa durante l'elaborazione", progresso=0)
        self._ridisegna_coda()

    # ------------------------------------------------------------ esecuzione coda
    def avvia_o_ferma(self):
        if self.in_esecuzione:
            self.in_esecuzione = False
            self.b_avvia.setText(tr('▶ Avvia coda'))
            if self.worker:
                self.worker.ferma()
            self.statusBar().showMessage(tr('Coda fermata.'))
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, tr('Attendi'), tr("Sto ancora fermando l'elaborazione precedente: riprova tra qualche secondo."))
            return
        if not core.leggi_token():
            QMessageBox.warning(self, tr('Token mancante'), tr('Inserisci prima il token Hugging Face nelle Impostazioni.'))
            self.vai_a_impostazioni("hf")
            return
        if not any(j["stato"] == "In attesa" for j in self.jobs):
            QMessageBox.information(self, tr('Coda vuota'), tr('Non ci sono file «In attesa». Aggiungi dei file o rimettili in coda.'))
            return
        self.in_esecuzione = True
        self.b_avvia.setText(tr('■ Ferma coda'))
        self._prossimo()

    def _prossimo(self):
        if not self.in_esecuzione:
            return
        job = next((j for j in self.jobs if j["stato"] == "In attesa"), None)
        if job is None:
            self.in_esecuzione = False
            self.b_avvia.setText(tr('▶ Avvia coda'))
            self.fase.setText("")
            self.statusBar().showMessage(tr('Coda completata.'))
            QApplication.alert(self)
            return
        if not Path(job["file"]).exists():
            job.update(stato="Errore", nota="file non trovato")
            self._aggiorna_riga(job)
            return self._prossimo()
        self.job_corrente = job
        job.update(stato="In corso", progresso=1, nota="avvio")
        self._aggiorna_riga(job)
        self._salva_coda()
        imp = core.carica_impostazioni()
        if job.get("solo_parlanti") and job.get("json") and Path(job["json"]).exists():
            cmd = [sys.executable, str(Path(core.__file__).resolve()), "ridiarizza", job["json"], job["file"],
                   str(job["parlanti"] or 0), imp.get("device", "cpu")]
            self.log.appendPlainText(f"\n=== {Path(job['file']).name} | solo parlanti | "
                                     f"partecipanti {job['parlanti'] or 'auto'} ===")
        else:
            cmd = core.comando_whisperx(job["file"], job["parlanti"], imp, core.leggi_token())
            self.log.appendPlainText(f"\n=== {Path(job['file']).name} | modello {imp['model']} | "
                                     f"partecipanti {job['parlanti'] or 'auto'} ===")
        self.t_inizio = time.time()
        self._log_job = []
        self.filtro = FiltroRumore()
        diagnostica.log.info("trascrizione: inizio · %s · %s · modello %s · %s · partecipanti %s",
                             diagnostica.descrivi_file(job["file"]),
                             "solo parlanti" if job.get("solo_parlanti") else "completa", imp.get("model"),
                             imp.get("device"), job["parlanti"] or "auto")
        w = ProcessWorker(cmd, self)
        self.worker = w
        w.riga.connect(lambda testo, w=w: self._riga_whisperx(testo) if w is self.worker else None)
        w.finito.connect(lambda codice, w=w, jb=job: self._fine_whisperx(codice, w, jb))
        w.start()

    def _riga_whisperx(self, testo):
        job = self.job_corrente
        if job is None:
            return
        if "%|" in testo:  # barre di download di Hugging Face
            self.fase.setText("Download modelli (solo la prima volta): " + testo[:110])
            job["nota"] = "download modelli"
            self._aggiorna_riga(job)
            return
        if self.filtro.e_rumore(testo):
            return
        if "hf_token" in testo:
            testo = re.sub(r"hf_[A-Za-z0-9]+", "hf_***", testo)
        self.log.appendPlainText(testo)
        self._log_job = (self._log_job + [testo])[-200:]
        diagnostica.riga_processo(testo)
        for chiave, (nome, ini, fine) in FASI.items():
            if chiave in testo:
                diagnostica.log.info("trascrizione: fase %s dopo %.0f s", nome.lower(), time.time() - self.t_inizio)
                job.update(nota=nome.lower(), progresso=ini)
                self._fase_corrente = (nome, ini, fine)
                self._aggiorna_riga(job)
        m = RE_PROGRESS.search(testo)
        if m and getattr(self, "_fase_corrente", None):
            nome, ini, fine = self._fase_corrente
            job["progresso"] = ini + (fine - ini) * float(m.group(1)) / 100
            self._aggiorna_riga(job)
        minuti = int((time.time() - self.t_inizio) // 60)
        self.fase.setText(tr('{name}: {get} - {minuti} min trascorsi', name=Path(job['file']).name, get=job.get('nota', ''), minuti=minuti))

    def _fine_whisperx(self, codice, w=None, job=None):
        if w is not None and w is not self.worker:  # segnale tardivo di un lavoro già sostituito
            if job is not None and job.get("stato") == "In corso":
                job.update(stato="Interrotta", nota="fermata dall'utente", progresso=0)
                self._ridisegna_coda()
                self._salva_coda()
            return
        job = job or self.job_corrente
        self.job_corrente = None
        self._fase_corrente = None
        interrotto = self.worker.interrotto if self.worker else False
        self.worker = None
        if job is None:
            return
        minuti = max(1, round((time.time() - self.t_inizio) / 60))
        if interrotto:
            job.update(stato="Interrotta", nota="fermata dall'utente", progresso=0)
        else:
            fj = core.json_atteso(job["file"])
            job.pop("solo_parlanti", None)
            if codice == 0 and fj.exists():
                try:
                    out, mappa, _, _ = core.identifica(fj)
                    nomi = sorted(set(mappa.values()))
                    job.pop("ripresa_sospensione", None)
                    job.update(stato="Completata", progresso=100, json=str(fj), txt=str(out),
                               nota=f"{minuti} min - " + ", ".join(nomi))
                except Exception as e:
                    job.update(stato="Errore", nota=f"identificazione voci: {e}")
            elif veglia.sospeso_dal(self.t_inizio) and not job.get("ripresa_sospensione"):
                # il computer ha dormito (coperchio chiuso, tasto di accensione): si riparte da capo, una volta
                job.update(stato="In attesa", progresso=0, ripresa_sospensione=True,
                           nota="ripresa dopo la sospensione del computer")
                diagnostica.coda_processo(getattr(self, "_log_job", []),
                                          motivo=f"codice di uscita {codice} dopo una sospensione: rimessa in coda")
            else:
                job.update(stato="Errore", nota=self._spiega_errore(), progresso=0)
                job.pop("ripresa_sospensione", None)
                diagnostica.coda_processo(getattr(self, "_log_job", []), motivo=f"codice di uscita {codice}")
        if job["stato"] == "Completata":
            diagnostica.log.info("trascrizione: completata in %d min · parlanti %d", minuti,
                                 len(set(mappa.values())))
        else:  # la nota dell'errore è tecnica; per «Completata» contiene i nomi e non si scrive
            diagnostica.log.warning("trascrizione: %s dopo %d min · %s", job["stato"].lower(), minuti,
                                    job.get("nota", ""))
        self.log.appendPlainText(f"--- {job['stato']}: {job.get('nota', '')}")
        self._aggiorna_dettaglio()
        self._aggiorna_riga(job)
        self._salva_coda()
        self._prossimo()

    def _spiega_errore(self):
        log = "\n".join(getattr(self, "_log_job", []))
        if veglia.sospeso_dal(self.t_inizio):
            return ("il computer è andato in sospensione due volte durante la trascrizione: "
                    "tienilo acceso e alla corrente, poi rimetti in coda")
        if "401" in log and "huggingface" in log.lower():
            return "token Hugging Face non valido (verifica nelle Impostazioni)"
        if "403" in log or "gated" in log.lower():
            return "condizioni del modello pyannote non accettate"
        if "IncompleteRead" in log or "Connection" in log:
            return "download interrotto: rimetti in coda e riprova"
        if "No such file" in log or ("ffmpeg" in log.lower() and "not found" in log.lower()):
            return "ffmpeg non trovato o file illeggibile"
        return "vedi il registro qui sotto"

    def _job_selezionato(self):
        sel = self._selezionati()
        if not sel:
            QMessageBox.information(self, tr('Seleziona'), tr('Seleziona prima una riga della coda.'))
            return None
        return sel[0]

    def apri_risultato(self):
        j = self._job_selezionato()
        if j and j.get("txt") and Path(j["txt"]).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(j["txt"]))
        elif j:
            QMessageBox.information(self, tr('Non pronta'), tr('La trascrizione non è ancora disponibile.'))

    def rivedi_parlanti(self):
        j = self._job_selezionato()
        if not j:
            return
        if not (j.get("json") and Path(j["json"]).exists()):
            QMessageBox.information(self, tr('Non pronta'), tr('Prima completa la trascrizione.'))
            return
        dlg = RevisioneDialog(j["json"], self)
        if dlg.exec():
            j["txt"] = str(dlg.out)
            self._salva_coda()
            self._aggiorna_voci()
            self._aggiorna_dettaglio()

    def rivedi_json(self, file_json):
        """Usato dagli Incarichi: apre la revisione dei nomi su una trascrizione qualsiasi."""
        dlg = RevisioneDialog(str(file_json), self)
        if dlg.exec():
            for j in self.jobs:
                if j.get("json") and Path(j["json"]) == Path(file_json):
                    j["txt"] = str(dlg.out)
            self._salva_coda()
            self._aggiorna_voci()
            self._aggiorna_dettaglio()
            return True
        return False

    def crea_verbale(self):
        j = self._job_selezionato()
        if not j:
            return
        if not (j.get("txt") and Path(j["txt"]).exists()):
            QMessageBox.information(self, tr('Non pronta'), tr('Prima completa la trascrizione.'))
            return
        self.tab_verbale.carica(j["txt"])
        self.vai_a(self.tab_verbale)

    def _sorgente_job(self):
        """Per «⬇️ Scarica trascrizione»: (segmenti, nome, cartella, titolo) del file selezionato in coda."""
        j = self._job_selezionato()
        if not j:
            return None
        if not (j.get("txt") and Path(j["txt"]).exists()):
            QMessageBox.information(self, tr('Non pronta'), tr('Prima completa la trascrizione.'))
            return None
        txt = Path(j["txt"])
        nome = txt.stem.replace("_nomi", "")
        return esporta_trascrizione.da_file(j.get("json") or txt), nome, txt.parent, f"Trascrizione: {nome}"

    def _menu_scarica(self):
        return esporta_trascrizione.menu(self, self._sorgente_job)

    def esporta_word(self):
        esporta_trascrizione.scarica(self, self._sorgente_job, ("docx",))

    def _aggiorna_badge(self):
        if hasattr(self, "badge_cervello"):
            acceso = cervello.attivo()
            self.badge_cervello.setVisible(acceso)
            if acceso:
                n = len(cervello_base.voci())
                self.badge_cervello.setText(tr('🧠 Secondo cervello attivo · {n} {valore} nella Base', n=n, valore='voce' if n == 1 else 'voci'))
                self.badge_cervello.setToolTip(tr('Argo chiede con chi parli a ogni registrazione; i dati restano su questo computer. Clic per aprire la pagina.'))
                self.badge_cervello.setStyleSheet(f"color: {tema.colori()['accento']};"
                                                  " font-weight: 600; padding: 0 8px; border: none; background: transparent;")
        url = core.carica_impostazioni().get("ollama_url", "")
        nel_cloud = [cloud.NOMI_ATTREZZI[a] for a in cloud.NOMI_ATTREZZI if cloud.e_cloud(a)]
        if nel_cloud:  # almeno un attrezzo usa un modello cloud: il badge non può dire «100% locale»
            self.badge.setText("☁️ Audio e trascrizioni in locale · modello cloud per: " + ", ".join(nel_cloud))
            self.badge.setToolTip(tr('Scelto in Impostazioni › Modelli cloud'))
            self.badge.setStyleSheet(f"color: {tema.colori()['warn']}; font-weight: 600; padding-right: 8px;")
        elif llm_locale.e_locale(url) and m365.account():
            self.badge.setText(tr('🔒 Locale · Microsoft 365 collegato: solo i risultati che confermi vanno su M365'))
            self.badge.setStyleSheet(f"color: {tema.colori()['ok']}; font-weight: 600; padding-right: 8px;")
        elif llm_locale.e_locale(url) and (backup.nel_cloud(backup.cartella_backup()) or backup.condivisione_attiva()):
            servizi = {backup.nel_cloud(backup.cartella_backup())} | (
                {backup.nel_cloud(core.carica_impostazioni().get("condivisione_cartella", ""))}
                if backup.condivisione_attiva() else set())
            self.badge.setText("🔒 Locale · backup e configurazione anche in " + ", ".join(sorted(x for x in servizi if x)))
            self.badge.setToolTip(tr('Scelto in Impostazioni › Backup e più computer'))
            self.badge.setStyleSheet(f"color: {tema.colori()['ok']}; font-weight: 600; padding-right: 8px;")
        elif llm_locale.e_locale(url):
            self.badge.setText(tr('🔒 100% locale: audio e testi non lasciano questo computer'))
            self.badge.setStyleSheet(f"color: {tema.colori()['ok']}; font-weight: 600; padding-right: 8px;")
        else:
            self.badge.setText(tr('⚠️ Il modello linguistico punta a un server esterno'))
            self.badge.setStyleSheet(f"color: {tema.colori()['warn']}; font-weight: 600; padding-right: 8px;")

    def apri_cartella(self):
        j = self._job_selezionato()
        if j:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(j["file"]).parent)))

    # ------------------------------------------------------------ tab anagrafe voci
    def _tab_voci(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        # Stile Argo · Organizzazione: un'azione principale con i suoi tre modi in un menu; le azioni sulla
        # singola voce compaiono solo quando ne scegli una; Elimina sta in disparte.
        bar = QHBoxLayout()
        self.b_nuova_voce = QToolButton()
        self.b_nuova_voce.setText(tr('＋ Nuova voce ▾'))
        self.b_nuova_voce.setProperty("primario", True)
        self.b_nuova_voce.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.b_nuova_voce)
        self.b_reg_voce = m.addAction(tr('🎙  Registra ora al microfono  ·  la persona parla 20-60 secondi'))
        self.b_nuova = m.addAction(tr('📄  Da un file in cui parla solo lei'))
        self.b_marca = m.addAction(tr('🎧  Segnando dove parla in una registrazione'))
        self.b_nuova_voce.setMenu(m)
        bar.addWidget(self.b_nuova_voce)
        self.b_iphone = QPushButton(tr('📱 Per iPhone…'))
        self.b_iphone.setToolTip(tr('Esporta le voci scelte per Argo per iPhone (file .argovoci da passare con AirDrop)'))
        bar.addWidget(self.b_iphone)
        bar.addStretch()
        self.b_camp = QPushButton(tr('Aggiungi campione…'))
        self.b_camp.setToolTip(tr('Un altro audio della stessa persona: più campioni, riconoscimento migliore'))
        self.b_ren = QPushButton(tr('Rinomina…'))
        self.b_del = QPushButton(tr('Elimina'))
        self.b_consenso = QPushButton(tr('Conferma consenso…'))
        self.b_consenso.setToolTip(tr('La persona ha acconsentito a essere riconosciuta: da ora la sua voce si usa'))
        self.b_consenso.clicked.connect(self.conferma_consenso)
        for b in (self.b_consenso, self.b_camp, self.b_ren):
            bar.addWidget(b)
        bar.addSpacing(16)
        bar.addWidget(self.b_del)
        lay.addLayout(bar)
        self.banda_voci = QFrame()
        self.banda_voci.setProperty("ruolo", "scheda")
        bvl = QHBoxLayout(self.banda_voci)
        self.l_banda_voci = QLabel()
        self.l_banda_voci.setWordWrap(True)
        self.b_attiva_voci = QPushButton(tr('Attiva il riconoscimento…'))
        self.b_attiva_voci.clicked.connect(self.attiva_riconoscimento)
        bvl.addWidget(self.l_banda_voci, 1)
        bvl.addWidget(self.b_attiva_voci)
        lay.addWidget(self.banda_voci)
        self.tab_voci = QTableWidget(0, 3)
        self.tab_voci.setHorizontalHeaderLabels([tr('Nome'), tr('Campioni'), tr('Consenso')])
        self.tab_voci.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tab_voci.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_voci.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab_voci.verticalHeader().setVisible(False)
        self.tab_voci.setShowGrid(False)
        self.tab_voci.itemSelectionChanged.connect(self._azioni_voce)
        lay.addWidget(self.tab_voci, 1)
        self.vuoto_voci = tema.StatoVuoto("Nessuna voce ancora. Premi «＋ Nuova voce» e scegli come crearla: "
                                          "Argo riconoscerà la persona nelle trascrizioni (solo con il suo consenso).")
        lay.addWidget(self.vuoto_voci, 1)
        self.stato_voci = QLabel("")
        lay.addWidget(self.stato_voci)
        self.b_reg_voce.triggered.connect(self.registra_voce)
        self.b_marca.triggered.connect(lambda: self.marca_voci(None))
        self.b_nuova.triggered.connect(lambda: self.iscrivi_voce(None))
        self.b_camp.clicked.connect(lambda: self.iscrivi_voce(self._voce_selezionata()))
        self.b_ren.clicked.connect(self.rinomina_voce)
        self.b_del.clicked.connect(self.elimina_voce)
        self.b_iphone.clicked.connect(self.esporta_voci_iphone)
        self._azioni_voce()
        return w

    def _azioni_voce(self):
        scelta = bool(self.tab_voci.selectedItems())
        for b in (self.b_camp, self.b_ren, self.b_del):
            b.setVisible(scelta)
        n = self._voce_selezionata()
        self.b_consenso.setVisible(bool(scelta and n and core.consenso(n) is None))
        attivo, vietato = core.riconoscimento_attivo(), core.riconoscimento_vietato()
        for a in (self.b_reg_voce, self.b_nuova, self.b_marca):
            a.setEnabled(attivo)
        self.b_camp.setEnabled(attivo)
        self.banda_voci.setVisible(not attivo or bool(core.senza_consenso()))
        if vietato:
            self.l_banda_voci.setText(tr("🏢 Il riconoscimento delle voci è disattivato dall'IT. Le trascrizioni usano «Parlante 1, 2…»."))
        elif not attivo:
            self.l_banda_voci.setText(tr('Riconoscimento delle voci spento: le trascrizioni usano «Parlante 1, 2…» e non si salvano impronte. Attivalo solo con il consenso delle persone.'))
        else:
            self.l_banda_voci.setText(tr('⚠️ Alcune voci non hanno il consenso registrato e non vengono usate: selezionale e premi «Conferma consenso…».'))
        self.b_attiva_voci.setVisible(not attivo and not vietato)
        vuota = self.tab_voci.rowCount() == 0
        self.b_iphone.setVisible(not vuota)
        self.tab_voci.setVisible(not vuota)
        self.vuoto_voci.setVisible(vuota)

    def _aggiorna_voci(self):
        voci = core.elenco_voci()
        self.tab_voci.setRowCount(len(voci))
        for r, (n, c) in enumerate(voci):
            self.tab_voci.setItem(r, 0, QTableWidgetItem(n))
            self.tab_voci.setItem(r, 1, QTableWidgetItem(str(c)))
            cons = core.consenso(n)
            self.tab_voci.setItem(r, 2, QTableWidgetItem(f"✅ {cons['data']}" if cons else "⚠️ da confermare"))
        self._azioni_voce()

    def _voce_selezionata(self):
        r = self.tab_voci.currentRow()
        it = self.tab_voci.item(r, 0) if r >= 0 else None
        return it.text() if it else None

    def attiva_riconoscimento(self):
        if consenso_voci.attiva(self):
            self.statusBar().showMessage(tr('Riconoscimento delle voci attivato.'), 6000)
        self._aggiorna_voci()
        if hasattr(self, "cb_riconoscimento"):
            self.cb_riconoscimento.blockSignals(True)
            self.cb_riconoscimento.setChecked(core.riconoscimento_attivo())
            self.cb_riconoscimento.blockSignals(False)

    def _cambia_riconoscimento(self, attivo):
        if attivo:
            self.attiva_riconoscimento()
        else:
            consenso_voci.disattiva()
            self.statusBar().showMessage(tr('Riconoscimento delle voci spento: le voci salvate restano, inutilizzate.'), 6000)
            self._aggiorna_voci()

    def conferma_consenso(self):
        n = self._voce_selezionata()
        if n and consenso_voci.chiedi([n], self, "confermato dalla pagina Voci"):
            self._aggiorna_voci()

    def iscrivi_voce(self, nome):
        if self.worker_voce:
            QMessageBox.information(self, tr('Attendi'), tr('Sto già elaborando una voce.'))
            return
        if not core.leggi_token():
            QMessageBox.warning(self, tr('Token mancante'), tr('Inserisci prima il token nelle Impostazioni.'))
            return
        if not core.riconoscimento_attivo() and not consenso_voci.attiva(self):
            return
        if nome is None:
            nome, ok = QInputDialog.getText(self, tr('Nuova voce'), tr('Nome della persona:'))
            if not ok:
                return
            nome = nome.strip()
        if not core.nome_valido(nome or ""):
            QMessageBox.warning(self, tr('Nome non valido'), tr('Scegli un nome senza caratteri speciali.'))
            return
        filtro = "Audio o video (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ")"
        f, _ = QFileDialog.getOpenFileName(self, tr('Audio con la sola voce di {nome}', nome=nome), str(Path.home()), filtro)
        if not f:
            return
        self._avvia_iscrizioni([(nome, f)])

    def _pronto_per_voci(self):
        if self.worker_voce:
            QMessageBox.information(self, tr('Attendi'), tr('Sto già elaborando una voce.'))
            return False
        if not core.leggi_token():
            QMessageBox.warning(self, tr('Token mancante'), tr('Inserisci prima il token nelle Impostazioni.'))
            return False
        if not core.riconoscimento_attivo() and not consenso_voci.attiva(self):
            return False
        self._aggiorna_voci()
        return True

    def registra_voce(self):
        if not self._pronto_per_voci():
            return
        dlg = voci_strumenti.RegistraVoceDialog([n for n, _ in core.elenco_voci()], self._voce_selezionata(), self)
        if dlg.exec() and dlg.risultato:
            self._avvia_iscrizioni(dlg.risultato, consenso_dato="spuntato registrando la voce al microfono")

    def marca_voci(self, file_audio=None):
        if not self._pronto_per_voci():
            return
        dlg = voci_strumenti.MarcaVociDialog([n for n, _ in core.elenco_voci()], file_audio, self)
        if dlg.exec() and dlg.risultato:
            self.tabs.setCurrentWidget(self.pag_voci)
            self._avvia_iscrizioni(dlg.risultato, consenso_dato="spuntato segnando le voci in una registrazione")

    def _avvia_iscrizioni(self, coppie, consenso_dato=None):
        """Calcola le impronte una dopo l'altra: coppie = [(nome, file_audio)]. Solo con il consenso:
        già spuntato nella finestra di registrazione (consenso_dato = come) oppure chiesto qui."""
        if consenso_dato and (core.riconoscimento_attivo() or consenso_voci.attiva(self)):
            for n, _ in coppie:
                if core.consenso(n) is None:
                    core.registra_consenso(n, consenso_dato)
        ok = consenso_voci.chiedi([n for n, _ in coppie], self)
        scartate = sorted({n for n, _ in coppie if n not in ok})
        coppie = [(n, f) for n, f in coppie if n in ok]
        if scartate:
            QMessageBox.information(self, tr('Senza consenso'), "Impronta non salvata per: " + ", ".join(scartate) + ".")
        if not coppie:
            return
        self._coda_voci = list(coppie)
        self._fatte_voci, self._errori_voci = [], []
        self._prossima_iscrizione()

    def _prossima_iscrizione(self):
        if not self._coda_voci:
            self.b_nuova.setEnabled(True)
            self.b_camp.setEnabled(True)
            self.b_reg_voce.setEnabled(True)
            self.b_marca.setEnabled(True)
            self._aggiorna_voci()
            msg = []
            if self._fatte_voci:
                msg.append("Impronte salvate: " + ", ".join(self._fatte_voci) + ".")
            if self._errori_voci:
                msg.append("Errori: " + "; ".join(self._errori_voci))
            self.stato_voci.setText(" ".join(msg))
            return
        nome, f = self._coda_voci.pop(0)
        device = core.carica_impostazioni().get("device", "cpu")
        cmd = [sys.executable, str(Path(core.__file__).resolve()), "iscrivi", nome, f, device]
        resto = f" (poi altre {len(self._coda_voci)})" if self._coda_voci else ""
        self.stato_voci.setText(tr("Calcolo dell'impronta di {nome} in corso (1-2 minuti){resto}…", nome=nome, resto=resto))
        for b in (self.b_nuova, self.b_camp, self.b_reg_voce, self.b_marca):
            b.setEnabled(False)
        self._righe_voce = []
        filtro_voce = FiltroRumore()
        self.worker_voce = ProcessWorker(cmd, self)
        self.worker_voce.riga.connect(lambda t: None if filtro_voce.e_rumore(t) else
                                      (self._righe_voce.append(t), self.log.appendPlainText("[voce] " + t)))
        self.worker_voce.finito.connect(lambda c, n=nome: self._fine_iscrizione(c, n))
        self.worker_voce.start()

    def _fine_iscrizione(self, codice, nome):
        self.worker_voce = None
        diagnostica.log.info("anagrafe voci: iscrizione %s (codice %s)", "riuscita" if codice == 0 else "non riuscita",
                             codice)
        if codice != 0:
            diagnostica.coda_processo(getattr(self, "_righe_voce", []), "voci_core", f"codice di uscita {codice}")
        self._aggiorna_voci()
        if codice == 0:
            self._fatte_voci.append(nome)
        else:
            err = next((r for r in reversed(self._righe_voce) if r.startswith("ERRORE")), "vedi il registro nella pagina Trascrivi")
            self._errori_voci.append(f"{nome}: {err}")
        self._prossima_iscrizione()

    def rinomina_voce(self):
        n = self._voce_selezionata()
        if not n:
            return
        nuovo, ok = QInputDialog.getText(self, tr('Rinomina'), tr('Nuovo nome:'), text=n)
        if ok and nuovo.strip() and nuovo.strip() != n:
            try:
                core.rinomina_voce(n, nuovo.strip())
            except Exception as e:
                QMessageBox.warning(self, tr('Errore'), str(e))
            self._aggiorna_voci()

    def elimina_voce(self):
        n = self._voce_selezionata()
        if n and QMessageBox.question(self, tr('Elimina'), tr('Eliminare la voce di {n} e tutti i suoi campioni?', n=n)) == QMessageBox.Yes:
            core.elimina_voce(n)
            self._aggiorna_voci()

    def esporta_voci_iphone(self):
        """Anagrafe → Argo per iPhone: scelta delle persone, conferma del consenso, file .argovoci."""
        if not core.riconoscimento_attivo():
            QMessageBox.information(self, tr('Voci per iPhone'), tr('Attiva prima il riconoscimento delle voci.'))
            return
        voci = [n for n, _ in core.elenco_voci() if core.consenso(n) is not None]
        if not voci:
            QMessageBox.information(self, tr('Voci per iPhone'), tr('Nessuna voce con il consenso registrato.'))
            return
        imp = core.carica_impostazioni()
        dlg = voci_strumenti.EsportaIphoneDialog(voci, imp.get("voci_iphone"), self)
        if not dlg.exec() or not dlg.scelte:
            return
        imp["voci_iphone"] = dlg.scelte
        core.salva_impostazioni(imp)
        import ponte
        n = len(dlg.scelte)
        if ponte.dispositivi():
            # Con il Ponte l'iPhone scarica da solo la scelta; il file serve solo per altre vie (AirDrop).
            r = QMessageBox.question(
                self, tr('Voci per iPhone'),
                tr("Fatto: l'iPhone collegato riceverà {n} voci alla prossima sincronizzazione.\n\nVuoi anche un file .argovoci da passare con AirDrop?", n=n),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self.stato_voci.setText(tr("{n} voci pronte per l'iPhone (Ponte).", n=n))
                return
        predefinito = str(Path.home() / "Desktop" / ("anagrafe" + core.ESTENSIONE_IPHONE))
        f, _ = QFileDialog.getSaveFileName(self, tr("Salva l'anagrafe per iPhone"), predefinito,
                                           f"Anagrafe voci per iPhone (*{core.ESTENSIONE_IPHONE})")
        if not f:
            return
        try:
            percorso, n = core.esporta_per_iphone(f, dlg.scelte)
        except Exception as e:
            QMessageBox.warning(self, tr('Esportazione non riuscita'), str(e))
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(percorso)], check=False)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(percorso.parent)))
        self.stato_voci.setText(tr('{n} voci esportate in {name}.', n=n, name=percorso.name))
        QMessageBox.information(
            self, tr('Anagrafe per iPhone pronta'),
            tr('Ho salvato {n} voci in «{name}».\n\nSul Mac: tasto destro sul file › Condividi › AirDrop › il tuo iPhone, poi «Apri con Argo».\n\nContiene impronte vocali (dati biometrici): dopo il trasferimento cancellalo dal Mac.', n=n, name=percorso.name))

    # ------------------------------------------------------------ tab impostazioni
    def _tab_impostazioni(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        imp = core.carica_impostazioni()

        g1 = QGroupBox(tr('Hugging Face (serve solo per scaricare i modelli)'))
        f1 = QFormLayout(g1)
        self.e_token = QLineEdit(core.leggi_token())
        self.e_token.setEchoMode(QLineEdit.Password)
        self.e_token.setPlaceholderText(tr('hf_...'))
        riga = QHBoxLayout()
        riga.addWidget(self.e_token)
        b_mostra = QPushButton(tr('Mostra'))
        b_mostra.setCheckable(True)
        b_mostra.toggled.connect(lambda on: self.e_token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        b_ver = QPushButton(tr('Salva e verifica'))
        b_ver.clicked.connect(self.verifica_token)
        riga.addWidget(b_mostra)
        riga.addWidget(b_ver)
        f1.addRow(tr('Token (Read):'), riga)
        self.l_token = QLabel("")
        self.l_token.setWordWrap(True)
        f1.addRow("", self.l_token)
        link = QLabel(tr('1) <a href="https://huggingface.co/pyannote/speaker-diarization-community-1">Accetta le condizioni del modello</a> &nbsp; 2) <a href="https://huggingface.co/settings/tokens">Crea un token di tipo Read</a>'))
        link.setOpenExternalLinks(True)
        f1.addRow("", link)
        lay.addWidget(g1)

        g2 = QGroupBox(tr('Trascrizione'))
        f2 = QFormLayout(g2)
        self.c_modello = QComboBox()
        for k, t in MODELLI:
            self.c_modello.addItem(t, k)
        self.c_modello.setCurrentIndex(max(0, [k for k, _ in MODELLI].index(imp["model"]) if imp["model"] in [k for k, _ in MODELLI] else 0))
        self.c_lingua = QComboBox()
        for k, t in LINGUE:
            self.c_lingua.addItem(t, k)
        self.c_lingua.setCurrentIndex(next((i for i, (k, _) in enumerate(LINGUE) if k == imp["language"]), 0))
        self.c_device = QComboBox()
        self.c_device.addItem(tr('CPU (sempre disponibile)'), "cpu")
        self.c_device.addItem(tr('GPU NVIDIA (CUDA)'), "cuda")
        self.c_device.setCurrentIndex(1 if imp["device"] == "cuda" else 0)
        self.e_hot = QLineEdit(imp.get("hotwords", ""))
        self.e_hot.setPlaceholderText(tr('es. Copilot, Azure, EOS Solutions, nomi dei partecipanti'))
        f2.addRow(tr('Modello:'), self.c_modello)
        f2.addRow(tr('Lingua:'), self.c_lingua)
        f2.addRow(tr('Calcolo su:'), self.c_device)
        f2.addRow(tr('Parole chiave:'), self.e_hot)
        self.c_risorse = QComboBox()
        for k, testo in risorse.PROFILI:
            self.c_risorse.addItem(testo, k)
        self.c_risorse.setCurrentIndex(max(0, self.c_risorse.findData(imp.get("risorse", "auto"))))
        self.c_risorse.setToolTip(tr('Quanta CPU e memoria può usare Argo per trascrivere e per i riassunti.\nSe il PC si blocca durante le elaborazioni, scegli Leggero.'))
        self.l_risorse = QLabel()
        self.l_risorse.setWordWrap(True)
        self.c_risorse.currentIndexChanged.connect(
            lambda _i: self.l_risorse.setText(risorse.descrizione(self.c_risorse.currentData())))
        self.l_risorse.setText(risorse.descrizione(self.c_risorse.currentData()))
        f2.addRow(tr('Uso del computer:'), self.c_risorse)
        f2.addRow("", self.l_risorse)
        self.b_adatta = QPushButton(tr('🖥️ Adatta a questo computer…'))
        self.b_adatta.setToolTip(tr('Legge processore, core, RAM e GPU di questo computer e propone modello di trascrizione, uso del computer e modelli di Ollama adatti. Scegli tu cosa applicare.'))
        self.b_adatta.clicked.connect(self.adatta_al_computer)
        f2.addRow("", self.b_adatta)
        lay.addWidget(g2)

        g3 = QGroupBox(tr('Riconoscimento voci'))
        f3 = QFormLayout(g3)
        self.cb_riconoscimento = QCheckBox(tr('Riconosci le persone dalla voce (anagrafe voci, solo con il loro consenso)'))
        self.cb_riconoscimento.setChecked(core.riconoscimento_attivo())
        self.cb_riconoscimento.setEnabled(not core.riconoscimento_vietato())
        if core.riconoscimento_vietato():
            self.cb_riconoscimento.setToolTip(tr("Disattivato dall'IT con i criteri aziendali"))
        self.cb_riconoscimento.toggled.connect(self._cambia_riconoscimento)
        f3.addRow(self.cb_riconoscimento)
        self.s_soglia = QDoubleSpinBox()
        self.s_soglia.setRange(0.2, 0.95)
        self.s_soglia.setSingleStep(0.05)
        self.s_soglia.setValue(float(imp["soglia"]))
        f3.addRow(tr('Somiglianza minima:'), self.s_soglia)
        nota = QLabel(tr('Più alta = meno errori ma più «Sconosciuto». 0,50 è un buon punto di partenza.'))
        nota.setWordWrap(True)
        f3.addRow("", nota)
        lay.addWidget(g3)

        self.pannello_ollama = attrezzi.PannelloOllama()
        self.pannello_ollama.cambiato.connect(lambda: self._aggiorna_badge() if hasattr(self, "badge") else None)
        self.pannello_ollama.chiedi_consigliati.connect(lambda: self.prepara_ollama(forzato=True))
        lay.addWidget(self.pannello_ollama)
        self.pannello_cloud = attrezzi.PannelloCloud()
        self.pannello_cloud.cambiato.connect(lambda: self._aggiorna_badge() if hasattr(self, "badge") else None)
        lay.addWidget(self.pannello_cloud)

        g6 = QGroupBox(tr('Microsoft 365 (facoltativo) · per Agenda, Posta e Incarichi'))
        f6 = QFormLayout(g6)
        self.e_m365_client = QLineEdit(imp.get("m365_client_id", ""))
        self.e_m365_client.setPlaceholderText(tr("Application (client) ID dell'app registrata in Entra ID"))
        self.e_m365_tenant = QLineEdit(imp.get("m365_tenant_id", ""))
        self.e_m365_tenant.setPlaceholderText(tr('Directory (tenant) ID'))
        f6.addRow(tr('Client ID:'), self.e_m365_client)
        f6.addRow(tr('Tenant ID:'), self.e_m365_tenant)
        r6 = QHBoxLayout()
        self.b_m365 = QPushButton(tr('Collega'))
        self.b_m365.clicked.connect(self.collega_m365)
        self.b_m365_off = QPushButton(tr('Scollega'))
        self.b_m365_off.clicked.connect(self.scollega_m365)
        self.l_m365 = QLabel("")
        self.l_m365.setWordWrap(True)
        r6.addWidget(self.b_m365)
        r6.addWidget(self.b_m365_off)
        r6.addWidget(self.l_m365, 1)
        f6.addRow("", r6)
        self.cb_posta = QCheckBox(tr('Leggi la posta per «Posta AI» (le mail vengono elaborate su questo computer, salvo un modello cloud scelto per Posta)'))
        self.cb_posta.setChecked(bool(imp.get("m365_leggi_posta")))
        self.cb_posta.toggled.connect(self._pref_posta)
        f6.addRow("", self.cb_posta)
        n6 = QLabel(tr('Su Microsoft 365 vanno solo i risultati che confermi (bozze di Outlook, task in Planner). Argo legge il calendario per Agenda e Incarichi e, solo se lo attivi, la posta per Posta AI: i testi vengono elaborati dal modello locale. Audio, trascrizioni e documenti restano qui.'))
        n6.setWordWrap(True)
        n6.setProperty("ruolo", "tenue")
        f6.addRow("", n6)
        lay.addWidget(g6)

        g7 = QGroupBox(tr('Dynamics 365 Sales (facoltativo) · per Incontri e Clienti'))
        f7 = QFormLayout(g7)
        self.e_d365 = QLineEdit(imp.get("d365_url", ""))
        self.e_d365.setPlaceholderText("https://nome-ambiente.crm4.dynamics.com")
        f7.addRow(tr('Ambiente:'), self.e_d365)
        r7 = QHBoxLayout()
        self.b_d365 = QPushButton(tr('Collega'))
        self.b_d365.clicked.connect(self.collega_d365)
        self.l_d365 = QLabel(tr('Usa Client ID e Tenant ID di Microsoft 365 qui sopra.'))
        self.l_d365.setWordWrap(True)
        r7.addWidget(self.b_d365)
        r7.addWidget(self.l_d365, 1)
        f7.addRow("", r7)
        n7 = QLabel(tr("Nell'app Entra di Argo serve in più il permesso delegato «Dynamics CRM · user_impersonation» (API permissions › Add › Dynamics CRM, poi «Grant admin consent»). Su Dynamics vanno solo i dati che confermi nella finestra «Invia a Dynamics» di un incontro."))
        n7.setWordWrap(True)
        n7.setProperty("ruolo", "tenue")
        f7.addRow("", n7)
        lay.addWidget(g7)

        g8 = QGroupBox(tr('Ricerca web (facoltativa) · scheda pubblica dei clienti'))
        f8 = QFormLayout(g8)
        import ricerca_web
        self.e_web = QLineEdit(ricerca_web.chiave())
        self.e_web.setEchoMode(QLineEdit.Password)
        self.e_web.setPlaceholderText(tr('Chiave API di Ollama Web Search (ollama.com › Settings › Keys)'))
        f8.addRow(tr('Chiave:'), self.e_web)
        r8 = QHBoxLayout()
        b_web = QPushButton(tr('Salva e prova'))
        b_web.clicked.connect(self.prova_ricerca_web)
        self.l_web = QLabel("")
        self.l_web.setWordWrap(True)
        r8.addWidget(b_web)
        r8.addWidget(self.l_web, 1)
        f8.addRow("", r8)
        n8 = QLabel(tr("Serve un account Ollama gratuito. Sul web esce solo il nome dell'azienda cercata: trascrizioni, partecipanti e documenti restano qui. La scheda la scrive il modello locale, solo dalle pagine trovate, con le regole di Client Intel Scout."))
        n8.setWordWrap(True)
        n8.setProperty("ruolo", "tenue")
        f8.addRow("", n8)
        lay.addWidget(g8)

        g5 = QGroupBox(tr('Aspetto'))
        f5 = QHBoxLayout(g5)
        f5.addWidget(QLabel(tr('Tema:')))
        self.c_tema = QComboBox()
        for etichetta, val in ((tr("Notte (scuro)"), "scuro"), (tr("Carta (chiaro)"), "chiaro"),
                               (tr("Come il sistema"), "sistema")):
            self.c_tema.addItem(etichetta, val)
        self.c_tema.setCurrentIndex(max(0, self.c_tema.findData(imp.get("tema", "scuro"))))
        self.c_tema.currentIndexChanged.connect(lambda _: self.cambia_tema(self.c_tema.currentData()))
        f5.addWidget(self.c_tema)
        # Lingua dell'interfaccia (non delle trascrizioni): vale dal prossimo avvio
        f5.addSpacing(24)
        f5.addWidget(QLabel(tr("Lingua:")))
        self.c_lingua = QComboBox()
        self.c_lingua.addItem(tr("Come il sistema"), "auto")
        for codice, nome in lingua.LINGUE.items():
            self.c_lingua.addItem(nome, codice)  # ogni lingua scritta nella sua lingua
        self.c_lingua.setCurrentIndex(max(0, self.c_lingua.findData(imp.get("lingua_interfaccia", "auto"))))
        self.c_lingua.currentIndexChanged.connect(lambda _: self.cambia_lingua(self.c_lingua.currentData()))
        self.c_lingua.setToolTip(tr("Lingua dei menu e delle finestre di Argo. Trascrizioni e relazioni hanno la loro lingua."))
        f5.addWidget(self.c_lingua)
        f5.addStretch()
        lay.addWidget(g5)

        g4 = QGroupBox(tr('Aggiornamenti · versione installata {versione}', versione=VERSIONE))
        f4 = QVBoxLayout(g4)
        crit = criteri.carica()
        r_canale = QHBoxLayout()
        r_canale.addWidget(QLabel(tr('Canale:')))
        self.c_canale = QComboBox()
        for val, etichetta in aggiornamenti.CANALI.items():
            self.c_canale.addItem(etichetta, val)
        self.c_canale.setCurrentIndex(max(0, self.c_canale.findData(aggiornamenti.canale_effettivo(imp, crit))))
        self.c_canale.currentIndexChanged.connect(lambda _: self._salva_canale(self.c_canale.currentData()))
        r_canale.addWidget(self.c_canale)
        r_canale.addStretch()
        f4.addLayout(r_canale)
        if "canale_aggiornamenti" in crit:
            self.c_canale.setEnabled(False)
            self.c_canale.setToolTip(tr("Impostato dall'IT con i criteri aziendali"))
        nota_canale = QLabel(tr('<b>Pro</b>: solo versioni rilasciate, con pacchetto verificato (impronta SHA-256 e firma) e librerie a versione fissa. <b>Lab</b>: ogni novità appena pubblicata, senza verifiche: per chi sperimenta.'))
        nota_canale.setWordWrap(True)
        f4.addWidget(nota_canale)
        self.cb_agg = QCheckBox(tr("Controlla all'avvio se su GitHub c'è una versione nuova"))
        self.cb_agg.setChecked(bool(imp.get("controlla_aggiornamenti", True)))
        self.cb_agg.toggled.connect(self._salva_pref_agg)
        f4.addWidget(self.cb_agg)
        nota_agg = QLabel(tr("Argo legge da GitHub solo il numero dell'ultima versione e le novità: nessun dato, audio o documento viene inviato. Voci, impostazioni e glossario restano dove sono."))
        nota_agg.setWordWrap(True)
        f4.addWidget(nota_agg)
        r4 = QHBoxLayout()
        self.b_agg = QPushButton(tr('Controlla ora'))
        self.b_agg.clicked.connect(lambda: self.controlla_aggiornamenti(manuale=True))
        b_gh = QPushButton(tr('Apri GitHub'))
        b_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(aggiornamenti.URL_GITHUB)))
        self.l_agg = QLabel("")
        r4.addWidget(self.b_agg)
        r4.addWidget(b_gh)
        r4.addWidget(self.l_agg, 1)
        f4.addLayout(r4)
        if crit.get("aggiornamenti_dall_app") is False:
            for wdg in (self.cb_agg, self.b_agg, self.c_canale):
                wdg.setEnabled(False)
            self.l_agg.setText(tr("Gli aggiornamenti di Argo li distribuisce l'IT."))
        if crit:
            nota_it = QLabel(tr("🏢 Alcune impostazioni sono gestite dall'IT ({percorso}).", percorso=criteri.percorso()))
            nota_it.setWordWrap(True)
            f4.addWidget(nota_it)
        lay.addWidget(g4)

        # Disinstallare Argo: senza scaricare niente
        g9 = QGroupBox(tr('Disinstallare Argo'))
        l9 = QVBoxLayout(g9)
        if os.name == "nt":
            dove = ("Anche da Impostazioni di Windows › App › App installate › «Argo AI» › Disinstalla, "
                    "o dal menu Start › «Disinstalla Argo».")
        else:
            dove = ("Trascinare Argo AI nel Cestino non basta: resterebbe la cartella whisperx-env con i dati. "
                    "Usa questo pulsante.")
        t9 = QLabel("Chiede conferma e propone un backup sulla Scrivania di voci, incontri, clienti, glossario e "
                    "impostazioni (senza token e chiavi), poi elimina Argo e la cartella whisperx-env. "
                    "Ollama, i suoi modelli e le cache dei modelli restano. " + dove)
        t9.setWordWrap(True)
        t9.setProperty("ruolo", "tenue")
        l9.addWidget(t9)
        b9 = QPushButton(tr('Disinstalla Argo…'))
        b9.clicked.connect(self.disinstalla)
        r9 = QHBoxLayout()
        r9.addWidget(b9)
        r9.addStretch(1)
        l9.addLayout(r9)

        # Relazioni: i template (editor in incontri.py)
        import incontri
        g_rel = QGroupBox(tr('Template della relazione degli incontri'))
        lr = QVBoxLayout(g_rel)
        spiega = QLabel(tr('Un template dice come scrivere la relazione: quali sezioni e in che ordine, quanto lunga, e le tue indicazioni («come la voglio»). Si sceglie in Incontri accanto a «✨ Scrivi relazione»; il ★ predefinito vale anche per Clienti › Dalla call.'))
        spiega.setWordWrap(True)
        spiega.setProperty("ruolo", "tenue")
        lr.addWidget(spiega)
        self.editor_template = incontri.EditorTemplate()
        self.editor_template.cambiato.connect(
            lambda: self.tab_incontri.carica_template() if hasattr(self, "tab_incontri") else None)
        lr.addWidget(self.editor_template)

        self.pannello_supporto = supporto.PannelloSupporto(self)
        self.pannello_backup = backup_ui.PannelloBackup(self)

        # Pagina a argomenti (Stile Argo): colonna a sinistra, a destra solo l'argomento scelto
        self._categorie_imp = [
            (tr("🎙  Trascrizione e voci"), tr("Token, modelli di trascrizione, uso del computer, riconoscimento delle voci"),
             [("hf", g1), ("trascrizione", g2), ("voci", g3)]),
            (tr("🧠  Modelli AI"), tr("Ollama su questo computer e, se vuoi, modelli cloud attrezzo per attrezzo"),
             [("ollama", self.pannello_ollama), ("cloud", self.pannello_cloud)]),
            (tr("📝  Relazioni"), tr("Template delle relazioni: sezioni, lunghezza, come le vuoi"),
             [("relazioni", g_rel)]),
            (tr("🔗  Collegamenti"), tr("Microsoft 365, Dynamics 365 Sales e ricerca web: tutti facoltativi"),
             [("m365", g6), ("dynamics", g7), ("web", g8)]),
            (tr("⚙️  Aspetto e aggiornamenti"), tr("Tema chiaro o scuro, lingua, canale e aggiornamenti di Argo"),
             [("aspetto", g5), ("aggiornamenti", g4), ("disinstalla", g9)]),
            (tr("💾  Backup e più computer"),
             tr("Backup ora, alla chiusura e programmati; ripristino anche da OneDrive e Google Drive; configurazione condivisa tra Mac e Windows"),
             self.pannello_backup.gruppi),
            (tr("🛟  Supporto"), tr("Cosa è uscito da questo computer, chiedi supporto, modalità trace, registro e versione precedente"),
             self.pannello_supporto.gruppi),
        ]
        radice = QWidget()
        rl = QVBoxLayout(radice)
        corpo = QHBoxLayout()
        self.nav_imp = QListWidget()
        self.nav_imp.setFixedWidth(230)
        self.nav_imp.setSpacing(2)
        self.pile_imp = QStackedWidget()
        self._sezioni_imp, self._pagina_di_sezione, self._scorri_imp = {}, {}, []
        for n, (titolo, descrizione, gruppi) in enumerate(self._categorie_imp):
            voce = QListWidgetItem(titolo)
            voce.setToolTip(descrizione)
            voce.setSizeHint(QSize(0, 38))
            self.nav_imp.addItem(voce)
            contenuto = QWidget()
            cl = QVBoxLayout(contenuto)
            cl.setContentsMargins(4, 0, 12, 12)
            t_cat = QLabel(titolo.replace("  ", " "))
            t_cat.setProperty("ruolo", "sezione")
            cl.addWidget(t_cat)
            d_cat = QLabel(descrizione)
            d_cat.setProperty("ruolo", "tenue")
            d_cat.setWordWrap(True)
            cl.addWidget(d_cat)
            for chiave, gruppo in gruppi:
                cl.addWidget(gruppo)
                self._sezioni_imp[chiave] = gruppo
                self._pagina_di_sezione[chiave] = n
            cl.addStretch()
            scorri = QScrollArea()
            scorri.setWidgetResizable(True)
            scorri.setFrameShape(QFrame.NoFrame)
            scorri.setWidget(contenuto)
            self._scorri_imp.append(scorri)
            self.pile_imp.addWidget(scorri)
        self.nav_imp.currentRowChanged.connect(self.pile_imp.setCurrentIndex)
        self.nav_imp.setCurrentRow(0)
        corpo.addWidget(self.nav_imp)
        corpo.addWidget(self.pile_imp, 1)
        rl.addLayout(corpo, 1)

        riga2 = QHBoxLayout()
        b_salva = QPushButton(tr('Salva impostazioni'))
        b_salva.setProperty("primario", True)  # sempre in vista, qualunque argomento sia aperto
        b_salva.setToolTip(tr('Salva token, trascrizione, voci, collegamenti e aggiornamenti. Modelli, modelli cloud e template si salvano già nei loro riquadri.'))
        b_salva.clicked.connect(self.salva_impostazioni)
        b_dati = QPushButton(tr('Apri cartella dati'))
        b_dati.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.APP_HOME))))
        riga2.addWidget(b_salva)
        riga2.addWidget(b_dati)
        info = QLabel(tr("Dati in: {app_home}  ·  L'audio non lascia mai questo computer.", app_home=core.APP_HOME))
        info.setProperty("ruolo", "tenue")
        riga2.addWidget(info, 1)
        rl.addLayout(riga2)
        return radice

    def _aggiorna_supporto(self):
        if hasattr(self, "pannello_supporto"):
            self.pannello_supporto.aggiorna()

    def disinstalla(self):
        if QMessageBox.question(
                self, tr('Disinstallare Argo?'),
                tr('Si apre il disinstallatore in una finestra a parte e Argo si chiude.\n\nLì potrai fare un backup e confermare: finché non confermi non viene cancellato niente.')) \
                != QMessageBox.Yes:
            return
        if getattr(self, "tab_incontri", None) and self.tab_incontri.occupata():
            QMessageBox.information(self, tr('Un momento'), tr("C'è un'elaborazione in corso negli Incontri: aspetta che finisca o fermala, poi riprova."))
            return
        try:
            partito = disinstalla.avvia()
        except Exception as e:
            partito = False
            QMessageBox.warning(self, tr('Disinstallazione'), tr('Non riesco ad aprire il disinstallatore: {e}', e=e))
            return
        if not partito:
            QMessageBox.warning(self, tr('Disinstallazione'), tr('Disinstallatore non trovato in questa installazione: usa Disinstalla-Argo dal pacchetto di Argo (vedi il manuale, §14).'))
            return
        QTimer.singleShot(800, self.close)  # closeEvent: ferma Ponte e lavori, salva le code

    def _stato_m365(self):
        acc = m365.account()
        if hasattr(self, "l_m365"):
            self.l_m365.setText(tr('✅ Collegato come {acc}', acc=acc) if acc else tr('Non collegato'))
            self.b_m365_off.setVisible(bool(acc))  # Scollega solo se collegato
        if hasattr(self, "tab_incarichi"):
            self.tab_incarichi.aggiorna_m365()
        for s in ("tab_agenda", "tab_posta"):
            if hasattr(self, s):
                getattr(self, s).aggiorna_stato()
        self._aggiorna_badge()

    def _pref_posta(self, on):
        imp = core.carica_impostazioni()
        imp["m365_leggi_posta"] = bool(on)
        core.salva_impostazioni(imp)
        if hasattr(self, "tab_posta"):
            self.tab_posta.mail = []
            self.tab_posta.aggiorna_stato()

    def collega_m365(self):
        imp = core.carica_impostazioni()
        imp["m365_client_id"] = self.e_m365_client.text().strip()
        imp["m365_tenant_id"] = self.e_m365_tenant.text().strip()
        core.salva_impostazioni(imp)
        if not m365.configurato():
            QMessageBox.warning(self, tr('Microsoft 365'), tr('Inserisci Client ID e Tenant ID.'))
            return
        self.l_m365.setText(tr('Si è aperto il browser: accedi con il tuo account Microsoft e accetta i permessi (hai 5 minuti)…'))
        self.b_m365.setEnabled(False)
        lav = attrezzi.Lavoro(lambda _l: m365.accedi_interattivo(), self)

        def fine(_u):
            self.b_m365.setEnabled(True)
            self._stato_m365()
            self.raise_()
            self.activateWindow()

        def errore(e):
            self.b_m365.setEnabled(True)
            self._stato_m365()
            QMessageBox.warning(self, tr('Microsoft 365'), e)

        lav.sig_fine.connect(fine)
        lav.sig_errore.connect(errore)
        self._lav_m365 = lav
        lav.start()

    def collega_d365(self):
        import crm_dynamics
        imp = core.carica_impostazioni()
        imp["m365_client_id"] = self.e_m365_client.text().strip()
        imp["m365_tenant_id"] = self.e_m365_tenant.text().strip()
        imp["d365_url"] = self.e_d365.text().strip()
        core.salva_impostazioni(imp)
        if not crm_dynamics.configurato():
            QMessageBox.warning(self, tr('Dynamics 365'), tr("Inserisci Client ID e Tenant ID (Microsoft 365) e l'indirizzo dell'ambiente Dynamics."))
            return
        self.l_d365.setText(tr('Si è aperto il browser: accedi e accetta il permesso per Dynamics (hai 5 minuti)…'))
        self.b_d365.setEnabled(False)
        lav = attrezzi.Lavoro(lambda _l: crm_dynamics.accedi(), self)

        def fine(utente):
            self.b_d365.setEnabled(True)
            self.l_d365.setText(tr('✅ Collegato a {ambiente} come {utente}', ambiente=crm_dynamics.ambiente(), utente=utente))
            self.raise_()
            self.activateWindow()

        def errore(e):
            self.b_d365.setEnabled(True)
            self.l_d365.setText(f"⚠️ {e}")

        lav.sig_fine.connect(fine)
        lav.sig_errore.connect(errore)
        self._lav_d365 = lav
        lav.start()

    def prova_ricerca_web(self):
        import ricerca_web
        ricerca_web.salva_chiave(self.e_web.text())
        self.l_web.setText(tr('Provo…'))
        lav = attrezzi.Lavoro(lambda _l: ricerca_web.cerca("Argo AI Ollama", 1), self)
        lav.sig_fine.connect(lambda r: self.l_web.setText(tr('✅ Ricerca web attiva.') if r is not None else tr('⚠️ Nessuna risposta.')))
        lav.sig_errore.connect(lambda e: self.l_web.setText(f"⚠️ {e}"))
        self._lav_web = lav
        lav.start()
        if hasattr(self, "tab_clienti"):
            self.tab_clienti._aggiorna_stato_servizi()

    def scollega_m365(self):
        m365.scollega()
        self._stato_m365()

    def cambia_lingua(self, codice):
        imp = core.carica_impostazioni()
        if imp.get("lingua_interfaccia", "auto") == codice:
            return
        imp["lingua_interfaccia"] = codice
        core.salva_impostazioni(imp)
        nuova = lingua.scegli(imp)
        risposta = QMessageBox.question(
            self, tr("Lingua dell'interfaccia"),
            tr("La nuova lingua vale dal prossimo avvio di Argo. Riavvio adesso?"))
        if risposta == QMessageBox.Yes:
            diagnostica.log.info("lingua dell'interfaccia: %s, riavvio", nuova)
            self._salva_coda()
            aggiornamenti.riavvia()
            QApplication.quit()

    def cambia_tema(self, nome):
        imp = core.carica_impostazioni()
        imp["tema"] = nome
        core.salva_impostazioni(imp)
        tema.applica(QApplication.instance(), nome)
        self.nav.ricolora()
        self._aggiorna_badge()
        self._ridisegna_coda()
        self._aggiorna_dettaglio()

    # ------------------------------------------------------------ aggiornamenti
    def _salva_pref_agg(self, on):
        imp = core.carica_impostazioni()
        imp["controlla_aggiornamenti"] = bool(on)
        core.salva_impostazioni(imp)

    def _salva_canale(self, canale):
        imp = core.carica_impostazioni()
        imp["canale_aggiornamenti"] = canale
        core.salva_impostazioni(imp)
        if hasattr(self, "l_agg"):
            self.l_agg.setText(tr('Canale {capitalize}: premi «Controlla ora».', capitalize=canale.capitalize()))

    def _canale(self):
        return aggiornamenti.canale_effettivo(core.carica_impostazioni(), criteri.carica())

    # ------------------------------------------------------------ Ollama pronto all'avvio
    def prepara_ollama(self, forzato=False):
        """Accende Ollama se serve, sceglie i modelli installati e propone quelli consigliati che mancano."""
        if getattr(self, "_lav_modelli", None):
            return
        url = core.carica_impostazioni().get("ollama_url") or llm_locale.DEFAULT_URL

        def lavoro(lav):
            r = modelli_ollama.controlla(url, lav.stato, stop=lav.fermato)
            r["vision"] = self._vision_installati(url) if r["esito"] == "ok" else []
            r["dim"] = llm_locale.dimensioni(url) if r["esito"] == "ok" and llm_locale.e_locale(url) else {}
            return r

        lav = attrezzi.Lavoro(lavoro, self)
        lav.sig_stato.connect(lambda m: self.statusBar().showMessage(m, 10000))
        lav.sig_fine.connect(lambda r: self._esito_ollama(r, url, forzato))
        lav.sig_errore.connect(lambda e: (setattr(self, "_lav_modelli", None),
                                          self.statusBar().showMessage(tr('Ollama: {e}', e=e), 10000)))
        self._lav_modelli = lav
        lav.start()

    @staticmethod
    def _vision_installati(url):
        import relazione_incontro
        try:
            return relazione_incontro.modelli_vision(url)
        except Exception:
            return []

    def _scegli_modelli(self, r):
        """Sceglie i modelli mancanti tra quelli installati (anche quello per le foto, la prima volta)."""
        s = core.carica_impostazioni()
        scelti = attrezzi.completa_modelli(s, r["chat"], r["emb"])
        if s.get("modello_vision") is None and r.get("vision"):  # mai scelto: il modello dei testi, se vede le foto
            s["modello_vision"] = s["modello_chat"] if s.get("modello_chat") in r["vision"] else r["vision"][0]
            core.salva_impostazioni(s)
            scelti.append(f"foto: {s['modello_vision']}")
        adattati = modelli_ollama.adatta(s, r["chat"], r.get("vision", []), r.get("dim") or {})
        if adattati:  # il modello scelto non sta nella RAM di questo computer: si passa a uno che ci sta
            core.salva_impostazioni(s)
            logging.getLogger("argo").info("modelli adattati al computer: %s", "; ".join(adattati))
            scelti += adattati
        attrezzi.segnale_modelli.cambiato.emit()  # aggiorna gli elenchi delle Impostazioni
        return scelti

    def _esito_ollama(self, r, url, forzato):
        self._lav_modelli = None
        if r["esito"] == "assente":
            msg = "Ollama non è installato: per Verbale, Documenti, Dettatura, Traduzione e Incontri scaricalo da ollama.com."
            if forzato:
                QMessageBox.information(self, tr('Ollama non installato'), msg)
            self.statusBar().showMessage(msg, 15000)
            return
        if r["esito"] != "ok":
            msg = f"Ollama non risponde su {url}: avvialo e riprova da Impostazioni › Ollama."
            if forzato:
                QMessageBox.warning(self, tr('Ollama spento'), msg)
            self.statusBar().showMessage(msg, 15000)
            return
        scelti = self._scegli_modelli(r)
        if scelti:
            self.statusBar().showMessage("Modelli scelti in automatico: " + ", ".join(scelti)
                                         + ". Puoi cambiarli in Impostazioni › Ollama.", 15000)
        da_scaricare = modelli_ollama.mancanti(r["chat"], r["emb"], r.get("dim"))
        self._modelli_troppo_grandi = modelli_ollama.troppo_grandi(r["chat"], r.get("dim") or {})
        if not da_scaricare:
            if forzato:
                QMessageBox.information(self, tr('Modelli già presenti'),
                                        tr('Ollama ha già un modello per i testi e uno per i documenti.\nPer aggiungerne altri usa «Scarica un modello».'))
            return
        s = core.carica_impostazioni()
        chiave = "modello_leggero_rifiutato" if self._modelli_troppo_grandi else "modelli_consigliati_rifiutati"
        if not forzato and s.get(chiave):
            return
        self._proponi_modelli(da_scaricare, url, forzato)

    def _proponi_modelli(self, nomi, url, forzato):
        ruoli = {modelli_ollama.EMBED_CONSIGLIATO: "per cercare nei documenti"}
        righe = [f"•  {n} (circa {modelli_ollama.DIMENSIONI_GB.get(n, 0):.1f} GB) - "
                 + ruoli.get(n, "per verbali, riassunti, traduzioni e relazioni, anche dalle foto") for n in nomi]
        box = QMessageBox(self)
        box.setWindowTitle(tr("Modelli per l'AI locale"))
        box.setIcon(QMessageBox.Question)
        premessa = (f"I modelli per i testi installati in Ollama sono troppo grandi per i {risorse.ram_gb():.0f} GB di "
                    "RAM di questo computer: relazioni e verbali andrebbero in errore o sarebbero lentissimi.\n\n"
                    if getattr(self, "_modelli_troppo_grandi", False) else "")
        box.setText(premessa + "Per gli attrezzi AI di Argo servono questi modelli, che in Ollama mancano:\n\n"
                    + "\n".join(righe)
                    + f"\n\nTotale circa {modelli_ollama.peso(nomi):.1f} GB, una volta sola. Restano su questo "
                    "computer: nessun testo esce. Li scarico adesso? Poi li scelgo io, e tu potrai cambiarli "
                    "in Impostazioni › Ollama.")
        si = box.addButton(tr('Scarica ora'), QMessageBox.AcceptRole)
        box.addButton(tr('Non ora'), QMessageBox.RejectRole)
        box.setDefaultButton(si)
        box.exec()
        if box.clickedButton() is not si:
            if not forzato:
                s = core.carica_impostazioni()
                s["modello_leggero_rifiutato" if getattr(self, "_modelli_troppo_grandi", False)
                  else "modelli_consigliati_rifiutati"] = True
                core.salva_impostazioni(s)
            self.statusBar().showMessage(tr('Puoi scaricarli quando vuoi: Impostazioni › Ollama › «Scarica modelli consigliati».'), 15000)
            return

        def lavoro(lav):
            fatti = modelli_ollama.scarica(nomi, url, lav.stato, lav.fermato)
            chat, emb = llm_locale.elenco_modelli(url)
            return {"esito": "ok", "chat": chat, "emb": emb, "vision": self._vision_installati(url), "fatti": fatti,
                    "dim": llm_locale.dimensioni(url) if llm_locale.e_locale(url) else {}}

        lav = attrezzi.Lavoro(lavoro, self)
        lav.sig_stato.connect(self._stato_download)
        lav.sig_fine.connect(self._download_finito)
        lav.sig_errore.connect(lambda e: (setattr(self, "_lav_modelli", None),
                                          self._stato_download(f"❌ Download non riuscito: {e}", 0)))
        self._lav_modelli = lav
        lav.start()

    def _stato_download(self, testo, durata=0):
        self.statusBar().showMessage(testo, durata)
        if hasattr(self, "pannello_ollama"):
            self.pannello_ollama.l_stato.setText(testo)

    def _download_finito(self, r):
        self._lav_modelli = None
        if not r.get("fatti"):
            self._stato_download("Download interrotto.", 10000)
            return
        s = core.carica_impostazioni()
        s.pop("modelli_consigliati_rifiutati", None)
        core.salva_impostazioni(s)
        scelti = self._scegli_modelli(r)
        self._stato_download("✅ Modelli pronti: " + ", ".join(r["fatti"])
                             + (". Scelti: " + ", ".join(scelti) if scelti else "")
                             + ". Puoi cambiarli in Impostazioni › Ollama.", 20000)

    def controlla_aggiornamenti(self, manuale=False):
        if getattr(self, "_lav_agg", None):
            return
        if criteri.carica().get("aggiornamenti_dall_app") is False:
            return
        canale = self._canale()
        if hasattr(self, "l_agg"):
            self.l_agg.setText(tr('Controllo su GitHub (canale {capitalize})…', capitalize=canale.capitalize()))
        lav = attrezzi.Lavoro(lambda _l: aggiornamenti.controlla(VERSIONE, canale), self)
        lav.sig_fine.connect(lambda r: self._esito_controllo(r, manuale))
        lav.sig_errore.connect(lambda e: self._errore_controllo(e, manuale))
        self._lav_agg = lav
        lav.start()

    def _errore_controllo(self, e, manuale):
        self._lav_agg = None
        if hasattr(self, "l_agg"):
            self.l_agg.setText(tr('Controllo non riuscito (sei offline?)'))
        if manuale:
            QMessageBox.warning(self, tr('Aggiornamenti'), tr('Non riesco a contattare GitHub:\n{e}', e=e))

    def _esito_controllo(self, r, manuale):
        self._lav_agg = None
        nuova, remota, testo = r
        if not nuova:
            if hasattr(self, "l_agg"):
                self.l_agg.setText(tr("✅ Hai l'ultima versione ({versione}).", versione=VERSIONE))
            if manuale:
                QMessageBox.information(self, tr('Aggiornamenti'), tr("Hai già l'ultima versione ({versione}).", versione=VERSIONE))
            return
        if hasattr(self, "l_agg"):
            self.l_agg.setText(tr('🆕 Disponibile la versione {remota}.', remota=remota))
        self._proponi_aggiornamento(remota, testo)

    def _proponi_aggiornamento(self, remota, testo):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Nuova versione di Argo'))
        dlg.resize(620, 480)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(tr("<b>È disponibile la versione {remota}</b> (hai la {versione}).<br>L'aggiornamento sostituisce solo i file del programma: voci, token, impostazioni, glossario e documenti indicizzati restano come sono.", remota=remota, versione=VERSIONE)))
        box = QPlainTextEdit(testo or "Novità: vedi CHANGELOG su GitHub.")
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        bar = QHBoxLayout()
        b_ora = QPushButton(tr('Aggiorna ora'))
        b_ora.setProperty("primario", True)
        b_dopo = QPushButton(tr('Più tardi'))
        b_gh = QPushButton(tr('Apri GitHub'))
        bar.addWidget(b_gh)
        bar.addStretch()
        bar.addWidget(b_dopo)
        bar.addWidget(b_ora)
        lay.addLayout(bar)
        b_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(aggiornamenti.URL_GITHUB)))
        b_dopo.clicked.connect(dlg.reject)
        b_ora.clicked.connect(dlg.accept)
        if dlg.exec():
            self.installa_aggiornamento()

    def installa_aggiornamento(self):
        if self.worker or self.worker_voce:
            QMessageBox.information(self, tr('Aggiornamento'), tr("Aspetta che finisca l'elaborazione in corso, poi riprova."))
            return
        if criteri.carica().get("aggiornamenti_dall_app") is False:
            QMessageBox.information(self, tr('Aggiornamento'), tr("Gli aggiornamenti di Argo li distribuisce l'IT."))
            return
        cartella = Path(__file__).resolve().parent
        canale = self._canale()
        lav = attrezzi.Lavoro(lambda l: aggiornamenti.installa(cartella, l.stato, canale), self)
        lav.sig_stato.connect(lambda t: self.statusBar().showMessage(t))
        lav.sig_fine.connect(self._fine_aggiornamento)
        lav.sig_errore.connect(lambda e: (QMessageBox.warning(
            self, tr('Aggiornamento non riuscito'),
            tr("{e}\n\nLa versione attuale non è stata toccata. Puoi scaricare il pacchetto da GitHub e rilanciare l'installer.", e=e)),
            setattr(self, "_lav_inst", None)))
        self._lav_inst = lav
        self.statusBar().showMessage(tr('Aggiornamento in corso…'))
        lav.start()

    def _fine_aggiornamento(self, esito):
        self._lav_inst = None
        lib = esito["librerie"]
        extra = ""
        if lib == "manca_uv":
            extra = ("\n\nQuesta versione richiede librerie nuove e non trovo «uv» per installarle: "
                     "scarica il pacchetto da GitHub e rilancia l'installer.")
        elif lib.startswith("errore"):
            extra = f"\n\nAggiornamento delle librerie non riuscito: {lib[7:]}\nRilancia l'installer dal pacchetto su GitHub."
        r = QMessageBox.question(
            self, tr('Aggiornamento installato'),
            tr('Argo {versione} è installato (canale {capitalize}, verifica: {get}).{extra}\n\nRiavvio Argo adesso per usarlo?\n(La versione precedente è salvata in {backup}.)', versione=esito['versione'], capitalize=esito.get('canale', 'lab').capitalize(), get=esito.get('verifica', 'nessuna'), extra=extra, backup=esito['backup']),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        self.statusBar().showMessage(tr('Aggiornato alla versione {versione}.', versione=esito['versione']))
        if r == QMessageBox.Yes:
            self._salva_coda()
            aggiornamenti.riavvia()
            QApplication.quit()

    def verifica_token(self):
        tok = self.e_token.text().strip()
        if not tok.startswith("hf_"):
            self.l_token.setText(tr('❌ Il token deve iniziare con hf_'))
            return
        core.salva_token(tok)
        self.l_token.setText(tr('Verifica in corso…'))
        QApplication.processEvents()
        ok, msg = core.verifica_token(tok)
        self.l_token.setText(("✅ " if ok else "❌ ") + msg)

    def adatta_al_computer(self):
        """Pulsante «Adatta a questo computer»: legge il computer (e Ollama, da un thread) e propone i cambi."""
        if getattr(self, "_lav_adatta", None):
            return
        s = core.carica_impostazioni()
        url = s.get("ollama_url") or llm_locale.DEFAULT_URL

        def lavoro(_lav):
            pc = adatta_computer.computer()
            ollama = adatta_computer.leggi_ollama(url)
            return pc, ollama, adatta_computer.proposte(s, pc, ollama)

        self.b_adatta.setEnabled(False)
        self.b_adatta.setText(tr("Leggo com'è fatto il computer…"))
        lav = attrezzi.Lavoro(lavoro, self)
        lav.sig_fine.connect(lambda r: self._mostra_adatta(*r, url))
        lav.sig_errore.connect(lambda e: (self._fine_adatta(), QMessageBox.warning(self, tr('Adatta a questo computer'), e)))
        self._lav_adatta = lav
        lav.start()

    def _fine_adatta(self):
        self._lav_adatta = None
        self.b_adatta.setEnabled(True)
        self.b_adatta.setText(tr('🖥️ Adatta a questo computer…'))

    def _mostra_adatta(self, pc, ollama, proposte, url):
        self._fine_adatta()
        d = QDialog(self)
        d.setWindowTitle(tr('Adatta a questo computer'))
        d.setMinimumWidth(620)
        lay = QVBoxLayout(d)
        testa = QLabel(f"<b>Questo computer:</b> {adatta_computer.descrivi(pc)}"
                       + ("" if ollama is not None else "<br>Ollama non risponde su questo computer: i modelli di "
                          "Ollama non sono controllati."))
        testa.setWordWrap(True)
        lay.addWidget(testa)
        caselle = []
        if not proposte:
            lay.addWidget(QLabel(tr('✅ La configurazione è già adatta a questo computer.')))
        else:
            lay.addWidget(QLabel(tr('Cambi consigliati (togli la spunta a quelli che non vuoi):')))
            for p in proposte:
                if p["chiave"] == "scarica":
                    testo = f"{p['ruolo']}: {p['nuovo']} — {p['motivo']}"
                else:
                    nuovo = risorse.NOMI.get(p["nuovo"], "Automatico") if p["chiave"] == "risorse" else p["nuovo"]
                    nuovo = {"cuda": "GPU NVIDIA", "cpu": "CPU"}.get(nuovo, nuovo)
                    testo = f"{p['ruolo']}: {p['attuale']} → {nuovo} — {p['motivo']}"
                riga = QHBoxLayout()
                cb = QCheckBox()
                cb.setChecked(True)
                etichetta = QLabel(testo)
                etichetta.setWordWrap(True)
                etichetta.mousePressEvent = lambda _e, c=cb: c.toggle()
                riga.addWidget(cb, 0, Qt.AlignTop)
                riga.addWidget(etichetta, 1)
                caselle.append((cb, p))
                lay.addLayout(riga)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(tr('Chiudi'))
        if proposte:
            bb.addButton(tr('Applica'), QDialogButtonBox.AcceptRole)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() != QDialog.Accepted:
            return
        scelte = [p for cb, p in caselle if cb.isChecked()]
        s = core.carica_impostazioni()
        for p in scelte:
            if p["chiave"] != "scarica":
                s[p["chiave"]] = p["nuovo"]
        core.salva_impostazioni(s)
        self.c_modello.setCurrentIndex(max(0, self.c_modello.findData(s.get("model"))))
        self.c_device.setCurrentIndex(max(0, self.c_device.findData(s.get("device"))))
        self.c_risorse.setCurrentIndex(max(0, self.c_risorse.findData(s.get("risorse", "auto"))))
        attrezzi.segnale_modelli.cambiato.emit()
        logging.getLogger("argo").info("adattato al computer (%s): %s", adatta_computer.descrivi(pc),
                                       "; ".join(f"{p['chiave']}={p['nuovo']}" for p in scelte) or "nessun cambio")
        self.statusBar().showMessage(tr('Configurazione adattata a questo computer: {len} cambi.', len=len(scelte)), 10000)
        da_scaricare = [p["nuovo"] for p in scelte if p["chiave"] == "scarica"]
        if da_scaricare:
            self._modelli_troppo_grandi = True
            self._proponi_modelli(da_scaricare, url, True)

    def salva_impostazioni(self):
        imp = core.carica_impostazioni()
        imp.update(model=self.c_modello.currentData(), language=self.c_lingua.currentData(),
                   device=self.c_device.currentData(), soglia=round(self.s_soglia.value(), 2),
                   hotwords=self.e_hot.text().strip(), risorse=self.c_risorse.currentData())
        core.salva_impostazioni(imp)
        if self.e_token.text().strip():
            core.salva_token(self.e_token.text().strip())
        self.statusBar().showMessage(tr('Impostazioni salvate.'), 5000)

    def closeEvent(self, e):
        if self.tab_incontri.occupata() and QMessageBox.question(
                self, tr('Uscire?'), tr('Sto scrivendo la relazione di un incontro: verrà interrotta. La coda resta salvata e la riprendi con «▶ Riprendi coda». Uscire comunque?')) != QMessageBox.Yes:
            e.ignore()
            return
        self.tab_incontri.ferma()
        if self.tab_registra.occupata():
            if QMessageBox.question(self, tr('Uscire?'), tr("C'è una registrazione in corso: verrà fermata. In modalità Live l'audio non ancora trascritto resta in una cartella privata e Argo ti chiederà cosa farne al prossimo avvio. Uscire comunque?")) != QMessageBox.Yes:
                e.ignore()
                return
            self.tab_registra.chiudi()
        if self.worker or self.worker_voce:
            if QMessageBox.question(self, tr('Uscire?'), tr("C'è un'elaborazione in corso: verrà interrotta. Uscire comunque?")) != QMessageBox.Yes:
                e.ignore()
                return
            for w in (self.worker, self.worker_voce):
                if w:
                    w.ferma()
                    w.wait(5000)
        if getattr(self, "_lav_modelli", None):  # download dei modelli: si ferma, Ollama riprende da dove era
            self._lav_modelli.ferma()
            self._lav_modelli.wait(5000)
        self._salva_coda()
        if not diagnostica.MODALITA_SICURA:  # backup alla chiusura e configurazione condivisa
            _senza_errori(lambda: backup_ui.alla_chiusura(self))
        _senza_errori(lambda: _ferma_ollama_attesa(self))  # Ollama spento secondo Impostazioni › Modelli AI
        diagnostica.avvio_riuscito()  # chiusa dall'utente: l'avvio era andato a buon fine
        e.accept()


_ollama_chiusura_fatta = False


def _ferma_ollama_attesa(finestra):
    """Ferma Ollama (se va fermato) mostrando un breve messaggio: di solito un secondo.
    La chiamano sia la chiusura della finestra (pulsante di chiusura, Alt+F4) sia l'uscita dall'app (Mac: ⌘Q,
    menu Argo › Esci, Esci dal Dock; spegnimento del computer): una volta sola."""
    global _ollama_chiusura_fatta
    import aggiornamenti
    import modelli_ollama
    if _ollama_chiusura_fatta or aggiornamenti.IN_RIAVVIO:
        return
    _ollama_chiusura_fatta = True
    s = core.carica_impostazioni()
    scelta = modelli_ollama.scelta_chiusura(s)
    if scelta == "mai" or (scelta == "se_avviato" and not modelli_ollama.avviato_da_argo()):
        return
    finestra.statusBar().showMessage(tr("Spengo Ollama…"))
    QApplication.processEvents()
    modelli_ollama.alla_chiusura()


def _senza_errori(funzione):
    try:
        funzione()
    except Exception:
        pass


def main():
    precedenti = diagnostica.inizia(VERSIONE)
    app = QApplication(sys.argv)
    app.setApplicationName("Argo AI")
    lingua.imposta(lingua.scegli(core.carica_impostazioni()))  # prima di ogni testo dell'interfaccia
    lingua.installa_qt(app)
    tema.applica(app, core.carica_impostazioni().get("tema", "scuro"))
    icona = Path(__file__).resolve().parent / "icon.png"
    if icona.exists():
        app.setWindowIcon(QIcon(str(icona)))
    supporto.collega()  # da qui un errore non gestito apre una finestra con «Chiedi supporto»
    _senza_errori(lambda: diagnostica.log.info("canale %s", aggiornamenti.canale_effettivo(
        core.carica_impostazioni(), criteri.carica())))
    # Avvio protetto: dopo due avvii di fila che non sono arrivati alla finestra (o con --sicura)
    if "--sicura" in sys.argv or precedenti >= diagnostica.AVVII_PRIMA_DELLA_SICURA:
        scelta = "sicura" if "--sicura" in sys.argv else supporto.chiedi_avvio_protetto(precedenti)
        diagnostica.log.warning("avvio protetto: %d avvii non riusciti, scelta «%s»", precedenti, scelta)
        if scelta == "esci":
            return
        if scelta == "precedente":
            if supporto.torna_alla_precedente(None, chiedi=False):
                return
            scelta = "sicura"
        diagnostica.MODALITA_SICURA = scelta == "sicura"
    app.aboutToQuit.connect(diagnostica.chiusura)
    condivisa_da = ""
    if not diagnostica.MODALITA_SICURA:  # configurazione condivisa con gli altri computer: prima della finestra
        try:
            condivisa_da = backup.leggi_condivisa()
            if condivisa_da:
                tema.applica(app, core.carica_impostazioni().get("tema", "scuro"))
        except Exception as e:
            diagnostica.log.warning("configurazione condivisa non letta: %s", e)
    f = Finestra()
    app.aboutToQuit.connect(lambda: _senza_errori(lambda: _ferma_ollama_attesa(f)))  # anche ⌘Q, Dock, spegnimento
    f.show()
    if condivisa_da:
        f.statusBar().showMessage(tr('Configurazione aggiornata da {condivisa_da} (cartella condivisa).', condivisa_da=condivisa_da), 15000)
    QTimer.singleShot(8000, diagnostica.avvio_riuscito)  # finestra rimasta aperta: avvio riuscito
    prova = os.environ.get("ARGO_PROVA_AVVIO", "")
    if prova.isdigit():  # prova automatica di avvio (GitHub Actions): Argo si chiude da solo dopo N secondi
        QTimer.singleShot(int(prova) * 1000, lambda: (diagnostica.avvio_riuscito(), app.quit()))
    if not diagnostica.MODALITA_SICURA:
        QTimer.singleShot(1500, f.prepara_ollama)  # Ollama acceso e modelli scelti (o proposti) già all'avvio
        f._timer_backup = QTimer(f)  # backup programmati: controllo a un minuto dall'avvio e poi ogni mezz'ora
        f._timer_backup.timeout.connect(lambda: _senza_errori(lambda: backup_ui.periodico(f)))
        f._timer_backup.start(30 * 60 * 1000)
        QTimer.singleShot(60 * 1000, lambda: _senza_errori(lambda: backup_ui.periodico(f)))
        if os.name == "nt":  # Argo tra le app installate di Windows, anche per chi si aggiorna dall'app
            threading.Thread(target=lambda: _senza_errori(disinstalla.registra_windows), daemon=True).start()
        if (core.carica_impostazioni().get("controlla_aggiornamenti", True)
                and criteri.carica().get("aggiornamenti_dall_app") is not False):
            QTimer.singleShot(3000, f.controlla_aggiornamenti)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
