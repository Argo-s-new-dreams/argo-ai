"""Argo · Cassetta degli attrezzi AI - trascrittore con anagrafe voci, verbale, documenti riservati, dettatura e traduzione.
Tutto gira in locale: l'audio non lascia il computer.
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voci_core as core  # noqa: E402
import argo_attrezzi as attrezzi  # noqa: E402
import llm_locale  # noqa: E402
import voci_strumenti  # noqa: E402
import aggiornamenti  # noqa: E402
import tema  # noqa: E402
import dettaglio  # noqa: E402
import m365  # noqa: E402

VERSIONE = "20261115.1415"
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
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW su Windows
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
        self.setWindowTitle("Revisione parlanti")
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
            "Controlla i nomi: puoi correggerli scrivendo o scegliendo dall'elenco. I nomi restano salvati.\n"
            "Due etichette sono la stessa persona? Dai loro lo stesso nome e verranno unite.\n"
            "Mancano persone o ce ne sono troppe? Chiudi e cambia «Partecipanti» nella coda: Argo rifà solo i parlanti.\n"
            "Spunta «Memorizza» per salvare l'impronta di quella voce nell'anagrafe: "
            "le prossime volte verrà riconosciuta da sola."))
        self.tab = QTableWidget(len(self.mappa), 5)
        self.tab.setHorizontalHeaderLabels(["Etichetta", "Parla per", "Somiglianza", "Nome", "Memorizza", ])
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
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(chk, alignment=Qt.AlignCenter)
            self.tab.setCellWidget(r, 4, box)
            self.righe.append((spk, combo, chk))
        lay.addWidget(self.tab)
        self.esempio = QLabel("Passa il mouse su un nome per leggere una frase di quel parlante.")
        self.esempio.setWordWrap(True)
        lay.addWidget(self.esempio)
        self.tab.cellClicked.connect(lambda r, c: self.esempio.setText(
            f"{self.righe[r][0]}: «{esempi.get(self.righe[r][0], '')[:300]}»"))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Applica e salva")
        bb.accepted.connect(self.applica)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def applica(self):
        nuova, memorizzate = {}, []
        for spk, combo, chk in self.righe:
            nome = combo.currentText().strip() or self.mappa[spk]
            nuova[spk] = nome
            if chk.isChecked():
                if nome.startswith(("Sconosciuto", "Parlante")) or not core.nome_valido(nome):
                    QMessageBox.warning(self, "Nome mancante", f"Dai un nome vero a {spk} prima di memorizzarlo.")
                    return
                core.salva_impronta(nome, self.emb[spk])
                memorizzate.append(nome)
        core.salva_nomi(self.file_json, nuova)
        self.dati[core.NOMI_KEY] = nuova
        self.out = core.scrivi_trascrizione(self.dati, nuova, self.file_json)
        msg = f"Trascrizione aggiornata:\n{self.out}"
        if memorizzate:
            msg += "\n\nVoci memorizzate: " + ", ".join(memorizzate)
        QMessageBox.information(self, "Fatto", msg)
        self.accept()


# =============================================================== finestra principale
class Finestra(QMainWindow):
    COL_FILE, COL_PARL, COL_STATO, COL_AVANZ = range(4)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Argo · Cassetta degli attrezzi AI - versione {VERSIONE}")
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
        import incarichi
        self.tab_incarichi = incarichi.SchedaIncarichi(self)
        self.tabs.addTab(self.tab_incarichi, "Incarichi")
        import agenda_posta
        self.tab_agenda = agenda_posta.SchedaAgenda(self)
        self.tab_posta = agenda_posta.SchedaPosta(self)
        self.tabs.addTab(self.tab_agenda, "Agenda")
        self.tabs.addTab(self.tab_posta, "Posta AI")
        self.pag_coda = self._tab_coda()
        self.tabs.addTab(self.pag_coda, "Trascrittore")
        self.tabs.addTab(self._pagina(self.tab_verbale, "Verbale", "Dalla trascrizione al verbale, in locale"), "Verbale")
        self.tabs.addTab(self._pagina(attrezzi.SchedaDocumenti(), "Documenti riservati",
                                      "Domande su contratti e capitolati, con le fonti"), "Documenti riservati")
        self.tabs.addTab(self._pagina(attrezzi.SchedaDettatura(), "Dettatura", "Parli, Argo scrive"), "Dettatura")
        self.tabs.addTab(self._pagina(attrezzi.SchedaTraduzione(), "Traduzione", "IT · EN · DE con glossario"), "Traduzione")
        self.pag_voci = self._pagina(self._tab_voci(), "Anagrafe voci", "Impronte vocali, solo con il consenso delle persone")
        self.tabs.addTab(self.pag_voci, "Anagrafe voci")
        self.tab_imp = QScrollArea()
        self.tab_imp.setWidgetResizable(True)
        self.tab_imp.setWidget(self._pagina(self._tab_impostazioni(), "Impostazioni", f"Argo versione {VERSIONE}"))
        self.tabs.addTab(self.tab_imp, "Impostazioni")
        self.tabs.tabBar().hide()
        self.nav = tema.NavLaterale([
            ("incarichi", "Incarichi", "Incarichi"), ("agenda", "Agenda", "Agenda"), ("posta", "Posta AI", "Posta"),
            ("trascrittore", "Trascrittore", "Trascrivi"),
            ("verbale", "Verbale", "Verbale"), ("documenti", "Documenti riservati", "Documenti"),
            ("dettatura", "Dettatura", "Dettatura"), ("traduzione", "Traduzione", "Traduci"),
            ("voci", "Anagrafe voci", "Voci"), ("impostazioni", "Impostazioni", "Impostaz.")])
        self.nav.scelto.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.nav.seleziona)
        centro = QWidget()
        cl = QHBoxLayout(centro)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.nav)
        cl.addWidget(self.tabs, 1)
        self.setCentralWidget(centro)
        self.tabs.setCurrentWidget(self.pag_coda)
        self.nav.seleziona(self.tabs.indexOf(self.pag_coda))
        self.badge = QLabel()
        self.statusBar().addPermanentWidget(self.badge)
        self._aggiorna_badge()
        self.statusBar().showMessage("Pronto. Tutto viene elaborato in locale.")

        self._carica_coda()
        self._aggiorna_voci()
        self._stato_m365()
        if not core.leggi_token():
            self.tabs.setCurrentWidget(self.tab_imp)
            QMessageBox.information(self, "Primo avvio",
                                    "Benvenuto! Inserisci il token Hugging Face nelle Impostazioni e premi «Verifica».")

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
        tit = QLabel("Trascrittore")
        tit.setProperty("ruolo", "titolo")
        sotto = QLabel("Trascina qui audio o video · nulla esce da questo computer")
        sotto.setProperty("ruolo", "tenue")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(tit)
        col.addWidget(sotto)
        testa.addLayout(col)
        testa.addStretch()
        lay.addLayout(testa)

        self.tab_coda = QTableWidget(0, 4)
        self.tab_coda.setHorizontalHeaderLabels(["File", "Partecipanti", "Stato", "Avanzamento"])
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
        self.tab_coda.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_coda.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_coda.customContextMenuRequested.connect(self._menu_coda)
        QShortcut(QKeySequence.Delete, self.tab_coda, activated=self.rimuovi_job)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.tab_coda, activated=self.rimuovi_job)
        self.tab_coda.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab_coda.doubleClicked.connect(lambda _: self.apri_risultato())

        bar = QHBoxLayout()
        self.b_agg = QPushButton("+ Aggiungi file…")
        self.b_rim = QPushButton("Rimuovi")
        self.b_rip = QPushButton("Rimetti in coda")
        self.b_avvia = QPushButton("▶ Avvia coda")
        self.b_avvia.setProperty("primario", True)
        self.b_ris = QPushButton("Apri trascrizione")
        self.b_rev = QPushButton("✏️ Nomi dei parlanti…")
        self.b_cart = QPushButton("Apri cartella")
        self.b_verb = QPushButton("Crea verbale →")
        self.b_word = QPushButton("Esporta in Word")
        self.b_marca_job = QPushButton("🎧 Marca voci…")
        for b in (self.b_agg, self.b_rim, self.b_rip):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.b_avvia)
        testa.addWidget(self.b_agg)
        testa.addWidget(self.b_avvia)
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
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tab_coda)
        split.addWidget(self.log)
        split.setSizes([420, 120])
        lay.addWidget(split, 1)
        lay.addWidget(self.fase)
        lay.addLayout(bar)
        self.b_cart.setParent(sinistra)
        bar.insertWidget(3, self.b_cart)

        self.dettaglio = dettaglio.DettaglioTrascrizione()
        self.dettaglio.nomi.connect(self.rivedi_parlanti)
        self.dettaglio.marca.connect(lambda: (lambda j: j and self.marca_voci(j["file"]))(self._job_selezionato()))
        self.dettaglio.word.connect(self.esporta_word)
        self.dettaglio.verbale.connect(self.crea_verbale)
        self.dettaglio.apri.connect(self.apri_risultato)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(sinistra)
        sp.addWidget(self.dettaglio)
        sp.setSizes([560, 620])
        esterno.addWidget(sp)
        return w

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
        files, _ = QFileDialog.getOpenFileNames(self, "Scegli i file audio", str(Path.home()), filtro)
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
            self.statusBar().showMessage(f"{aggiunti} file aggiunti alla coda.")

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
            spin.setToolTip("Numero di persone che parlano. Su una trascrizione completata, cambiarlo "
                            "rifà solo la separazione dei parlanti.")
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
                self, "Cambiare i partecipanti?",
                f"Rifaccio solo la separazione dei parlanti di «{Path(j['file']).name}» con partecipanti: {n}.\n\n"
                "Il testo trascritto resta lo stesso, ci vuole meno tempo di una trascrizione completa. "
                "I nomi corretti a mano finora andranno riassegnati.",
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
            m.addAction("Apri trascrizione", self.apri_trascrizione if hasattr(self, "apri_trascrizione") else self.b_ris.click)
            m.addAction("✏️ Nomi dei parlanti…", self.rivedi_parlanti)
            m.addAction("Esporta in Word", self.esporta_word)
            m.addAction("Crea verbale →", self.crea_verbale)
            m.addSeparator()
        m.addAction("🎧 Marca voci…", lambda: self.marca_voci(j["file"]))
        m.addAction("Rimetti in coda", self.rimetti_in_coda)
        m.addAction("Apri cartella", self.b_cart.click)
        m.addSeparator()
        m.addAction("Rimuovi dalla coda", self.rimuovi_job)
        m.exec(self.tab_coda.viewport().mapToGlobal(pos))

    def _in_lavorazione(self, j):
        return j is self.job_corrente and self.worker is not None and self.worker.isRunning()

    def rimuovi_job(self):
        sel = [j for j in self._selezionati() if not self._in_lavorazione(j)]
        if not sel and self._selezionati():
            QMessageBox.information(self, "In lavorazione", "Questo file è in elaborazione: ferma prima la coda.")
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
            box.setWindowTitle("Rimetti in coda")
            box.setText("Cosa vuoi rifare per le trascrizioni già completate?")
            b_parl = box.addButton("Solo i parlanti", QMessageBox.AcceptRole)
            b_tutto = box.addButton("Tutta la trascrizione", QMessageBox.DestructiveRole)
            box.addButton("Annulla", QMessageBox.RejectRole)
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
            self.b_avvia.setText("▶ Avvia coda")
            if self.worker:
                self.worker.ferma()
            self.statusBar().showMessage("Coda fermata.")
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Attendi", "Sto ancora fermando l'elaborazione precedente: riprova tra qualche secondo.")
            return
        if not core.leggi_token():
            QMessageBox.warning(self, "Token mancante", "Inserisci prima il token Hugging Face nelle Impostazioni.")
            self.tabs.setCurrentWidget(self.tab_imp)
            return
        if not any(j["stato"] == "In attesa" for j in self.jobs):
            QMessageBox.information(self, "Coda vuota", "Non ci sono file «In attesa». Aggiungi dei file o rimettili in coda.")
            return
        self.in_esecuzione = True
        self.b_avvia.setText("■ Ferma coda")
        self._prossimo()

    def _prossimo(self):
        if not self.in_esecuzione:
            return
        job = next((j for j in self.jobs if j["stato"] == "In attesa"), None)
        if job is None:
            self.in_esecuzione = False
            self.b_avvia.setText("▶ Avvia coda")
            self.fase.setText("")
            self.statusBar().showMessage("Coda completata.")
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
        for chiave, (nome, ini, fine) in FASI.items():
            if chiave in testo:
                job.update(nota=nome.lower(), progresso=ini)
                self._fase_corrente = (nome, ini, fine)
                self._aggiorna_riga(job)
        m = RE_PROGRESS.search(testo)
        if m and getattr(self, "_fase_corrente", None):
            nome, ini, fine = self._fase_corrente
            job["progresso"] = ini + (fine - ini) * float(m.group(1)) / 100
            self._aggiorna_riga(job)
        minuti = int((time.time() - self.t_inizio) // 60)
        self.fase.setText(f"{Path(job['file']).name}: {job.get('nota', '')} - {minuti} min trascorsi")

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
                    job.update(stato="Completata", progresso=100, json=str(fj), txt=str(out),
                               nota=f"{minuti} min - " + ", ".join(nomi))
                except Exception as e:
                    job.update(stato="Errore", nota=f"identificazione voci: {e}")
            else:
                job.update(stato="Errore", nota=self._spiega_errore(), progresso=0)
        self.log.appendPlainText(f"--- {job['stato']}: {job.get('nota', '')}")
        self._aggiorna_dettaglio()
        self._aggiorna_riga(job)
        self._salva_coda()
        self._prossimo()

    def _spiega_errore(self):
        log = "\n".join(getattr(self, "_log_job", []))
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
            QMessageBox.information(self, "Seleziona", "Seleziona prima una riga della coda.")
            return None
        return sel[0]

    def apri_risultato(self):
        j = self._job_selezionato()
        if j and j.get("txt") and Path(j["txt"]).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(j["txt"]))
        elif j:
            QMessageBox.information(self, "Non pronta", "La trascrizione non è ancora disponibile.")

    def rivedi_parlanti(self):
        j = self._job_selezionato()
        if not j:
            return
        if not (j.get("json") and Path(j["json"]).exists()):
            QMessageBox.information(self, "Non pronta", "Prima completa la trascrizione.")
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
            QMessageBox.information(self, "Non pronta", "Prima completa la trascrizione.")
            return
        self.tab_verbale.carica(j["txt"])
        self.vai_a(self.tab_verbale)

    def esporta_word(self):
        j = self._job_selezionato()
        if not j:
            return
        if not (j.get("txt") and Path(j["txt"]).exists()):
            QMessageBox.information(self, "Non pronta", "Prima completa la trascrizione.")
            return
        txt = Path(j["txt"])
        nome = txt.stem.replace("_nomi", "")
        attrezzi.salva_word(self, txt.read_text(encoding="utf-8", errors="replace"),
                            txt.with_name(nome + "_trascrizione.docx"), f"Trascrizione: {nome}",
                            attrezzi.oggi(), nota_ai=attrezzi.word.NOTA_TRASCRIZIONE)

    def _aggiorna_badge(self):
        url = core.carica_impostazioni().get("ollama_url", "")
        if llm_locale.e_locale(url) and m365.account():
            self.badge.setText("🔒 Locale · Microsoft 365 collegato: solo i risultati che confermi vanno su M365")
            self.badge.setStyleSheet(f"color: {tema.colori()['ok']}; font-weight: 600; padding-right: 8px;")
        elif llm_locale.e_locale(url):
            self.badge.setText("🔒 100% locale: audio e testi non lasciano questo computer")
            self.badge.setStyleSheet(f"color: {tema.colori()['ok']}; font-weight: 600; padding-right: 8px;")
        else:
            self.badge.setText("⚠️ Il modello linguistico punta a un server esterno")
            self.badge.setStyleSheet(f"color: {tema.colori()['warn']}; font-weight: 600; padding-right: 8px;")

    def apri_cartella(self):
        j = self._job_selezionato()
        if j:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(j["file"]).parent)))

    # ------------------------------------------------------------ tab anagrafe voci
    def _tab_voci(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(
            "Ogni persona ha un'impronta vocale ricavata da 20-60 secondi in cui parla solo lei. Tre modi per crearla:\n"
            "🎙 Registra voce: la persona parla al microfono adesso.\n"
            "🎧 Marca voci in un audio: ascolti una registrazione e segni dove parla ciascuno.\n"
            "➕ Nuova voce da audio: scegli un file in cui parla solo quella persona.\n"
            "Più campioni della stessa persona migliorano il riconoscimento. Registra le voci solo con il consenso delle persone.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.tab_voci = QTableWidget(0, 2)
        self.tab_voci.setHorizontalHeaderLabels(["Nome", "Campioni"])
        self.tab_voci.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tab_voci.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_voci.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tab_voci)
        bar = QHBoxLayout()
        self.b_reg_voce = QPushButton("🎙 Registra voce…")
        self.b_marca = QPushButton("🎧 Marca voci in un audio…")
        self.b_nuova = QPushButton("➕ Nuova voce da audio…")
        self.b_camp = QPushButton("Aggiungi campione…")
        b_ren = QPushButton("Rinomina…")
        b_del = QPushButton("Elimina")
        for b in (self.b_reg_voce, self.b_marca, self.b_nuova, self.b_camp, b_ren, b_del):
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.stato_voci = QLabel("")
        lay.addWidget(self.stato_voci)
        self.b_reg_voce.clicked.connect(self.registra_voce)
        self.b_marca.clicked.connect(lambda: self.marca_voci(None))
        self.b_nuova.clicked.connect(lambda: self.iscrivi_voce(None))
        self.b_camp.clicked.connect(lambda: self.iscrivi_voce(self._voce_selezionata()))
        b_ren.clicked.connect(self.rinomina_voce)
        b_del.clicked.connect(self.elimina_voce)
        return w

    def _aggiorna_voci(self):
        voci = core.elenco_voci()
        self.tab_voci.setRowCount(len(voci))
        for r, (n, c) in enumerate(voci):
            self.tab_voci.setItem(r, 0, QTableWidgetItem(n))
            self.tab_voci.setItem(r, 1, QTableWidgetItem(str(c)))

    def _voce_selezionata(self):
        r = self.tab_voci.currentRow()
        it = self.tab_voci.item(r, 0) if r >= 0 else None
        return it.text() if it else None

    def iscrivi_voce(self, nome):
        if self.worker_voce:
            QMessageBox.information(self, "Attendi", "Sto già elaborando una voce.")
            return
        if not core.leggi_token():
            QMessageBox.warning(self, "Token mancante", "Inserisci prima il token nelle Impostazioni.")
            return
        if nome is None:
            nome, ok = QInputDialog.getText(self, "Nuova voce", "Nome della persona:")
            if not ok:
                return
            nome = nome.strip()
        if not core.nome_valido(nome or ""):
            QMessageBox.warning(self, "Nome non valido", "Scegli un nome senza caratteri speciali.")
            return
        filtro = "Audio o video (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ")"
        f, _ = QFileDialog.getOpenFileName(self, f"Audio con la sola voce di {nome}", str(Path.home()), filtro)
        if not f:
            return
        self._avvia_iscrizioni([(nome, f)])

    def _pronto_per_voci(self):
        if self.worker_voce:
            QMessageBox.information(self, "Attendi", "Sto già elaborando una voce.")
            return False
        if not core.leggi_token():
            QMessageBox.warning(self, "Token mancante", "Inserisci prima il token nelle Impostazioni.")
            return False
        return True

    def registra_voce(self):
        if not self._pronto_per_voci():
            return
        dlg = voci_strumenti.RegistraVoceDialog([n for n, _ in core.elenco_voci()], self._voce_selezionata(), self)
        if dlg.exec() and dlg.risultato:
            self._avvia_iscrizioni(dlg.risultato)

    def marca_voci(self, file_audio=None):
        if not self._pronto_per_voci():
            return
        dlg = voci_strumenti.MarcaVociDialog([n for n, _ in core.elenco_voci()], file_audio, self)
        if dlg.exec() and dlg.risultato:
            self.tabs.setCurrentWidget(self.pag_voci)
            self._avvia_iscrizioni(dlg.risultato)

    def _avvia_iscrizioni(self, coppie):
        """Calcola le impronte una dopo l'altra: coppie = [(nome, file_audio)]."""
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
        self.stato_voci.setText(f"Calcolo dell'impronta di {nome} in corso (1-2 minuti){resto}…")
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
        self._aggiorna_voci()
        if codice == 0:
            self._fatte_voci.append(nome)
        else:
            err = next((r for r in reversed(self._righe_voce) if r.startswith("ERRORE")), "vedi registro nella scheda Trascrittore")
            self._errori_voci.append(f"{nome}: {err}")
        self._prossima_iscrizione()

    def rinomina_voce(self):
        n = self._voce_selezionata()
        if not n:
            return
        nuovo, ok = QInputDialog.getText(self, "Rinomina", "Nuovo nome:", text=n)
        if ok and nuovo.strip() and nuovo.strip() != n:
            try:
                core.rinomina_voce(n, nuovo.strip())
            except Exception as e:
                QMessageBox.warning(self, "Errore", str(e))
            self._aggiorna_voci()

    def elimina_voce(self):
        n = self._voce_selezionata()
        if n and QMessageBox.question(self, "Elimina", f"Eliminare la voce di {n} e tutti i suoi campioni?") == QMessageBox.Yes:
            core.elimina_voce(n)
            self._aggiorna_voci()

    # ------------------------------------------------------------ tab impostazioni
    def _tab_impostazioni(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        imp = core.carica_impostazioni()

        g1 = QGroupBox("Hugging Face (serve solo per scaricare i modelli)")
        f1 = QFormLayout(g1)
        self.e_token = QLineEdit(core.leggi_token())
        self.e_token.setEchoMode(QLineEdit.Password)
        self.e_token.setPlaceholderText("hf_...")
        riga = QHBoxLayout()
        riga.addWidget(self.e_token)
        b_mostra = QPushButton("Mostra")
        b_mostra.setCheckable(True)
        b_mostra.toggled.connect(lambda on: self.e_token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        b_ver = QPushButton("Salva e verifica")
        b_ver.clicked.connect(self.verifica_token)
        riga.addWidget(b_mostra)
        riga.addWidget(b_ver)
        f1.addRow("Token (Read):", riga)
        self.l_token = QLabel("")
        self.l_token.setWordWrap(True)
        f1.addRow("", self.l_token)
        link = QLabel('1) <a href="https://huggingface.co/pyannote/speaker-diarization-community-1">Accetta le condizioni del modello</a>'
                      ' &nbsp; 2) <a href="https://huggingface.co/settings/tokens">Crea un token di tipo Read</a>')
        link.setOpenExternalLinks(True)
        f1.addRow("", link)
        lay.addWidget(g1)

        g2 = QGroupBox("Trascrizione")
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
        self.c_device.addItem("CPU (sempre disponibile)", "cpu")
        self.c_device.addItem("GPU NVIDIA (CUDA)", "cuda")
        self.c_device.setCurrentIndex(1 if imp["device"] == "cuda" else 0)
        self.e_hot = QLineEdit(imp.get("hotwords", ""))
        self.e_hot.setPlaceholderText("es. Copilot, Azure, EOS Solutions, nomi dei partecipanti")
        f2.addRow("Modello:", self.c_modello)
        f2.addRow("Lingua:", self.c_lingua)
        f2.addRow("Calcolo su:", self.c_device)
        f2.addRow("Parole chiave:", self.e_hot)
        lay.addWidget(g2)

        g3 = QGroupBox("Riconoscimento voci")
        f3 = QFormLayout(g3)
        self.s_soglia = QDoubleSpinBox()
        self.s_soglia.setRange(0.2, 0.95)
        self.s_soglia.setSingleStep(0.05)
        self.s_soglia.setValue(float(imp["soglia"]))
        f3.addRow("Somiglianza minima:", self.s_soglia)
        nota = QLabel("Più alta = meno errori ma più «Sconosciuto». 0,50 è un buon punto di partenza.")
        nota.setWordWrap(True)
        f3.addRow("", nota)
        lay.addWidget(g3)

        self.pannello_ollama = attrezzi.PannelloOllama()
        self.pannello_ollama.cambiato.connect(lambda: self._aggiorna_badge() if hasattr(self, "badge") else None)
        lay.addWidget(self.pannello_ollama)

        g6 = QGroupBox("Microsoft 365 (facoltativo) · per gli Incarichi")
        f6 = QFormLayout(g6)
        self.e_m365_client = QLineEdit(imp.get("m365_client_id", ""))
        self.e_m365_client.setPlaceholderText("Application (client) ID dell'app registrata in Entra ID")
        self.e_m365_tenant = QLineEdit(imp.get("m365_tenant_id", ""))
        self.e_m365_tenant.setPlaceholderText("Directory (tenant) ID")
        f6.addRow("Client ID:", self.e_m365_client)
        f6.addRow("Tenant ID:", self.e_m365_tenant)
        r6 = QHBoxLayout()
        self.b_m365 = QPushButton("Collega")
        self.b_m365.clicked.connect(self.collega_m365)
        self.b_m365_off = QPushButton("Scollega")
        self.b_m365_off.clicked.connect(self.scollega_m365)
        self.l_m365 = QLabel("")
        self.l_m365.setWordWrap(True)
        r6.addWidget(self.b_m365)
        r6.addWidget(self.b_m365_off)
        r6.addWidget(self.l_m365, 1)
        f6.addRow("", r6)
        self.cb_posta = QCheckBox("Leggi la posta per «Posta AI» (le mail vengono elaborate solo su questo computer)")
        self.cb_posta.setChecked(bool(imp.get("m365_leggi_posta")))
        self.cb_posta.toggled.connect(self._pref_posta)
        f6.addRow("", self.cb_posta)
        n6 = QLabel("Su Microsoft 365 vanno solo i risultati che confermi (bozze di Outlook, task in Planner). Argo legge "
                    "il calendario per Agenda e Incarichi e, solo se lo attivi, la posta per Posta AI: i testi vengono "
                    "elaborati dal modello locale. Audio, trascrizioni e documenti restano qui.")
        n6.setWordWrap(True)
        n6.setProperty("ruolo", "tenue")
        f6.addRow("", n6)
        lay.addWidget(g6)

        g5 = QGroupBox("Aspetto")
        f5 = QHBoxLayout(g5)
        f5.addWidget(QLabel("Tema:"))
        self.c_tema = QComboBox()
        for etichetta, val in (("Scuro", "scuro"), ("Chiaro", "chiaro"), ("Come il sistema", "sistema")):
            self.c_tema.addItem(etichetta, val)
        self.c_tema.setCurrentIndex(max(0, self.c_tema.findData(imp.get("tema", "scuro"))))
        self.c_tema.currentIndexChanged.connect(lambda _: self.cambia_tema(self.c_tema.currentData()))
        f5.addWidget(self.c_tema)
        f5.addStretch()
        lay.addWidget(g5)

        g4 = QGroupBox(f"Aggiornamenti · versione installata {VERSIONE}")
        f4 = QVBoxLayout(g4)
        self.cb_agg = QCheckBox("Controlla all'avvio se su GitHub c'è una versione nuova")
        self.cb_agg.setChecked(bool(imp.get("controlla_aggiornamenti", True)))
        self.cb_agg.toggled.connect(self._salva_pref_agg)
        f4.addWidget(self.cb_agg)
        nota_agg = QLabel("Argo legge da GitHub solo il numero dell'ultima versione e le novità: nessun dato, "
                          "audio o documento viene inviato. Voci, impostazioni e glossario restano dove sono.")
        nota_agg.setWordWrap(True)
        f4.addWidget(nota_agg)
        r4 = QHBoxLayout()
        self.b_agg = QPushButton("Controlla ora")
        self.b_agg.clicked.connect(lambda: self.controlla_aggiornamenti(manuale=True))
        b_gh = QPushButton("Apri GitHub")
        b_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(aggiornamenti.URL_GITHUB)))
        self.l_agg = QLabel("")
        r4.addWidget(self.b_agg)
        r4.addWidget(b_gh)
        r4.addWidget(self.l_agg, 1)
        f4.addLayout(r4)
        lay.addWidget(g4)

        riga2 = QHBoxLayout()
        b_salva = QPushButton("Salva impostazioni")
        b_salva.clicked.connect(self.salva_impostazioni)
        b_dati = QPushButton("Apri cartella dati")
        b_dati.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.APP_HOME))))
        riga2.addWidget(b_salva)
        riga2.addWidget(b_dati)
        riga2.addStretch()
        lay.addLayout(riga2)
        lay.addStretch()
        lay.addWidget(QLabel(f"Dati in: {core.APP_HOME}  ·  L'audio non lascia mai questo computer."))
        return w

    def _stato_m365(self):
        acc = m365.account()
        if hasattr(self, "l_m365"):
            self.l_m365.setText(f"✅ Collegato come {acc}" if acc else "Non collegato")
            self.b_m365_off.setEnabled(bool(acc))
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
            QMessageBox.warning(self, "Microsoft 365", "Inserisci Client ID e Tenant ID.")
            return
        self.l_m365.setText("Si è aperto il browser: accedi con il tuo account Microsoft e accetta i permessi "
                            "(hai 5 minuti)…")
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
            QMessageBox.warning(self, "Microsoft 365", e)

        lav.sig_fine.connect(fine)
        lav.sig_errore.connect(errore)
        self._lav_m365 = lav
        lav.start()

    def scollega_m365(self):
        m365.scollega()
        self._stato_m365()

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

    def controlla_aggiornamenti(self, manuale=False):
        if getattr(self, "_lav_agg", None):
            return
        if hasattr(self, "l_agg"):
            self.l_agg.setText("Controllo su GitHub…")
        lav = attrezzi.Lavoro(lambda _l: aggiornamenti.controlla(VERSIONE), self)
        lav.sig_fine.connect(lambda r: self._esito_controllo(r, manuale))
        lav.sig_errore.connect(lambda e: self._errore_controllo(e, manuale))
        self._lav_agg = lav
        lav.start()

    def _errore_controllo(self, e, manuale):
        self._lav_agg = None
        if hasattr(self, "l_agg"):
            self.l_agg.setText("Controllo non riuscito (sei offline?)")
        if manuale:
            QMessageBox.warning(self, "Aggiornamenti", f"Non riesco a contattare GitHub:\n{e}")

    def _esito_controllo(self, r, manuale):
        self._lav_agg = None
        nuova, remota, testo = r
        if not nuova:
            if hasattr(self, "l_agg"):
                self.l_agg.setText(f"✅ Hai l'ultima versione ({VERSIONE}).")
            if manuale:
                QMessageBox.information(self, "Aggiornamenti", f"Hai già l'ultima versione ({VERSIONE}).")
            return
        if hasattr(self, "l_agg"):
            self.l_agg.setText(f"🆕 Disponibile la versione {remota}.")
        self._proponi_aggiornamento(remota, testo)

    def _proponi_aggiornamento(self, remota, testo):
        dlg = QDialog(self)
        dlg.setWindowTitle("Nuova versione di Argo")
        dlg.resize(620, 480)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"<b>È disponibile la versione {remota}</b> (hai la {VERSIONE}).<br>"
                             "L'aggiornamento sostituisce solo i file del programma: voci, token, impostazioni, "
                             "glossario e documenti indicizzati restano come sono."))
        box = QPlainTextEdit(testo or "Novità: vedi CHANGELOG su GitHub.")
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        bar = QHBoxLayout()
        b_ora = QPushButton("Aggiorna ora")
        b_ora.setProperty("primario", True)
        b_dopo = QPushButton("Più tardi")
        b_gh = QPushButton("Apri GitHub")
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
            QMessageBox.information(self, "Aggiornamento", "Aspetta che finisca l'elaborazione in corso, poi riprova.")
            return
        cartella = Path(__file__).resolve().parent
        lav = attrezzi.Lavoro(lambda l: aggiornamenti.installa(cartella, l.stato), self)
        lav.sig_stato.connect(lambda t: self.statusBar().showMessage(t))
        lav.sig_fine.connect(self._fine_aggiornamento)
        lav.sig_errore.connect(lambda e: (QMessageBox.warning(
            self, "Aggiornamento non riuscito",
            f"{e}\n\nLa versione attuale non è stata toccata. Puoi scaricare il pacchetto da GitHub e rilanciare l'installer."),
            setattr(self, "_lav_inst", None)))
        self._lav_inst = lav
        self.statusBar().showMessage("Aggiornamento in corso…")
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
            self, "Aggiornamento installato",
            f"Argo {esito['versione']} è installato.{extra}\n\nRiavvio Argo adesso per usarlo?\n"
            f"(La versione precedente è salvata in {esito['backup']}.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        self.statusBar().showMessage(f"Aggiornato alla versione {esito['versione']}.")
        if r == QMessageBox.Yes:
            self._salva_coda()
            aggiornamenti.riavvia()
            QApplication.quit()

    def verifica_token(self):
        tok = self.e_token.text().strip()
        if not tok.startswith("hf_"):
            self.l_token.setText("❌ Il token deve iniziare con hf_")
            return
        core.salva_token(tok)
        self.l_token.setText("Verifica in corso…")
        QApplication.processEvents()
        ok, msg = core.verifica_token(tok)
        self.l_token.setText(("✅ " if ok else "❌ ") + msg)

    def salva_impostazioni(self):
        imp = core.carica_impostazioni()
        imp.update(model=self.c_modello.currentData(), language=self.c_lingua.currentData(),
                   device=self.c_device.currentData(), soglia=round(self.s_soglia.value(), 2),
                   hotwords=self.e_hot.text().strip())
        core.salva_impostazioni(imp)
        if self.e_token.text().strip():
            core.salva_token(self.e_token.text().strip())
        self.statusBar().showMessage("Impostazioni salvate.", 5000)

    def closeEvent(self, e):
        if self.worker or self.worker_voce:
            if QMessageBox.question(self, "Uscire?", "C'è un'elaborazione in corso: verrà interrotta. Uscire comunque?") != QMessageBox.Yes:
                e.ignore()
                return
            for w in (self.worker, self.worker_voce):
                if w:
                    w.ferma()
                    w.wait(5000)
        self._salva_coda()
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Argo AI")
    tema.applica(app, core.carica_impostazioni().get("tema", "scuro"))
    icona = Path(__file__).resolve().parent / "icon.png"
    if icona.exists():
        app.setWindowIcon(QIcon(str(icona)))
    f = Finestra()
    f.show()
    if core.carica_impostazioni().get("controlla_aggiornamenti", True):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, f.controlla_aggiornamenti)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
