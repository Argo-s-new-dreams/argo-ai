"""incontri.py - pagina Incontri: ciò che arriva da Argo per iPhone (fiere, visite ai clienti).

Tappa 1: Ponte (abbinamento con QR, ricezione dei pacchetti), elenco e consultazione degli incontri.
Tappe successive: relazione con Ollama (testo + foto, anche con modello vision) e Dynamics 365 Sales.
"""
import io
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

import ponte as pt


def _durata(secondi):
    s = int(secondi or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


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
    def __init__(self, finestra, versione):
        super().__init__()
        self.finestra = finestra
        self.avvisi = _Avvisi()
        self.avvisi.arrivato.connect(self._evento)
        self.ponte = pt.Ponte(versione, notifica=lambda t, x: self.avvisi.arrivato.emit(t, x))
        self.dialogo = None

        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.b_collega = QPushButton("📱 Collega iPhone…")
        self.b_collega.setProperty("primario", True)
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

        div = QSplitter(Qt.Horizontal)
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._mostra)
        div.addWidget(self.lista)

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
        self.testo = QPlainTextEdit()
        self.testo.setReadOnly(True)
        dl.addWidget(self.testo, 1)
        prossimi = QLabel("Prossimi passi: relazione con Ollama (testo + foto) e invio a Dynamics 365 Sales.")
        prossimi.setProperty("ruolo", "tenue")
        dl.addWidget(prossimi)
        div.addWidget(destra)
        div.setStretchFactor(1, 3)
        lay.addWidget(div, 1)

        self.vuoto = QLabel("Nessun incontro ancora.\nCollega l'iPhone con «📱 Collega iPhone…»: "
                            "gli incontri registrati in fiera o dai clienti arriveranno qui.")
        self.vuoto.setProperty("ruolo", "tenue")
        self.vuoto.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.vuoto, 1)
        self._incontri = []

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
        self._incontri = pt.elenco_incontri()
        self.lista.blockSignals(True)
        self.lista.clear()
        for cartella, d in self._incontri:
            quando = (d.get("creata") or "")[:16].replace("T", " ")
            extra = []
            if d.get("foto"):
                extra.append(f"📷 {len(d['foto'])}")
            if d.get("partecipanti"):
                extra.append(f"👥 {len(d['partecipanti'])}")
            it = QListWidgetItem(f"{d.get('titolo', cartella.name)}\n{quando}  {'  '.join(extra)}")
            self.lista.addItem(it)
        self.lista.blockSignals(False)
        vuota = not self._incontri
        self.vuoto.setVisible(vuota)
        self.lista.parentWidget().setVisible(not vuota)
        self.b_cartella.setEnabled(not vuota)
        if not vuota:
            self.lista.setCurrentRow(0)
            self._mostra(0)
        self._aggiorna_stato_ponte()

    def _corrente(self):
        r = self.lista.currentRow()
        return self._incontri[r] if 0 <= r < len(self._incontri) else (None, None)

    def _mostra(self, _riga):
        cartella, d = self._corrente()
        while self.foto_lay.count():
            w = self.foto_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not cartella:
            return
        self.l_titolo.setText(d.get("titolo", ""))
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
        md = cartella / "relazione.md"
        self.testo.setPlainText(md.read_text(encoding="utf-8") if md.exists() else "")

    def apri_cartella(self):
        cartella, _d = self._corrente()
        destinazione = cartella or pt.INCONTRI
        destinazione.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destinazione)))
