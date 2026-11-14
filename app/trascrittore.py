"""Trascrittore - interfaccia grafica per WhisperX con anagrafe voci e coda di trascrizioni.
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
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voci_core as core  # noqa: E402

VERSIONE = "20261114.1010"
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4", ".mov", ".mkv", ".webm"}
MODELLI = [
    ("large-v3", "large-v3 - massima qualità (lento)"),
    ("large-v3-turbo", "large-v3-turbo - ottimo compromesso (consigliato)"),
    ("medium", "medium - più veloce"),
    ("small", "small - prove rapide"),
]
LINGUE = [("it", "Italiano"), ("en", "Inglese"), ("de", "Tedesco"), ("fr", "Francese"), ("es", "Spagnolo"), ("", "Rilevamento automatico")]
FASI = {  # testo nel log -> (nome fase, inizio %, fine %)
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
            )
        except Exception as e:
            self.riga.emit(f"ERRORE avvio processo: {e}")
            self.finito.emit(-1)
            return
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
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


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
            "Controlla i nomi. Puoi correggerli scrivendo o scegliendo dall'elenco.\n"
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
        self.setWindowTitle(f"Trascrittore - versione {VERSIONE}")
        self.resize(1050, 680)
        self.setAcceptDrops(True)
        self.jobs = []
        self.worker = None          # trascrizione in corso
        self.job_corrente = None
        self.worker_voce = None     # iscrizione voce in corso
        self.in_esecuzione = False
        self.t_inizio = 0

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_coda(), "Coda trascrizioni")
        self.tabs.addTab(self._tab_voci(), "Anagrafe voci")
        self.tabs.addTab(self._tab_impostazioni(), "Impostazioni")
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("Pronto. Tutto viene elaborato in locale.")

        self._carica_coda()
        self._aggiorna_voci()
        if not core.leggi_token():
            self.tabs.setCurrentIndex(2)
            QMessageBox.information(self, "Primo avvio",
                                    "Benvenuto! Inserisci il token Hugging Face nelle Impostazioni e premi «Verifica».")

    # ------------------------------------------------------------ tab coda
    def _tab_coda(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel("Trascina qui i file audio, oppure usa «Aggiungi file». "
                      "Imposta il numero di partecipanti (0 = automatico) e avvia la coda.")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.tab_coda = QTableWidget(0, 4)
        self.tab_coda.setHorizontalHeaderLabels(["File", "Partecipanti", "Stato", "Avanzamento"])
        h = self.tab_coda.horizontalHeader()
        h.setSectionResizeMode(self.COL_FILE, QHeaderView.Interactive)
        h.setSectionResizeMode(self.COL_STATO, QHeaderView.Stretch)
        self.tab_coda.setColumnWidth(self.COL_FILE, 320)
        self.tab_coda.setColumnWidth(self.COL_PARL, 95)
        self.tab_coda.setColumnWidth(self.COL_AVANZ, 180)
        self.tab_coda.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_coda.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab_coda.doubleClicked.connect(lambda _: self.apri_risultato())

        bar = QHBoxLayout()
        self.b_agg = QPushButton("➕ Aggiungi file…")
        self.b_rim = QPushButton("Rimuovi")
        self.b_rip = QPushButton("Rimetti in coda")
        self.b_avvia = QPushButton("▶ Avvia coda")
        self.b_avvia.setStyleSheet("font-weight: bold;")
        self.b_ris = QPushButton("Apri trascrizione")
        self.b_rev = QPushButton("Rivedi parlanti…")
        self.b_cart = QPushButton("Apri cartella")
        for b in (self.b_agg, self.b_rim, self.b_rip):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.b_ris, self.b_rev, self.b_cart, self.b_avvia):
            bar.addWidget(b)
        self.b_agg.clicked.connect(self.scegli_file)
        self.b_rim.clicked.connect(self.rimuovi_job)
        self.b_rip.clicked.connect(self.rimetti_in_coda)
        self.b_avvia.clicked.connect(self.avvia_o_ferma)
        self.b_ris.clicked.connect(self.apri_risultato)
        self.b_rev.clicked.connect(self.rivedi_parlanti)
        self.b_cart.clicked.connect(self.apri_cartella)

        self.fase = QLabel("")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setFont(QFont("Consolas" if os.name == "nt" else "Menlo", 9))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tab_coda)
        split.addWidget(self.log)
        split.setSizes([400, 160])
        lay.addLayout(bar)
        lay.addWidget(split)
        lay.addWidget(self.fase)
        return w

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
            spin.setEnabled(j["stato"] in ("In attesa", "Errore", "Interrotta"))
            spin.valueChanged.connect(lambda v, jid=j["id"]: self._set_parlanti(jid, v))
            t.setCellWidget(r, self.COL_PARL, spin)
            stato = j["stato"] + (f" - {j['nota']}" if j.get("nota") else "")
            t.setItem(r, self.COL_STATO, QTableWidgetItem(stato))
            pb = QProgressBar()
            pb.setValue(int(j.get("progresso", 0)))
            t.setCellWidget(r, self.COL_AVANZ, pb)

    def _set_parlanti(self, jid, v):
        for j in self.jobs:
            if j["id"] == jid:
                j["parlanti"] = v
        self._salva_coda()

    def _riga_di(self, job):
        return self.jobs.index(job) if job in self.jobs else -1

    def _aggiorna_riga(self, job):
        r = self._riga_di(job)
        if r < 0:
            return
        stato = job["stato"] + (f" - {job['nota']}" if job.get("nota") else "")
        self.tab_coda.setItem(r, self.COL_STATO, QTableWidgetItem(stato))
        pb = self.tab_coda.cellWidget(r, self.COL_AVANZ)
        if pb:
            pb.setValue(int(job.get("progresso", 0)))
        spin = self.tab_coda.cellWidget(r, self.COL_PARL)
        if spin:
            spin.setEnabled(job["stato"] in ("In attesa", "Errore", "Interrotta"))

    def _selezionati(self):
        righe = sorted({i.row() for i in self.tab_coda.selectedIndexes()})
        return [self.jobs[r] for r in righe if r < len(self.jobs)]

    def rimuovi_job(self):
        sel = [j for j in self._selezionati() if j is not self.job_corrente]
        for j in sel:
            self.jobs.remove(j)
        self._ridisegna_coda()
        self._salva_coda()

    def rimetti_in_coda(self):
        for j in self._selezionati():
            if j is not self.job_corrente:
                j.update(stato="In attesa", progresso=0, nota="")
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
        if not core.leggi_token():
            QMessageBox.warning(self, "Token mancante", "Inserisci prima il token Hugging Face nelle Impostazioni.")
            self.tabs.setCurrentIndex(2)
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
        cmd = core.comando_whisperx(job["file"], job["parlanti"], imp, core.leggi_token())
        self.log.appendPlainText(f"\n=== {Path(job['file']).name} | modello {imp['model']} | "
                                 f"partecipanti {job['parlanti'] or 'auto'} ===")
        self.t_inizio = time.time()
        self._log_job = []
        self.filtro = FiltroRumore()
        self.worker = ProcessWorker(cmd, self)
        self.worker.riga.connect(self._riga_whisperx)
        self.worker.finito.connect(self._fine_whisperx)
        self.worker.start()

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

    def _fine_whisperx(self, codice):
        job, self.job_corrente = self.job_corrente, None
        self._fase_corrente = None
        interrotto = self.worker.interrotto if self.worker else False
        self.worker = None
        minuti = max(1, round((time.time() - self.t_inizio) / 60))
        if interrotto:
            job.update(stato="Interrotta", nota="fermata dall'utente", progresso=0)
        else:
            fj = core.json_atteso(job["file"])
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

    def apri_cartella(self):
        j = self._job_selezionato()
        if j:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(j["file"]).parent)))

    # ------------------------------------------------------------ tab anagrafe voci
    def _tab_voci(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(
            "Registra ogni persona con 20-60 secondi di audio in cui parla solo lei, con il microfono che usi di solito. "
            "Più campioni della stessa persona migliorano il riconoscimento.\n"
            "In alternativa: dopo una trascrizione usa «Rivedi parlanti» e spunta «Memorizza».")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.tab_voci = QTableWidget(0, 2)
        self.tab_voci.setHorizontalHeaderLabels(["Nome", "Campioni"])
        self.tab_voci.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tab_voci.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab_voci.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tab_voci)
        bar = QHBoxLayout()
        self.b_nuova = QPushButton("➕ Nuova voce da audio…")
        self.b_camp = QPushButton("Aggiungi campione…")
        b_ren = QPushButton("Rinomina…")
        b_del = QPushButton("Elimina")
        for b in (self.b_nuova, self.b_camp, b_ren, b_del):
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.stato_voci = QLabel("")
        lay.addWidget(self.stato_voci)
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
        filtro = "Audio (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ")"
        f, _ = QFileDialog.getOpenFileName(self, f"Audio con la sola voce di {nome}", str(Path.home()), filtro)
        if not f:
            return
        device = core.carica_impostazioni().get("device", "cpu")
        cmd = [sys.executable, str(Path(core.__file__).resolve()), "iscrivi", nome, f, device]
        self.stato_voci.setText(f"Calcolo dell'impronta di {nome} in corso (1-2 minuti)…")
        self.b_nuova.setEnabled(False)
        self.b_camp.setEnabled(False)
        self._righe_voce = []
        filtro_voce = FiltroRumore()
        self.worker_voce = ProcessWorker(cmd, self)
        self.worker_voce.riga.connect(lambda t: None if filtro_voce.e_rumore(t) else
                                      (self._righe_voce.append(t), self.log.appendPlainText("[voce] " + t)))
        self.worker_voce.finito.connect(lambda c, n=nome: self._fine_iscrizione(c, n))
        self.worker_voce.start()

    def _fine_iscrizione(self, codice, nome):
        self.worker_voce = None
        self.b_nuova.setEnabled(True)
        self.b_camp.setEnabled(True)
        self._aggiorna_voci()
        if codice == 0:
            self.stato_voci.setText(f"Impronta di {nome} salvata.")
        else:
            err = next((r for r in reversed(self._righe_voce) if r.startswith("ERRORE")), "vedi registro nella scheda Coda")
            self.stato_voci.setText(f"Errore per {nome}: {err}")

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
    app.setApplicationName("Trascrittore")
    icona = Path(__file__).resolve().parent / "icon.png"
    if icona.exists():
        app.setWindowIcon(QIcon(str(icona)))
    f = Finestra()
    f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
