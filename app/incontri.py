"""incontri.py - pagina Incontri: ciò che arriva da Argo per iPhone (fiere, visite ai clienti).

Ponte (abbinamento con QR, ricezione dei pacchetti), elenco degli incontri, relazione con Ollama
(trascrizione + foto, anche con un modello vision). Prossima tappa: Dynamics 365 Sales.
"""
import io
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

import esporta_word
import llm_locale as llm
import ponte as pt
import relazione_incontro as rel
import tema
import voci_core as core

SOLO_OCR = "Solo testo letto dall'iPhone"


def _durata(secondi):
    s = int(secondi or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


class LavoroRelazione(QThread):
    """Scrive la relazione di un incontro fuori dall'interfaccia, con stato e avanzamento."""
    sig_stato = Signal(str)
    sig_avanzamento = Signal(int)
    sig_fine = Signal()
    sig_errore = Signal(str)

    def __init__(self, cartella, sessione, url, modello_testo, modello_vision, parent=None):
        super().__init__(parent)
        self.argomenti = (cartella, sessione, url, modello_testo, modello_vision)
        self._stop = False

    def ferma(self):
        self._stop = True

    def run(self):
        cartella, sessione, url, testo, vision = self.argomenti
        try:
            rel.scrivi_relazione(cartella, sessione, url, testo, vision, stato=self.sig_stato.emit,
                                 stop=lambda: self._stop, avanzamento=self.sig_avanzamento.emit)
            self.sig_fine.emit()
        except Exception as e:
            self.sig_errore.emit("Interrotta" if self._stop else str(e))


class _Avvisi(QObject):
    """Porta le notifiche del server (thread del Ponte) nel thread dell'interfaccia."""
    arrivato = Signal(str, str)


class DialogoAbbina(QDialog):
    """Mostra il QR da inquadrare con Argo per iPhone (Impostazioni › Argo sul computer › Collega)."""

    def __init__(self, ponte, parent=None):
        super().__init__(parent)
        self.ponte = ponte
        self.setWindowTitle("Collega un iPhone")
        lay = QVBoxLayout(self)
        testo = QLabel("Su iPhone apri <b>Argo › Impostazioni › Argo sul computer › Collega</b> e inquadra il codice.<br>"
                       "Il codice vale 5 minuti e una sola volta. iPhone e computer devono essere sulla stessa rete.")
        testo.setWordWrap(True)
        lay.addWidget(testo)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setMinimumSize(320, 320)
        lay.addWidget(self.qr)
        self.stato = QLabel("")
        self.stato.setProperty("ruolo", "tenue")
        self.stato.setWordWrap(True)
        lay.addWidget(self.stato)
        riga = QHBoxLayout()
        b_nuovo = QPushButton("Nuovo codice")
        b_nuovo.clicked.connect(self._mostra)
        b_chiudi = QPushButton("Chiudi")
        b_chiudi.clicked.connect(self.accept)
        riga.addWidget(b_nuovo)
        riga.addStretch()
        riga.addWidget(b_chiudi)
        lay.addLayout(riga)
        self._mostra()

    def _mostra(self):
        try:
            import segno
        except ImportError:
            self.stato.setText("Manca la libreria «segno» per il QR: rilancia l'installer di Argo.")
            return
        contenuto = self.ponte.contenuto_qr()
        buf = io.BytesIO()
        segno.make(contenuto, error="m").save(buf, kind="png", scale=10, border=4, dark="#1E1E1E", light="#FFFFFF")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        # Sempre intero e nitido: ridimensionato senza sfumature
        self.qr.setPixmap(pix.scaled(340, 340, Qt.KeepAspectRatio, Qt.FastTransformation))
        indirizzi = ", ".join(pt.indirizzi_locali())
        self.stato.setText(f"In ascolto su {indirizzi} · porta {self.ponte.porta}. "
                           "Al primo collegamento il sistema potrebbe chiedere di consentire le connessioni in entrata.")

    def abbinato(self, nome):
        self.stato.setText(f"✅ {nome} collegato. Puoi chiudere questa finestra.")
        self.qr.clear()


class SchedaIncontri(QWidget):
    COLONNE = ["Incontro", "Data", "Durata", "Foto", "Persone", "Stato", "Avanzamento"]
    COL_TITOLO, COL_DATA, COL_DURATA, COL_FOTO, COL_PERSONE, COL_STATO, COL_AVANZ = range(7)

    def __init__(self, finestra, versione):
        super().__init__()
        self.finestra = finestra
        self.avvisi = _Avvisi()
        self.avvisi.arrivato.connect(self._evento)
        self.ponte = pt.Ponte(versione, notifica=lambda t, x: self.avvisi.arrivato.emit(t, x))
        self.dialogo = None

        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        # Stile Argo: un solo pulsante principale per pagina («Scrivi relazione»); il collegamento è secondario.
        self.b_collega = QPushButton("📱 Collega iPhone…")
        self.b_collega.clicked.connect(self.collega)
        bar.addWidget(self.b_collega)
        self.b_dispositivi = QToolButton()
        self.b_dispositivi.setText("iPhone collegati ▾")
        self.b_dispositivi.setPopupMode(QToolButton.InstantPopup)
        bar.addWidget(self.b_dispositivi)
        b_importa = QPushButton("Importa pacchetto…")
        b_importa.setToolTip("Un pacchetto Argo (.zip) arrivato per altra via, es. AirDrop o mail")
        b_importa.clicked.connect(self.importa_file)
        bar.addWidget(b_importa)
        bar.addStretch()
        self.b_cartella = QPushButton("Apri cartella")
        self.b_cartella.clicked.connect(self.apri_cartella)
        bar.addWidget(self.b_cartella)
        lay.addLayout(bar)

        self.l_ponte = QLabel("")
        self.l_ponte.setProperty("ruolo", "tenue")
        lay.addWidget(self.l_ponte)

        # Barra dei comandi (Stile Argo): azione principale per prima, poi le scelte
        comandi = QHBoxLayout()
        self.b_relazione = QPushButton("✨ Scrivi relazione")
        self.b_relazione.setProperty("primario", True)
        self.b_relazione.setToolTip("Mette in coda gli incontri selezionati: Ollama in locale scrive per ciascuno la "
                                    "relazione (trascrizione con i nomi + foto) con contatti, aziende, opportunità e azioni")
        self.b_relazione.clicked.connect(self.scrivi_relazione)
        comandi.addWidget(self.b_relazione)
        self.b_ferma = QPushButton("■ Ferma coda")
        self.b_ferma.setVisible(False)
        self.b_ferma.clicked.connect(self.ferma_coda)
        comandi.addWidget(self.b_ferma)
        comandi.addSpacing(12)
        comandi.addWidget(QLabel("Foto:"))
        self.c_vision = QComboBox()
        self.c_vision.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.c_vision.setToolTip("Un modello vision di Ollama guarda anche le foto (prodotti, stand, schemi); "
                                 "senza, si usa il testo letto dall'iPhone")
        self.c_vision.currentTextChanged.connect(self._salva_vision)
        comandi.addWidget(self.c_vision)
        comandi.addStretch()
        lay.addLayout(comandi)

        div = QSplitter(Qt.Vertical)
        self.tabella = QTableWidget(0, len(self.COLONNE))
        self.tabella.setHorizontalHeaderLabels(self.COLONNE)
        h = self.tabella.horizontalHeader()
        h.setSectionResizeMode(self.COL_TITOLO, QHeaderView.Stretch)
        for col, larghezza in ((self.COL_DATA, 130), (self.COL_DURATA, 70), (self.COL_FOTO, 50),
                               (self.COL_PERSONE, 70), (self.COL_STATO, 190), (self.COL_AVANZ, 110)):
            self.tabella.setColumnWidth(col, larghezza)
        self.tabella.verticalHeader().setVisible(False)
        self.tabella.verticalHeader().setDefaultSectionSize(36)
        self.tabella.setShowGrid(False)
        self.tabella.setWordWrap(False)
        self.tabella.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabella.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabella.itemSelectionChanged.connect(self._selezione_cambiata)
        self.tabella.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabella.customContextMenuRequested.connect(self._menu)
        QShortcut(QKeySequence.Delete, self.tabella, activated=self.togli_dalla_coda)
        div.addWidget(self.tabella)

        destra = QWidget()
        dl = QVBoxLayout(destra)
        dl.setContentsMargins(0, 0, 0, 0)
        self.l_titolo = QLabel("")
        self.l_titolo.setProperty("ruolo", "sezione")
        self.l_titolo.setWordWrap(True)
        dl.addWidget(self.l_titolo)
        self.l_info = QLabel("")
        self.l_info.setProperty("ruolo", "tenue")
        self.l_info.setWordWrap(True)
        dl.addWidget(self.l_info)
        self.foto = QWidget()
        self.foto_lay = QHBoxLayout(self.foto)
        self.foto_lay.setContentsMargins(0, 0, 0, 0)
        scorri = QScrollArea()
        scorri.setWidget(self.foto)
        scorri.setWidgetResizable(True)
        scorri.setFixedHeight(150)
        self.scorri_foto = scorri
        dl.addWidget(scorri)
        salva = QHBoxLayout()
        self.l_lavoro = QLabel("")
        self.l_lavoro.setProperty("ruolo", "tenue")
        self.l_lavoro.setWordWrap(True)
        salva.addWidget(self.l_lavoro, 1)
        self.b_salva_mod = QPushButton("Salva modifiche")
        self.b_salva_mod.setEnabled(False)
        self.b_salva_mod.clicked.connect(self.salva_modifiche)
        salva.addWidget(self.b_salva_mod)
        self.b_salva = QToolButton()
        self.b_salva.setText("Salva ▾")
        self.b_salva.setPopupMode(QToolButton.InstantPopup)
        ms = QMenu(self.b_salva)
        ms.addAction("Word (.docx)…").triggered.connect(lambda: self.esporta("docx"))
        ms.addAction("Markdown (.md)…").triggered.connect(lambda: self.esporta("md"))
        self.b_salva.setMenu(ms)
        salva.addWidget(self.b_salva)
        dl.addLayout(salva)

        self.schede = QTabWidget()
        self.testo = QPlainTextEdit()
        self.testo.setPlaceholderText("Nessuna relazione ancora: premi «✨ Scrivi relazione».")
        self.testo.textChanged.connect(lambda: self.b_salva_mod.setEnabled(self._caricato))
        self.schede.addTab(self.testo, "Relazione")
        self.t_trascrizione = QPlainTextEdit()
        self.t_trascrizione.setReadOnly(True)
        self.schede.addTab(self.t_trascrizione, "Trascrizione e foto")
        dl.addWidget(self.schede, 1)
        self.lavoro = None
        self._caricato = False
        div.addWidget(destra)
        div.setStretchFactor(0, 2)
        div.setStretchFactor(1, 3)
        lay.addWidget(div, 1)
        self.div = div
        # Coda delle relazioni: id incontro → {stato, progresso, nota}
        self.coda = []
        self.stati = {}
        self.in_corso = None
        self._lento = QTimer(self)
        self._lento.setInterval(2500)
        self._lento.timeout.connect(self._avanza_piano)

        self.vuoto = QLabel("Nessun incontro ancora.\nCollega l'iPhone con «📱 Collega iPhone…»: "
                            "gli incontri registrati in fiera o dai clienti arriveranno qui.")
        self.vuoto.setProperty("ruolo", "tenue")
        self.vuoto.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.vuoto, 1)
        self._incontri = []

        QTimer.singleShot(800, self._carica_modelli_vision)
        # Il Ponte parte da solo se c'è già almeno un iPhone collegato.
        if pt.dispositivi():
            QTimer.singleShot(500, self._avvia_ponte)
        self.aggiorna()

    # -- Ponte
    def _avvia_ponte(self):
        try:
            porta = self.ponte.avvia()
        except Exception as e:
            self.l_ponte.setText(f"⚠️ Ponte non avviato: {e}")
            return False
        self._aggiorna_stato_ponte(porta)
        return True

    def _aggiorna_stato_ponte(self, porta=None):
        n = len(pt.dispositivi())
        if self.ponte.attivo:
            self.l_ponte.setText(f"🔒 Ponte attivo in rete locale (porta {porta or self.ponte.porta}) · "
                                 f"{n} iPhone collegat{'o' if n == 1 else 'i'} · cifrato, nessun cloud")
        else:
            self.l_ponte.setText("Ponte spento: si accende quando colleghi un iPhone.")
        m = QMenu(self.b_dispositivi)
        for d in pt.dispositivi():
            visto = d.get("ultimo_contatto") or "mai"
            sotto = m.addMenu(f"{d['nome']} · ultimo contatto {visto}")
            azione = sotto.addAction("Scollega questo iPhone")
            azione.triggered.connect(lambda _c=False, i=d["id"], nome=d["nome"]: self._scollega(i, nome))
        if not pt.dispositivi():
            m.addAction("Nessun iPhone collegato").setEnabled(False)
        self.b_dispositivi.setMenu(m)

    def _scollega(self, id_dispositivo, nome):
        if QMessageBox.question(self, "Scollega", f"Scollegare {nome}? Non potrà più inviare incontri finché "
                                "non lo ricolleghi.") == QMessageBox.Yes:
            pt.scollega(id_dispositivo)
            self._aggiorna_stato_ponte()

    def collega(self):
        if not self.ponte.attivo and not self._avvia_ponte():
            return
        self.dialogo = DialogoAbbina(self.ponte, self)
        self.dialogo.exec()
        self.dialogo = None
        self.ponte.consuma_codice()
        self._aggiorna_stato_ponte()

    def _evento(self, tipo, testo):
        if tipo == "abbinato":
            if self.dialogo:
                self.dialogo.abbinato(testo)
            self._aggiorna_stato_ponte()
        elif tipo == "incontro":
            self.aggiorna()
            self.finestra.statusBar().showMessage(f"📱 Incontro ricevuto dall'iPhone: {testo}", 8000)

    def ferma(self):
        self.ferma_coda()
        if self.lavoro:
            self.lavoro.wait(3000)
        self.ponte.ferma()

    # -- incontri
    def importa_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Pacchetto Argo", str(Path.home() / "Downloads"), "Pacchetto Argo (*.zip)")
        if not f:
            return
        try:
            _id, dati = pt.importa_pacchetto(f, origine="file")
        except Exception as e:
            QMessageBox.warning(self, "Importazione non riuscita", str(e))
            return
        self.aggiorna()
        QMessageBox.information(self, "Incontro importato", f"«{dati.get('titolo', '')}» è tra gli Incontri.")

    def aggiorna(self):
        scelto = self._corrente()[0]
        self._incontri = pt.elenco_incontri()
        t = self.tabella
        t.blockSignals(True)
        t.setRowCount(len(self._incontri))
        for r, (cartella, d) in enumerate(self._incontri):
            titolo = rel.carica(cartella).get("relazione", {}).get("titolo") or d.get("titolo", cartella.name)
            it = QTableWidgetItem(titolo)
            it.setToolTip(titolo)
            t.setItem(r, self.COL_TITOLO, it)
            t.setItem(r, self.COL_DATA, QTableWidgetItem((d.get("creata") or "")[:16].replace("T", " ")))
            for col, valore in ((self.COL_DURATA, _durata(d.get("durata"))),
                                (self.COL_FOTO, str(len(d.get("foto", []))) if d.get("foto") else "–"),
                                (self.COL_PERSONE, str(len(d.get("partecipanti", []))) if d.get("partecipanti") else "–")):
                cella = QTableWidgetItem(valore)
                cella.setTextAlignment(Qt.AlignCenter)
                t.setItem(r, col, cella)
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 0, 10, 0)
            pb = QProgressBar()
            pb.setFixedHeight(8)
            pb.setTextVisible(False)
            bl.addWidget(pb)
            box.pb = pb
            t.setCellWidget(r, self.COL_AVANZ, box)
            self._aggiorna_riga(r)
        t.blockSignals(False)
        vuota = not self._incontri
        self.vuoto.setVisible(vuota)
        self.div.setVisible(not vuota)
        self.b_cartella.setEnabled(not vuota)
        if not vuota:
            ids = [c.name for c, _d in self._incontri]
            t.selectRow(ids.index(scelto.name) if scelto and scelto.name in ids else 0)
            self._mostra(0)
        self._aggiorna_comandi()
        self._aggiorna_stato_ponte()

    def _stato_di(self, cartella):
        """Stato della relazione: dalla coda se c'è, altrimenti da ciò che è salvato."""
        if cartella.name in self.stati:
            return self.stati[cartella.name]
        if (cartella / rel.FILE_TESTO).exists():
            return {"stato": "Pronta", "progresso": 100, "nota": rel.carica(cartella).get("generata", "")}
        return {"stato": "Da fare", "progresso": 0, "nota": ""}

    def _aggiorna_riga(self, r):
        if not 0 <= r < len(self._incontri):
            return
        cartella, _d = self._incontri[r]
        st = self._stato_di(cartella)
        c = tema.colori()
        pieno = st["stato"] in ("In corso", "Pronta", "Errore", "Interrotta")
        testo = st["stato"] + (f" - {st['nota']}" if st.get("nota") else "")
        it = QTableWidgetItem(("●  " if pieno else "○  ") + testo)
        it.setToolTip(testo)
        it.setForeground(QColor({"Pronta": c["ok"], "In corso": c["accento"], "Errore": c["err"],
                                 "Interrotta": c["warn"]}.get(st["stato"], c["tenue"])))
        self.tabella.setItem(r, self.COL_STATO, it)
        box = self.tabella.cellWidget(r, self.COL_AVANZ)
        pb = getattr(box, "pb", None)
        if pb:
            pb.setValue(int(st.get("progresso", 0)))
            pb.setVisible(st["stato"] == "In corso")

    def _riga_di(self, id_incontro):
        return next((r for r, (c, _d) in enumerate(self._incontri) if c.name == id_incontro), -1)

    def _selezionati(self):
        righe = sorted({i.row() for i in self.tabella.selectedIndexes()})
        return [self._incontri[r] for r in righe if r < len(self._incontri)]

    def _corrente(self):
        r = self.tabella.currentRow()
        if not 0 <= r < len(self._incontri):
            sel = self._selezionati()
            return sel[0] if sel else (None, None)
        return self._incontri[r]

    def _selezione_cambiata(self):
        self._mostra(self.tabella.currentRow())
        self._aggiorna_comandi()

    def _aggiorna_comandi(self):
        n = len(self._selezionati())
        self.b_relazione.setEnabled(n > 0)
        self.b_relazione.setText("✨ Scrivi relazione" + (f" ({n})" if n > 1 else ""))
        self.b_ferma.setVisible(bool(self.in_corso or self.coda))

    def _menu(self, pos):
        r = self.tabella.rowAt(pos.y())
        if r < 0:
            return
        if r not in {i.row() for i in self.tabella.selectedIndexes()}:
            self.tabella.selectRow(r)
        m = QMenu(self)
        m.addAction("✨ Scrivi relazione", self.scrivi_relazione)
        if any(c.name in self.coda for c, _d in self._selezionati()):
            m.addAction("Togli dalla coda", self.togli_dalla_coda)
        m.addSeparator()
        m.addAction("Apri cartella", self.apri_cartella)
        m.addAction("Elimina incontro…", self.elimina_incontri)
        m.exec(self.tabella.viewport().mapToGlobal(pos))

    def _mostra(self, _riga):
        cartella, d = self._corrente()
        while self.foto_lay.count():
            w = self.foto_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not cartella:
            return
        self.l_titolo.setText(rel.carica(cartella).get("relazione", {}).get("titolo") or d.get("titolo", ""))
        nomi = ", ".join(p.get("nome", p.get("id", "")) for p in d.get("partecipanti", []))
        ricevuto = {}
        try:
            ricevuto = json.loads((cartella / "ricevuto.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        self.l_info.setText(f"{(d.get('creata') or '')[:16].replace('T', ' ')} · durata {_durata(d.get('durata'))}"
                            + (f" · partecipanti: {nomi}" if nomi else "")
                            + (f" · ricevuto {ricevuto.get('ricevuto', '')} da {ricevuto.get('origine', '')}" if ricevuto else ""))
        for f in d.get("foto", []):
            pix = QPixmap(str(cartella / f.get("file", "")))
            if pix.isNull():
                continue
            l = QLabel()
            l.setPixmap(pix.scaledToHeight(130, Qt.SmoothTransformation))
            l.setToolTip(f"{_durata(f.get('secondo'))}\n{f.get('testo', '')}")
            self.foto_lay.addWidget(l)
        self.foto_lay.addStretch()
        self.scorri_foto.setVisible(bool(d.get("foto")))
        self._caricato = False
        mia = cartella / rel.FILE_TESTO
        st = self.stati.get(cartella.name)
        if st and st["stato"] in ("In corso", "In coda", "Errore"):
            self.testo.setPlainText(mia.read_text(encoding="utf-8") if mia.exists() else "")
            self.l_lavoro.setText({"In corso": "Relazione in corso…", "In coda": "In coda per la relazione."}
                                  .get(st["stato"], f"⚠️ {st.get('nota', '')}"))
        elif mia.exists():
            self.testo.setPlainText(mia.read_text(encoding="utf-8"))
            meta = rel.carica(cartella)
            self.l_lavoro.setText(f"Relazione del {meta.get('generata', '')} con {meta.get('modello_testo', '')}"
                                  + (f" · foto: {meta['modello_vision']}" if meta.get("modello_vision") else "")
                                  + ". Puoi modificarla qui.")
        else:
            iphone = cartella / "relazione.md"
            self.testo.setPlainText("")
            self.l_lavoro.setText("Seleziona uno o più incontri e premi «✨ Scrivi relazione»." + (
                " (C'è anche la bozza fatta sull'iPhone, nella scheda Trascrizione.)" if iphone.exists() else ""))
        descrizioni = {k: v.get("descrizione", "") for k, v in rel.carica(cartella).get("foto", {}).items()}
        self.t_trascrizione.setPlainText(rel.cronologia(cartella, d, descrizioni)
                                         + (("\n\n— Bozza fatta sull'iPhone —\n\n" + (cartella / "relazione.md").read_text(encoding="utf-8"))
                                            if (cartella / "relazione.md").exists() else ""))
        self._caricato = True
        self.b_salva_mod.setEnabled(False)

    # -- relazione
    def _carica_modelli_vision(self):
        s = core.carica_impostazioni()
        try:
            vision = rel.modelli_vision(s.get("ollama_url", llm.DEFAULT_URL))
        except Exception:
            vision = []
        self.c_vision.blockSignals(True)
        self.c_vision.clear()
        self.c_vision.addItem(SOLO_OCR)
        self.c_vision.addItems(vision)
        scelto = s.get("modello_vision")
        if scelto in vision:
            self.c_vision.setCurrentText(scelto)
        elif scelto is None and vision:
            self.c_vision.setCurrentIndex(1)  # prima volta: se c'è un modello vision, si usa
        self.c_vision.blockSignals(False)
        if not vision:
            self.c_vision.setToolTip("Nessun modello vision in Ollama: es. «ollama pull qwen2.5vl:7b» o gemma3")

    def _salva_vision(self, testo):
        s = core.carica_impostazioni()
        s["modello_vision"] = "" if testo == SOLO_OCR else testo
        core.salva_impostazioni(s)

    # -- coda delle relazioni (come la coda delle trascrizioni)
    def scrivi_relazione(self):
        scelti = self._selezionati()
        if not scelti:
            return
        gia_fatte = [c for c, _d in scelti if (c / rel.FILE_TESTO).exists() and c.name not in self.coda
                     and c.name != self.in_corso]
        if gia_fatte and QMessageBox.question(
                self, "Rifare le relazioni?",
                f"{len(gia_fatte)} degli incontri scelti ha già una relazione (con eventuali tue modifiche): "
                "sostituirla?") != QMessageBox.Yes:
            scelti = [x for x in scelti if x[0] not in gia_fatte]
        for cartella, _d in scelti:
            if cartella.name in self.coda or cartella.name == self.in_corso:
                continue
            self.coda.append(cartella.name)
            self.stati[cartella.name] = {"stato": "In coda", "progresso": 0, "nota": ""}
            self._aggiorna_riga(self._riga_di(cartella.name))
        self._aggiorna_comandi()
        self._prossima()

    def togli_dalla_coda(self):
        for cartella, _d in self._selezionati():
            if cartella.name in self.coda:
                self.coda.remove(cartella.name)
                self.stati.pop(cartella.name, None)
                self._aggiorna_riga(self._riga_di(cartella.name))
        self._aggiorna_comandi()

    def ferma_coda(self):
        for id_incontro in self.coda:
            self.stati.pop(id_incontro, None)
            self._aggiorna_riga(self._riga_di(id_incontro))
        self.coda.clear()
        if self.lavoro:
            self.lavoro.ferma()
            self.l_lavoro.setText("Mi fermo appena finisce il passaggio in corso…")
        self._aggiorna_comandi()

    def _prossima(self):
        if self.lavoro or not self.coda:
            if not self.coda and not self.lavoro:
                self.in_corso = None
                self._aggiorna_comandi()
            return
        id_incontro = self.coda.pop(0)
        r = self._riga_di(id_incontro)
        if r < 0:
            return self._prossima()
        cartella, d = self._incontri[r]
        s = core.carica_impostazioni()
        vision = "" if self.c_vision.currentText() == SOLO_OCR else self.c_vision.currentText()
        self.in_corso = id_incontro
        self.stati[id_incontro] = {"stato": "In corso", "progresso": 3, "nota": "preparo"}
        self._aggiorna_riga(r)
        self.lavoro = LavoroRelazione(cartella, d, s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_chat"),
                                      vision or None, self)
        self.lavoro.sig_stato.connect(lambda t, i=id_incontro: self._nota(i, t))
        self.lavoro.sig_avanzamento.connect(lambda p, i=id_incontro: self._progresso(i, p))
        self.lavoro.sig_fine.connect(lambda i=id_incontro: self._fine(i, None))
        self.lavoro.sig_errore.connect(lambda e, i=id_incontro: self._fine(i, e))
        self._lento.start()
        self._aggiorna_comandi()
        self.lavoro.start()

    def _nota(self, id_incontro, testo):
        st = self.stati.get(id_incontro)
        if st:
            st["nota"] = testo.rstrip("…").replace("Guardo la foto", "foto").replace("Scrivo la relazione con", "scrivo con")
            self._aggiorna_riga(self._riga_di(id_incontro))
        if self._corrente()[0] and self._corrente()[0].name == id_incontro:
            self.l_lavoro.setText(testo)

    def _progresso(self, id_incontro, percento):
        st = self.stati.get(id_incontro)
        if st:
            st["progresso"] = max(st.get("progresso", 0), percento)
            st["reale"] = percento
            self._aggiorna_riga(self._riga_di(id_incontro))

    def _avanza_piano(self):
        """Durante le chiamate lunghe la barra avanza piano, senza mai superare il passo successivo."""
        st = self.stati.get(self.in_corso or "")
        if st and st["stato"] == "In corso" and st["progresso"] < min(95, st.get("reale", 0) + 25):
            st["progresso"] += 1
            self._aggiorna_riga(self._riga_di(self.in_corso))

    def _fine(self, id_incontro, errore):
        self._lento.stop()
        self.lavoro = None
        self.in_corso = None
        if errore:
            self.stati[id_incontro] = {"stato": "Interrotta" if errore == "Interrotta" else "Errore",
                                       "progresso": 0, "nota": "" if errore == "Interrotta" else errore}
        else:
            self.stati.pop(id_incontro, None)  # «Pronta» si legge dal file salvato
        self.aggiorna()
        r = self._riga_di(id_incontro)
        corrente = self._corrente()[0]
        if not errore and corrente and corrente.name == id_incontro:
            self.schede.setCurrentIndex(0)
        if not self.coda:
            fatte = "Relazione pronta: rileggila prima di usarla." if not errore else f"Relazione non riuscita: {errore}"
            self.finestra.statusBar().showMessage(fatte, 8000)
        self._prossima()

    def elimina_incontri(self):
        scelti = [x for x in self._selezionati() if x[0].name != self.in_corso]
        if not scelti:
            return
        if QMessageBox.question(self, "Elimina", f"Eliminare {len(scelti)} incontr{'o' if len(scelti) == 1 else 'i'} "
                                "da questo computer (trascrizione, foto e relazione)?") != QMessageBox.Yes:
            return
        import shutil
        for cartella, _d in scelti:
            if cartella.name in self.coda:
                self.coda.remove(cartella.name)
            self.stati.pop(cartella.name, None)
            shutil.rmtree(cartella, ignore_errors=True)
        self.aggiorna()

    def salva_modifiche(self):
        cartella, _d = self._corrente()
        if cartella:
            (cartella / rel.FILE_TESTO).write_text(self.testo.toPlainText(), encoding="utf-8")
            self.b_salva_mod.setEnabled(False)
            self.finestra.statusBar().showMessage("Modifiche salvate.", 4000)

    def esporta(self, formato):
        cartella, d = self._corrente()
        testo = self.testo.toPlainText().strip()
        if not cartella or not testo:
            QMessageBox.information(self, "Niente da salvare", "Scrivi prima la relazione.")
            return
        nome = "".join(c if c.isalnum() or c in " -_" else "_" for c in d.get("titolo", "Incontro"))[:60].strip()
        estensione = ".docx" if formato == "docx" else ".md"
        f, _ = QFileDialog.getSaveFileName(self, "Salva la relazione", str(Path.home() / "Documents" / (nome + estensione)),
                                           "Word (*.docx)" if formato == "docx" else "Markdown (*.md)")
        if not f:
            return
        if formato == "docx":
            percorso = esporta_word.salva_docx(testo, f)
        else:
            percorso = Path(f)
            percorso.write_text(testo, encoding="utf-8")
        self.finestra.statusBar().showMessage(f"Salvata in {percorso}", 6000)

    def apri_cartella(self):
        cartella, _d = self._corrente()
        destinazione = cartella or pt.INCONTRI
        destinazione.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destinazione)))
