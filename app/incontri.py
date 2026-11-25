"""incontri.py - pagina Incontri: ciò che arriva da Argo per iPhone (fiere, visite ai clienti).

Ponte (abbinamento con QR, ricezione dei pacchetti), elenco degli incontri, relazione con Ollama
(trascrizione + foto, anche con un modello vision). Prossima tappa: Dynamics 365 Sales.
"""
from lingua import tr
import io
import re
import json
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImageReader, QKeySequence, QPixmap, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget,
)

import crm_dynamics as crm
import crm_incontri
import esporta_word
import incontri_file as inf
import llm_locale as llm
import diagnostica
import ponte as pt
import esporta_trascrizione
import gruppi_incontri as gruppi
import relazione_incontro as rel
import secondo_cervello as cervello
import secondo_cervello_ui as cervello_ui
import tema
import template_relazione as tpl
import veglia
import voci_core as core

FILE_CODA = core.APP_HOME / "incontri_coda.json"

SOLO_OCR = "Solo testo letto dall'iPhone"


def _durata(secondi):
    s = int(secondi or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"



class VistaRelazione(QTextBrowser):
    """Relazione impaginata con le foto dell'incontro: i percorsi relativi partono dalla cartella dell'incontro,
    le foto sono ruotate come le ha scattate il telefono e ridotte alla larghezza della vista."""

    LARGHEZZA_MAX = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cartella = None

    def loadResource(self, tipo, url):
        immagine = QTextDocument.ResourceType.ImageResource
        if tipo in (immagine, getattr(immagine, "value", 2)):
            percorso = Path(url.toLocalFile() or url.path())
            if not percorso.is_absolute() and self.cartella:
                percorso = Path(self.cartella) / percorso
            if percorso.is_file():
                lettore = QImageReader(str(percorso))
                lettore.setAutoTransform(True)
                img = lettore.read()
                if not img.isNull():
                    larghezza = min(self.LARGHEZZA_MAX, max(200, self.viewport().width() - 40))
                    if img.width() > larghezza:
                        img = img.scaledToWidth(larghezza, Qt.SmoothTransformation)
                    return img
        return super().loadResource(tipo, url)

class LavoroRelazione(QObject):
    """Scrive la relazione di un incontro fuori dall'interfaccia, con stato e avanzamento.

    Gira in un thread «daemon»: se Argo si chiude mentre Ollama sta ancora rispondendo, la chiusura non resta
    appesa (l'incontro risulterà «Interrotta» alla riapertura, come nelle trascrizioni)."""
    sig_stato = Signal(str)
    sig_avanzamento = Signal(int)
    sig_fine = Signal()
    sig_errore = Signal(str)

    def __init__(self, cartella, sessione, url, modello_testo, modello_vision, parent=None, template=None):
        super().__init__(parent)
        self.argomenti = (cartella, sessione, url, modello_testo, modello_vision)
        self.template = template
        self._stop = False
        self._thread = None

    def ferma(self):
        self._stop = True

    def start(self):
        self._thread = threading.Thread(target=self.run, name="argo-relazione", daemon=True)
        self._thread.start()

    def wait(self, millisecondi):
        if self._thread:
            self._thread.join(millisecondi / 1000)

    def _stato_trace(self, testo):
        diagnostica.log.debug("relazione · passo %d", self._passi)  # in trace solo il numero del passo
        self._passi += 1
        self.sig_stato.emit(testo)

    def run(self):
        self._passi = 1
        cartella, sessione, url, testo, vision = self.argomenti
        try:
            with veglia.tieni("relazione"), diagnostica.misura("relazione incontro", modello=testo,
                                                               foto=vision or None):
                rel.scrivi_relazione(cartella, sessione, url, testo, vision, stato=self._stato_trace,
                                     stop=lambda: self._stop, avanzamento=self.sig_avanzamento.emit,
                                     template=self.template)
            self.sig_fine.emit()
        except Exception as e:
            self.sig_errore.emit("Interrotta" if self._stop else str(e))


class LavoroFile(QObject):
    """Nuovi incontri da audio/video e file aggiunti a un incontro, uno dopo l'altro, fuori dall'interfaccia.

    operazioni: [("nuovo", file)] oppure [("aggiungi", cartella, [file…])]."""
    sig_stato = Signal(str)
    sig_avanzamento = Signal(int)
    sig_fatto = Signal(str, str)     # id incontro, riepilogo
    sig_errore = Signal(str, str)    # nome del file o dell'incontro, errore
    sig_fine = Signal()

    def __init__(self, operazioni, versione, parent=None):
        super().__init__(parent)
        self.operazioni = list(operazioni)
        self.versione = versione
        self._stop = False
        self._thread = None

    def ferma(self):
        self._stop = True

    def start(self):
        self._thread = threading.Thread(target=self.run, name="argo-incontri-file", daemon=True)
        self._thread.start()

    def wait(self, millisecondi):
        if self._thread:
            self._thread.join(millisecondi / 1000)

    def _stato(self, prefisso):
        def stato(testo, percento=None):
            self.sig_stato.emit(prefisso + testo)
            if percento is not None:
                self.sig_avanzamento.emit(int(percento))
        return stato

    def run(self):
        totale = len(self.operazioni)
        for n, op in enumerate(self.operazioni, 1):
            if self._stop:
                break
            prefisso = f"[{n} di {totale}] " if totale > 1 else ""
            inizio = time.time()
            try:
                with veglia.tieni("incontro da file"), diagnostica.misura("incontro da file", operazione=op[0],
                                        file=diagnostica.descrivi_file(op[1]) if op[0] == "nuovo" else f"{len(op[2])} file"):
                    self._esegui(op, prefisso)
            except Exception as e:
                nome = Path(op[1]).name if op[0] == "nuovo" else "incontro"
                errore = "Interrotto" if self._stop else str(e)
                if not self._stop and veglia.sospeso_dal(inizio):
                    errore = ("il computer è andato in sospensione durante il lavoro (coperchio chiuso o tasto di "
                              "accensione): riprova tenendolo acceso. Dettaglio: " + errore)
                self.sig_errore.emit(nome, errore)
        self.sig_fine.emit()

    def _esegui(self, op, prefisso):
        if op[0] == "nuovo":
            cartella, s = inf.crea_da_media(op[1], self.versione, self._stato(prefisso),
                                            stop=lambda: self._stop)
            nomi = ", ".join(p["nome"] for p in s["partecipanti"])
            self.sig_fatto.emit(cartella.name, f"«{s['titolo']}» creato" + (f" · {nomi}" if nomi else ""))
        else:
            _tipo, cartella, file = op
            sessione = json.loads((Path(cartella) / "sessione.json").read_text(encoding="utf-8"))
            _s, riepilogo, scartati = inf.aggiungi_file(cartella, sessione, file, self._stato(prefisso),
                                                        stop=lambda: self._stop)
            testo = f"Aggiunti a «{sessione.get('titolo', '')}»: {riepilogo or 'nulla'}"
            if scartati:
                testo += f" · non supportati: {', '.join(scartati)}"
            self.sig_fatto.emit(Path(cartella).name, testo)


class EditorTemplate(QWidget):
    """Impostazioni › Relazioni: i template della relazione (standard da duplicare e personali da modificare)."""
    cambiato = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        sx = QVBoxLayout()
        self.elenco = QListWidget()
        self.elenco.setMinimumWidth(230)
        self.elenco.currentRowChanged.connect(self._mostra)
        sx.addWidget(self.elenco, 1)
        bott = QHBoxLayout()
        for testo, azione, aiuto in (("Nuovo", self.nuovo, "Un template vuoto da riempire"),
                                     ("Duplica", self.duplica, "Copia il template selezionato per modificarlo"),
                                     ("Elimina", self.elimina, "Elimina il template personale selezionato")):
            b = QPushButton(testo)
            b.setToolTip(aiuto)
            b.clicked.connect(azione)
            bott.addWidget(b)
            setattr(self, "b_" + testo.lower(), b)
        sx.addLayout(bott)
        self.b_predefinito = QPushButton(tr('★ Usa come predefinito'))
        self.b_predefinito.setToolTip(tr('Il template proposto in Incontri e usato da Clienti › Dalla call'))
        self.b_predefinito.clicked.connect(self.rendi_predefinito)
        sx.addWidget(self.b_predefinito)
        lay.addLayout(sx)

        dx = QVBoxLayout()
        self.l_nota = QLabel("")
        self.l_nota.setWordWrap(True)
        self.l_nota.setProperty("ruolo", "tenue")
        dx.addWidget(self.l_nota)
        f = QFormLayout()
        self.e_nome = QLineEdit()
        f.addRow(tr('Nome:'), self.e_nome)
        self.e_descrizione = QLineEdit()
        self.e_descrizione.setPlaceholderText(tr('Quando usarlo, in una riga'))
        f.addRow(tr('Descrizione:'), self.e_descrizione)
        self.c_lunghezza = QComboBox()
        for k, (nome, _guida) in tpl.LUNGHEZZE.items():
            self.c_lunghezza.addItem(nome, k)
        f.addRow(tr('Lunghezza:'), self.c_lunghezza)
        self.c_forma = QComboBox()
        for k, (nome, aiuto) in tpl.FORME.items():
            self.c_forma.addItem(nome, k)
            self.c_forma.setItemData(self.c_forma.count() - 1, aiuto, Qt.ToolTipRole)
        self.c_forma.currentIndexChanged.connect(self._forma_cambiata)
        f.addRow(tr('Forma:'), self.c_forma)
        self.e_struttura = QPlainTextEdit()
        self.e_struttura.setPlaceholderText(tr("Capitoli e contenuti del documento, uno per riga. Per esempio:\n## 1. Executive summary: …\n## 2. Il processo attuale: …\nLe foto vanno da sole dentro i capitoli dove aiutano a spiegare."))
        self.e_struttura.setMinimumHeight(160)
        f.addRow(tr('Struttura del documento:'), self.e_struttura)
        self.l_sezioni = QListWidget()
        self.l_sezioni.setDragDropMode(QAbstractItemView.InternalMove)
        self.l_sezioni.setToolTip(tr("Spunta le sezioni da mostrare e trascinale per cambiare l'ordine"))
        self.l_sezioni.setMinimumHeight(250)
        f.addRow(tr('Sezioni:'), self.l_sezioni)
        nota_sez = QLabel(tr("Spunta le sezioni e trascinale nell'ordine che vuoi. Contatti, aziende e azioni vengono comunque estratti per Dynamics e Clienti, anche se non li mostri."))
        nota_sez.setWordWrap(True)
        nota_sez.setProperty("ruolo", "tenue")
        f.addRow("", nota_sez)
        self.e_istruzioni = QPlainTextEdit()
        self.e_istruzioni.setPlaceholderText(
            tr('Come la vuoi, in parole tue. Per esempio:\n• Scrivi per il direttore commerciale: prima il valore economico, poi il resto.\n• Tono diretto, frasi brevi, niente aggettivi.\n• Evidenzia sempre i concorrenti citati e le obiezioni sul prezzo.\n• Le azioni al futuro, con il nome di chi le fa.'))
        self.e_istruzioni.setMinimumHeight(140)
        f.addRow(tr('Come la voglio:'), self.e_istruzioni)
        dx.addLayout(f)
        riga = QHBoxLayout()
        self.b_salva = QPushButton(tr('Salva template'))
        self.b_salva.setProperty("primario", True)
        self.b_salva.clicked.connect(self.salva)
        riga.addWidget(self.b_salva)
        self.l_esito = QLabel("")
        self.l_esito.setProperty("ruolo", "tenue")
        riga.addWidget(self.l_esito, 1)
        dx.addLayout(riga)
        lay.addLayout(dx, 1)
        self.ricarica()

    def ricarica(self, seleziona=None):
        corrente = seleziona or (self._id_corrente() if self.elenco.count() else None)
        predefinito = tpl.predefinito()["id"]
        self.elenco.blockSignals(True)
        self.elenco.clear()
        for t in tpl.tutti():
            testo = ("★ " if t["id"] == predefinito else "") + t["nome"] + ("  · standard" if t.get("standard") else "")
            it = QListWidgetItem(testo)
            it.setData(Qt.UserRole, t["id"])
            it.setToolTip(t.get("descrizione", ""))
            self.elenco.addItem(it)
        self.elenco.blockSignals(False)
        ids = [self.elenco.item(i).data(Qt.UserRole) for i in range(self.elenco.count())]
        self.elenco.setCurrentRow(ids.index(corrente) if corrente in ids else 0)
        self._mostra(self.elenco.currentRow())

    def _id_corrente(self):
        it = self.elenco.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _mostra(self, _riga):
        t = tpl.trova(self._id_corrente())
        if not t:
            return
        standard = bool(t.get("standard"))
        self.e_nome.setText(t["nome"])
        self.e_descrizione.setText(t.get("descrizione", ""))
        self.c_lunghezza.setCurrentIndex(max(0, self.c_lunghezza.findData(t.get("lunghezza", "media"))))
        self.l_sezioni.clear()
        ordine = t["sezioni"] + [k for k in tpl.SEZIONI if k not in t["sezioni"]]
        for k in ordine:
            titolo, guida = tpl.SEZIONI[k]
            it = QListWidgetItem(titolo)
            it.setData(Qt.UserRole, k)
            it.setToolTip(guida)
            flag = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            if not standard:
                flag |= Qt.ItemIsDragEnabled
            it.setFlags(flag)
            it.setCheckState(Qt.Checked if k in t["sezioni"] else Qt.Unchecked)
            self.l_sezioni.addItem(it)
        self.e_istruzioni.setPlainText(t.get("istruzioni", ""))
        self.c_forma.blockSignals(True)
        self.c_forma.setCurrentIndex(max(0, self.c_forma.findData(t.get("forma", "schede"))))
        self.c_forma.blockSignals(False)
        self.e_struttura.setPlainText(t.get("struttura", ""))
        for w in (self.e_nome, self.e_descrizione, self.e_istruzioni, self.e_struttura):
            w.setReadOnly(standard)
        self.c_forma.setEnabled(not standard)
        self.c_lunghezza.setEnabled(not standard)
        self.l_sezioni.setEnabled(True)
        self.l_sezioni.setDragDropMode(QAbstractItemView.NoDragDrop if standard else QAbstractItemView.InternalMove)
        if standard:  # le spunte di un template standard non si cambiano
            for i in range(self.l_sezioni.count()):
                it = self.l_sezioni.item(i)
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
        self.b_salva.setEnabled(not standard)
        self.b_elimina.setEnabled(not standard)
        self.b_predefinito.setEnabled(t["id"] != tpl.predefinito()["id"])
        self.l_nota.setText(tr('🔒 Template standard di Argo: per cambiarlo premi «Duplica» e modifica la copia.')
                            if standard else tr('✎ Template tuo: modificalo e premi «Salva template».'))
        self.l_esito.setText("")
        self._forma_cambiata()

    def _forma_cambiata(self, _i=None):
        documento = self.c_forma.currentData() == "documento"
        self.e_struttura.setEnabled(documento)
        self.l_sezioni.setEnabled(not documento)

    def _dal_modulo(self):
        sezioni = [self.l_sezioni.item(i).data(Qt.UserRole) for i in range(self.l_sezioni.count())
                   if self.l_sezioni.item(i).checkState() == Qt.Checked]
        return {"id": self._id_corrente(), "nome": self.e_nome.text(), "descrizione": self.e_descrizione.text(),
                "lunghezza": self.c_lunghezza.currentData(), "sezioni": sezioni,
                "istruzioni": self.e_istruzioni.toPlainText(), "forma": self.c_forma.currentData(),
                "struttura": self.e_struttura.toPlainText()}

    def salva(self):
        dati = self._dal_modulo()
        if not dati["sezioni"] and dati["forma"] != "documento":
            QMessageBox.information(self, tr('Nessuna sezione'), tr('Spunta almeno una sezione.'))
            return
        t = tpl.salva(dati)
        self.ricarica(t["id"])
        self.l_esito.setText(tr('Salvato «{nome}».', nome=t['nome']))
        self.cambiato.emit()

    def nuovo(self):
        t = tpl.salva({"nome": "Nuovo template", "sezioni": ["riassunto", "punti_chiave", "azioni"],
                       "lunghezza": "media", "descrizione": "", "istruzioni": ""})
        self.ricarica(t["id"])
        self.e_nome.setFocus()
        self.e_nome.selectAll()
        self.cambiato.emit()

    def duplica(self):
        t = tpl.duplica(self._id_corrente())
        self.ricarica(t["id"])
        self.e_nome.setFocus()
        self.e_nome.selectAll()
        self.cambiato.emit()

    def elimina(self):
        t = tpl.trova(self._id_corrente())
        if not t or t.get("standard"):
            return
        if QMessageBox.question(self, tr('Elimina template'), tr('Eliminare il template «{nome}»? Le relazioni già scritte non cambiano.', nome=t['nome'])) != QMessageBox.Yes:
            return
        tpl.elimina(t["id"])
        self.ricarica()
        self.cambiato.emit()

    def rendi_predefinito(self):
        tpl.imposta_predefinito(self._id_corrente())
        self.ricarica(self._id_corrente())
        self.cambiato.emit()


class _Avvisi(QObject):
    """Porta le notifiche del server (thread del Ponte) nel thread dell'interfaccia."""
    arrivato = Signal(str, str)


class DialogoAbbina(QDialog):
    """Mostra il QR da inquadrare con Argo per iPhone (Impostazioni › Argo sul computer › Collega)."""

    def __init__(self, ponte, parent=None):
        super().__init__(parent)
        self.ponte = ponte
        self.setWindowTitle(tr('Collega un iPhone'))
        lay = QVBoxLayout(self)
        testo = QLabel(tr('Su iPhone apri <b>Argo › Impostazioni › Argo sul computer › Collega</b> e inquadra il codice.<br>Il codice vale 5 minuti e una sola volta. iPhone e computer devono essere sulla stessa rete.'))
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
        b_nuovo = QPushButton(tr('Nuovo codice'))
        b_nuovo.clicked.connect(self._mostra)
        b_chiudi = QPushButton(tr('Chiudi'))
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
            self.stato.setText(tr("Manca la libreria «segno» per il QR: rilancia l'installer di Argo."))
            return
        contenuto = self.ponte.contenuto_qr()
        buf = io.BytesIO()
        segno.make(contenuto, error="m").save(buf, kind="png", scale=10, border=4, dark="#1E1E1E", light="#FFFFFF")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        # Sempre intero e nitido: ridimensionato senza sfumature
        self.qr.setPixmap(pix.scaled(340, 340, Qt.KeepAspectRatio, Qt.FastTransformation))
        indirizzi = ", ".join(pt.indirizzi_locali())
        self.stato.setText(tr('In ascolto su {indirizzi} · porta {porta}. Al primo collegamento il sistema potrebbe chiedere di consentire le connessioni in entrata.', indirizzi=indirizzi, porta=self.ponte.porta))

    def abbinato(self, nome):
        self.stato.setText(tr('✅ {nome} collegato. Puoi chiudere questa finestra.', nome=nome))
        self.qr.clear()


class SchedaIncontri(QWidget):
    COLONNE = ["Incontro", "Data", "Durata", "Foto", "Persone", "CRM", "Template", "Modello", "Stato", "Avanzamento"]
    (COL_TITOLO, COL_DATA, COL_DURATA, COL_FOTO, COL_PERSONE, COL_CRM, COL_TEMPLATE, COL_MODELLO, COL_STATO,
     COL_AVANZ) = range(10)

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
        self.b_collega = QPushButton(tr('📱 Collega iPhone…'))
        self.b_collega.clicked.connect(self.collega)
        bar.addWidget(self.b_collega)
        self.b_dispositivi = QToolButton()
        self.b_dispositivi.setText(tr('iPhone collegati ▾'))
        self.b_dispositivi.setPopupMode(QToolButton.InstantPopup)
        bar.addWidget(self.b_dispositivi)
        b_importa = QPushButton(tr('Importa pacchetto…'))
        b_importa.setToolTip(tr('Un pacchetto Argo (.zip) arrivato per altra via, es. AirDrop o mail'))
        b_importa.clicked.connect(self.importa_file)
        bar.addWidget(b_importa)
        self.b_nuovo = QPushButton(tr('🎙 Nuovo da audio/video…'))
        self.b_nuovo.setToolTip(tr("Crea un incontro da una registrazione o da un video (anche più file, uno per incontro): trascrizione, parlanti e voci note sul computer, poi la relazione come per l'iPhone. Puoi anche trascinare i file su questa pagina."))
        self.b_nuovo.clicked.connect(self.nuovo_da_media)
        bar.addWidget(self.b_nuovo)
        bar.addStretch()
        self.b_cartella = QPushButton(tr('Apri cartella'))
        self.b_cartella.clicked.connect(self.apri_cartella)
        bar.addWidget(self.b_cartella)
        lay.addLayout(bar)

        self.l_ponte = QLabel("")
        self.l_ponte.setProperty("ruolo", "tenue")
        lay.addWidget(self.l_ponte)

        self.riga_file = QWidget()
        rf = QHBoxLayout(self.riga_file)
        rf.setContentsMargins(0, 0, 0, 0)
        self.l_file = QLabel("")
        self.l_file.setWordWrap(True)
        rf.addWidget(self.l_file, 1)
        self.pb_file = QProgressBar()
        self.pb_file.setFixedWidth(160)
        self.pb_file.setFixedHeight(8)
        self.pb_file.setTextVisible(False)
        rf.addWidget(self.pb_file)
        b_ferma_file = QPushButton(tr('■ Ferma'))
        b_ferma_file.clicked.connect(self.ferma_file)
        rf.addWidget(b_ferma_file)
        self.riga_file.setVisible(False)
        lay.addWidget(self.riga_file)
        self.lavoro_file = None
        self.setAcceptDrops(True)

        # Barra dei comandi (Stile Argo): azione principale per prima, poi le scelte
        comandi = QHBoxLayout()
        self.b_relazione = QPushButton(tr('✨ Scrivi relazione'))
        self.b_relazione.setProperty("primario", True)
        self.b_relazione.setToolTip(tr('Mette in coda gli incontri selezionati: Ollama in locale (o il modello cloud scelto) scrive per ciascuno la relazione (trascrizione con i nomi + foto) con contatti, aziende, opportunità e azioni'))
        self.b_relazione.clicked.connect(self.scrivi_relazione)
        comandi.addWidget(self.b_relazione)
        self.b_ferma = QPushButton(tr('■ Ferma coda'))
        self.b_ferma.setVisible(False)
        self.b_ferma.clicked.connect(self.ferma_coda)
        comandi.addWidget(self.b_ferma)
        self.b_riprendi = QPushButton(tr('▶ Riprendi coda'))
        self.b_riprendi.setVisible(False)
        self.b_riprendi.setToolTip(tr('Riprende gli incontri rimasti in coda (anche dopo la chiusura di Argo)'))
        self.b_riprendi.clicked.connect(self.riprendi_coda)
        comandi.addWidget(self.b_riprendi)
        comandi.addSpacing(12)
        self.l_template = QLabel(tr('Template:'))
        comandi.addWidget(self.l_template)
        self.c_template = QComboBox()
        self.c_template.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.c_template.setToolTip(tr('Come scrivere la relazione: sezioni, lunghezza e indicazioni. Si creano e si modificano in Impostazioni › Relazioni.'))
        comandi.addWidget(self.c_template)
        self.c_template.currentIndexChanged.connect(lambda _i: [self._aggiorna_riga(r) for r in range(len(getattr(self, '_incontri', [])))])
        self.carica_template()
        comandi.addSpacing(12)
        self.l_foto = QLabel(tr('Foto:'))
        comandi.addWidget(self.l_foto)
        self.c_vision = QComboBox()
        self.c_vision.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.c_vision.setToolTip(tr("Un modello vision di Ollama guarda anche le foto (prodotti, stand, schemi); senza, si usa il testo letto dall'iPhone"))
        self.c_vision.currentIndexChanged.connect(lambda _i: self._salva_vision(self._vision_scelto()))
        comandi.addWidget(self.c_vision)
        self.c_vision.currentIndexChanged.connect(lambda _i: [self._aggiorna_riga(r) for r in range(len(getattr(self, '_incontri', [])))])
        comandi.addStretch()
        lay.addLayout(comandi)

        div = QSplitter(Qt.Vertical)
        self.tabella = QTableWidget(0, len(self.COLONNE))
        self.tabella.setHorizontalHeaderLabels(self.COLONNE)
        h = self.tabella.horizontalHeader()
        h.setSectionResizeMode(self.COL_TITOLO, QHeaderView.Stretch)
        for col, larghezza in ((self.COL_DATA, 130), (self.COL_DURATA, 70), (self.COL_FOTO, 50),
                               (self.COL_PERSONE, 70), (self.COL_CRM, 50), (self.COL_TEMPLATE, 150), (self.COL_MODELLO, 150),
                               (self.COL_STATO, 190), (self.COL_AVANZ, 110)):
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
        QShortcut(QKeySequence(Qt.Key_F2), self.tabella, activated=self.rinomina)
        self.tabella.cellDoubleClicked.connect(lambda _r, c: self.rinomina() if c == self.COL_TITOLO else None)
        self.tabella.cellClicked.connect(self._clic_titolo)
        self._aperti, self._livello = set(), {}
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
        self.b_allega = QPushButton(tr('📎 Aggiungi file…'))
        self.b_allega.setToolTip(tr("Aggiunge all'incontro foto (descritte dal modello vision), documenti PDF/Word/testo (letti dalla relazione) e altri audio o video (trascritti in coda all'incontro)"))
        self.b_allega.clicked.connect(self.aggiungi_file)
        salva.addWidget(self.b_allega)
        self.b_modifica = QPushButton(tr('✏️ Modifica'))
        self.b_modifica.setCheckable(True)
        self.b_modifica.setToolTip(tr('Passa dal testo impaginato al Markdown da correggere, e ritorno'))
        self.b_modifica.toggled.connect(self._modalita_modifica)
        salva.addWidget(self.b_modifica)
        self.b_salva_mod = QPushButton(tr('Salva modifiche'))
        self.b_salva_mod.setEnabled(False)
        self.b_salva_mod.clicked.connect(self.salva_modifiche)
        salva.addWidget(self.b_salva_mod)
        self.b_crm = QPushButton(tr('☁️ Invia a Dynamics…'))
        self.b_crm.setToolTip(tr('Dynamics 365 Sales: nuovo lead o aggancio a contatti/account esistenti, con relazione, foto e azioni. Scegli tu caso per caso.'))
        self.b_crm.clicked.connect(self.invia_crm)
        salva.addWidget(self.b_crm)
        self.b_salva = QToolButton()
        self.b_salva.setText(tr('Salva ▾'))
        self.b_salva.setPopupMode(QToolButton.InstantPopup)
        ms = QMenu(self.b_salva)
        ms.addAction(tr('Relazione in Word (.docx)…')).triggered.connect(lambda: self.esporta("docx"))
        ms.addAction(tr('Relazione in Markdown (.md)…')).triggered.connect(lambda: self.esporta("md"))
        ms.addSeparator()
        ms.addAction(tr('Trascrizione in Word (.docx)…')).triggered.connect(
            lambda: esporta_trascrizione.scarica(self, self._sorgente_trascrizione, ("docx",)))
        ms.addAction(tr('Trascrizione in WebVTT (.vtt)…')).triggered.connect(
            lambda: esporta_trascrizione.scarica(self, self._sorgente_trascrizione, ("vtt",)))
        ms.addAction(tr('Trascrizione in Word e WebVTT…')).triggered.connect(
            lambda: esporta_trascrizione.scarica(self, self._sorgente_trascrizione, ("docx", "vtt")))
        self.b_salva.setMenu(ms)
        salva.addWidget(self.b_salva)
        dl.addLayout(salva)

        self.schede = QTabWidget()
        # Relazione: vista impaginata (Markdown) e, con «Modifica», il testo da correggere
        self.vista = VistaRelazione()
        self.vista.setOpenExternalLinks(True)
        self.testo = QPlainTextEdit()
        self.testo.setPlaceholderText(tr('Nessuna relazione ancora: premi «✨ Scrivi relazione».'))
        self.testo.textChanged.connect(lambda: self.b_salva_mod.setEnabled(self._caricato))
        self.pila = QStackedWidget()
        self.pila.addWidget(self.vista)
        self.pila.addWidget(self.testo)
        self.schede.addTab(self.pila, tr('Relazione'))
        self.t_trascrizione = QPlainTextEdit()
        self.t_trascrizione.setReadOnly(True)
        self.schede.addTab(self.t_trascrizione, tr('Trascrizione e foto'))
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
        self.in_pausa = False
        self._carica_coda()
        self._lento = QTimer(self)
        self._lento.setInterval(2500)
        self._lento.timeout.connect(self._avanza_piano)

        self.vuoto = tema.StatoVuoto("Nessun incontro ancora. Collega l'iPhone con «📱 Collega iPhone…» in alto: "
                                     "gli incontri registrati in fiera o dai clienti arriveranno qui da soli. "
                                     "Oppure crea un incontro da una registrazione o da un video con "
                                     "«🎙 Nuovo da audio/video…», o trascina qui i file.")
        lay.addWidget(self.vuoto, 1)
        self._incontri = []

        QTimer.singleShot(800, self._carica_modelli_vision)
        # Il Ponte parte da solo se c'è già almeno un iPhone collegato.
        if pt.dispositivi() and not diagnostica.MODALITA_SICURA:  # in modalità sicura si avvia solo a mano
            QTimer.singleShot(500, self._avvia_ponte)
        self.aggiorna()

    # -- Ponte
    def _avvia_ponte(self):
        try:
            porta = self.ponte.avvia()
        except Exception as e:
            diagnostica.log.warning("Ponte non avviato: %s", e)
            self.l_ponte.setText(tr('⚠️ Ponte non avviato: {e}', e=e))
            return False
        diagnostica.log.info("Ponte avviato sulla porta %s", porta)
        self._aggiorna_stato_ponte(porta)
        return True

    def _aggiorna_stato_ponte(self, porta=None):
        n = len(pt.dispositivi())
        if self.ponte.attivo:
            self.l_ponte.setText((tr('🔒 Ponte attivo in rete locale (porta {porta}) · 1 iPhone collegato · cifrato, nessun cloud', porta=porta or self.ponte.porta) if n == 1 else tr('🔒 Ponte attivo in rete locale (porta {porta}) · {n} iPhone collegati · cifrato, nessun cloud', porta=porta or self.ponte.porta, n=n)))
        else:
            self.l_ponte.setText(tr('Ponte spento: si accende quando colleghi un iPhone.'))
        m = QMenu(self.b_dispositivi)
        for d in pt.dispositivi():
            visto = d.get("ultimo_contatto") or "mai"
            sotto = m.addMenu(tr('{nome} · ultimo contatto {visto}', nome=d['nome'], visto=visto))
            azione = sotto.addAction(tr('Scollega questo iPhone'))
            azione.triggered.connect(lambda _c=False, i=d["id"], nome=d["nome"]: self._scollega(i, nome))
        if not pt.dispositivi():
            m.addAction(tr('Nessun iPhone collegato')).setEnabled(False)
        self.b_dispositivi.setMenu(m)

    def _scollega(self, id_dispositivo, nome):
        if QMessageBox.question(self, tr('Scollega'), tr('Scollegare {nome}? Non potrà più inviare incontri finché non lo ricolleghi.', nome=nome)) == QMessageBox.Yes:
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
            self.finestra.statusBar().showMessage(tr("📱 Incontro ricevuto dall'iPhone: {testo}", testo=testo), 8000)

    def occupata(self):
        return self.lavoro is not None or self.lavoro_file is not None

    def ferma(self):
        """Chiusura di Argo: la coda resta salvata; l'incontro in corso risulterà «Interrotta»."""
        self.in_pausa = True  # nessun nuovo incontro parte mentre Argo si chiude
        self._salva_coda()
        if self.lavoro:
            self.lavoro.ferma()
            self.lavoro.wait(1500)
        if self.lavoro_file:
            self.lavoro_file.ferma()
            self.lavoro_file.wait(1500)
        self.ponte.ferma()

    def carica_template(self):
        """Riempie la tendina dei template (anche dopo una modifica nelle Impostazioni), sul predefinito."""
        scelto = self.c_template.currentData() if self.c_template.count() else None
        predefinito = tpl.predefinito()["id"]
        if predefinito != getattr(self, "_predefinito_visto", predefinito):
            scelto = predefinito  # cambiato il ★ nelle Impostazioni: la tendina lo segue
        self._predefinito_visto = predefinito
        self.c_template.blockSignals(True)
        self.c_template.clear()
        for t in tpl.tutti():
            self.c_template.addItem(("" if t.get("standard") else "✎ ") + t["nome"], t["id"])
            self.c_template.setItemData(self.c_template.count() - 1, t.get("descrizione", ""), Qt.ToolTipRole)
        i = self.c_template.findData(scelto) if scelto else -1
        if i < 0:
            i = self.c_template.findData(tpl.predefinito()["id"])
        self.c_template.setCurrentIndex(max(0, i))
        self.c_template.blockSignals(False)

    # -- incontri da file audio/video e file aggiunti
    def nuovo_da_media(self):
        file, _ = QFileDialog.getOpenFileNames(self, tr('Registrazioni o video da trasformare in incontri'),
                                               str(Path.home()), inf.filtro_dialogo(solo_media=True))
        if file:
            self._avvia_file([("nuovo", f) for f in file])

    def aggiungi_file(self, file=None):
        cartella, _d = self._corrente()
        if not cartella:
            QMessageBox.information(self, tr('Scegli un incontro'), tr("Seleziona prima l'incontro a cui aggiungere i file."))
            return
        if not file:
            file, _ = QFileDialog.getOpenFileNames(self, tr("File da aggiungere all'incontro"), str(Path.home()),
                                                   inf.filtro_dialogo())
        if file:
            self._avvia_file([("aggiungi", cartella, list(file))])

    def _avvia_file(self, operazioni):
        if self.lavoro_file:
            QMessageBox.information(self, tr('Un momento'), tr('Sto già elaborando dei file: aspetta che finisca o premi «Ferma».'))
            return
        if any(op[0] == "nuovo" for op in operazioni) or any(
                inf.tipo_di(f) == "audio" for op in operazioni if op[0] == "aggiungi" for f in op[2]):
            if not core.leggi_token():
                QMessageBox.warning(self, tr('Manca il token'), tr('Per trascrivere e riconoscere i parlanti serve il token Hugging Face: Impostazioni › Token.'))
                return
        self._esiti_file = []
        lav = LavoroFile(operazioni, getattr(self.ponte, "versione_app", ""), self)
        lav.sig_stato.connect(self.l_file.setText)
        lav.sig_avanzamento.connect(self.pb_file.setValue)
        lav.sig_fatto.connect(self._file_fatto)
        lav.sig_errore.connect(lambda nome, e: self._esiti_file.append(f"⚠️ {nome}: {e}"))
        lav.sig_fine.connect(self._file_finiti)
        self.lavoro_file = lav
        self.pb_file.setValue(0)
        self.l_file.setText(tr('Avvio…'))
        self.riga_file.setVisible(True)
        self.b_nuovo.setEnabled(False)
        self.b_allega.setEnabled(False)
        lav.start()

    def _file_fatto(self, id_incontro, riepilogo):
        self._esiti_file.append("✅ " + riepilogo)
        self.aggiorna()
        r = self._riga_di(id_incontro)
        if r >= 0:
            self.tabella.selectRow(r)

    def _file_finiti(self):
        self.lavoro_file = None
        self.riga_file.setVisible(False)
        self.b_nuovo.setEnabled(True)
        self.b_allega.setEnabled(True)
        esiti = self._esiti_file or ["Niente da fare."]
        self.finestra.statusBar().showMessage(" · ".join(esiti), 15000)
        if any(e.startswith("⚠️") for e in esiti):
            QMessageBox.warning(self, tr('File non elaborati'), "\n".join(esiti))
        elif any(e.startswith("✅") for e in esiti):
            QMessageBox.information(self, tr('Fatto'), "\n".join(esiti)
                                    + "\n\nSeleziona l'incontro e premi «✨ Scrivi relazione» per la relazione.")

    def ferma_file(self):
        if self.lavoro_file:
            self.lavoro_file.ferma()
            self.l_file.setText(tr('Mi fermo appena possibile…'))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        file = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        media = [f for f in file if inf.tipo_di(f) == "audio"]
        altri = [f for f in file if inf.tipo_di(f) in ("immagine", "documento")]
        cartella, d = self._corrente()
        operazioni = []
        if media:
            if cartella and QMessageBox.question(
                    self, tr('Audio o video'), tr("{len} audio/video: creo un incontro nuovo per ciascuno?\n\n«No» li aggiunge in coda all'incontro selezionato («{get}»).", len=len(media), get=d.get('titolo', ''))) == QMessageBox.No:
                altri += media
            else:
                operazioni += [("nuovo", f) for f in media]
        if altri:
            if not cartella:
                QMessageBox.information(self, tr('Scegli un incontro'),
                                        tr('Foto e documenti si aggiungono a un incontro: selezionane uno e riprova.'))
            else:
                operazioni.append(("aggiungi", cartella, altri))
        if operazioni:
            self._avvia_file(operazioni)

    # -- incontri
    def importa_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr('Pacchetto Argo'), str(Path.home() / "Downloads"), "Pacchetto Argo (*.zip)")
        if not f:
            return
        try:
            _id, dati = pt.importa_pacchetto(f, origine="file")
        except Exception as e:
            QMessageBox.warning(self, tr('Importazione non riuscita'), str(e))
            return
        self.aggiorna()
        QMessageBox.information(self, tr('Incontro importato'), tr('«{get}» è tra gli Incontri.', get=dati.get('titolo', '')))

    def aggiorna(self):
        scelto = self._corrente()[0]
        tutti = pt.elenco_incontri()
        per_id = {c.name: (c, d) for c, d in tutti}
        # Gruppi (uno a molti): i figli stanno sotto il capogruppo, visibili quando il gruppo è aperto
        self._incontri, self._livello = [], {}
        for c, d in tutti:
            if gruppi.capogruppo_di(c):
                continue
            self._incontri.append((c, d))
            figli = [f for f in gruppi.figli(c) if f.name in per_id]
            self._livello[c.name] = ("capo", len(figli)) if figli else ("solo", 0)
            if figli and c.name in self._aperti:
                for f in figli:
                    self._incontri.append(per_id[f.name])
                    self._livello[f.name] = ("figlio", 0)
        t = self.tabella
        t.blockSignals(True)
        t.setRowCount(len(self._incontri))
        for r, (cartella, d) in enumerate(self._incontri):
            titolo = rel.titolo(cartella, d, cartella.name)
            tipo, n = self._livello.get(cartella.name, ("solo", 0))
            if tipo == "capo":
                testo = ("▾ " if cartella.name in self._aperti else "▸ ") + titolo + f"  ·  {n + 1} incontri"
                suggerimento = tr('Relazione unica di {n} incontri: clic su ▸ per vedere gli incontri del gruppo', n=n + 1)
            elif tipo == "figlio":
                testo, suggerimento = "      ↳ " + titolo, tr('Fa parte del gruppo: la relazione è sul primo incontro')
            else:
                testo, suggerimento = titolo, titolo
            it = QTableWidgetItem(testo)
            it.setToolTip(suggerimento)
            if tipo == "capo":
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            t.setItem(r, self.COL_TITOLO, it)
            t.setItem(r, self.COL_DATA, QTableWidgetItem((d.get("creata") or "")[:16].replace("T", " ")))
            for col, valore in ((self.COL_DURATA, _durata(d.get("durata"))),
                                (self.COL_FOTO, str(len(d.get("foto", []))) if d.get("foto") else "–"),
                                (self.COL_PERSONE, str(len(d.get("partecipanti", []))) if d.get("partecipanti") else "–")):
                cella = QTableWidgetItem(valore)
                cella.setTextAlignment(Qt.AlignCenter)
                t.setItem(r, col, cella)
            inviato = crm_incontri.esito(cartella)
            cella = QTableWidgetItem("☁️" if inviato else "–")
            cella.setTextAlignment(Qt.AlignCenter)
            if inviato:
                cella.setToolTip(f"Inviato a Dynamics il {inviato.get('inviato', '')}: "
                                 + ", ".join(f"{r.get('nome', '')} ({r.get('tipo', '')})" for r in inviato.get("record", [])))
            t.setItem(r, self.COL_CRM, cella)
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
        # Stile Argo: senza incontri le azioni sugli incontri si nascondono e il primario diventa «Collega iPhone»
        self.b_cartella.setVisible(not vuota)
        for w in (self.b_relazione, self.l_foto, self.c_vision, self.l_template, self.c_template):
            w.setVisible(not vuota)
        tema.rimarca(self.b_collega, vuota)
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
        self.tabella.setItem(r, self.COL_TEMPLATE, self._cella_template(cartella, st))
        self.tabella.setItem(r, self.COL_MODELLO, self._cella_modello(cartella, st))
        box = self.tabella.cellWidget(r, self.COL_AVANZ)
        pb = getattr(box, "pb", None)
        if pb:
            pb.setValue(int(st.get("progresso", 0)))
            pb.setVisible(st["stato"] == "In corso")

    def _cella_template(self, cartella, st):
        """Con quale template è stata scritta la relazione; per quelle in coda o in corso, quello scelto."""
        c = tema.colori()
        if st["stato"] in ("In coda", "In corso"):
            t = tpl.trova(st.get("template") or self.c_template.currentData()) or {}
            nome = t.get("nome", "")
            it = QTableWidgetItem(("→ " if st["stato"] == "In coda" else "") + (nome or "predefinito"))
            it.setToolTip(("Template che verrà usato" if st["stato"] == "In coda" else "Template in uso") + f": {nome or 'il predefinito'}")
            it.setForeground(QColor(c["accento"] if st["stato"] == "In corso" else c["tenue"]))
            return it
        meta = rel.carica(cartella) if (cartella / rel.FILE_TESTO).exists() else {}
        nome = (meta.get("template") or {}).get("nome", "") if isinstance(meta.get("template"), dict) else ""
        it = QTableWidgetItem(nome or "–")
        if nome:
            it.setToolTip(f"Relazione scritta con il template «{nome}»")
        else:
            it.setTextAlignment(Qt.AlignCenter)
        return it

    def _cella_modello(self, cartella, st):
        """Con quale modello è stata scritta la relazione; per quelle in coda, quello che verrà usato adesso."""
        c = tema.colori()
        if st["stato"] in ("In coda", "In corso"):
            if st.get("modello"):
                testo, foto = st["modello"], st.get("modello_foto", "")
            else:
                testo, foto = rel.modelli_previsti(core.carica_impostazioni().get("modello_chat"),
                                                   self._vision_scelto() or None)
            it = QTableWidgetItem(("→ " if st["stato"] == "In coda" else "") + (testo or "nessun modello"))
            it.setToolTip(("Modello che verrà usato" if st["stato"] == "In coda" else "Modello in uso")
                          + f": {testo or 'scegline uno in Impostazioni › Modelli AI'}" + (f" · foto: {foto}" if foto else ""))
            it.setForeground(QColor(c["accento"] if st["stato"] == "In corso" else c["tenue"]))
            return it
        meta = rel.carica(cartella) if (cartella / rel.FILE_TESTO).exists() else {}
        testo = meta.get("modello_testo") or ""
        it = QTableWidgetItem(testo or "–")
        if testo:
            it.setToolTip(f"Relazione scritta con {testo}" + (f" · foto: {meta['modello_vision']}" if meta.get("modello_vision") else "")
                          + (f" · {meta.get('generata', '')}" if meta.get("generata") else ""))
        else:
            it.setTextAlignment(Qt.AlignCenter)
        return it

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
        self.b_ferma.setVisible(bool(self.lavoro))
        self.b_riprendi.setVisible(bool(self.coda) and not self.lavoro)
        self.b_riprendi.setText(tr('▶ Riprendi coda ({len})', len=len(self.coda)))

    # -- coda salvata su disco (come quella delle trascrizioni)
    def _salva_coda(self):
        stati = {i: {k: v for k, v in st.items() if k in ("stato", "nota", "template")}
                 for i, st in self.stati.items() if st.get("stato") in ("In coda", "Errore", "Interrotta")}
        if self.in_corso:
            stati[self.in_corso] = {"stato": "In corso", "nota": "",
                                    "template": (self.stati.get(self.in_corso) or {}).get("template")}
        try:
            core.APP_HOME.mkdir(parents=True, exist_ok=True)
            FILE_CODA.write_text(json.dumps({"coda": ([self.in_corso] if self.in_corso else []) + self.coda,
                                             "stati": stati}, indent=1, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.finestra.statusBar().showMessage(tr('Impossibile salvare la coda degli incontri: {e}', e=e), 8000)

    def _carica_coda(self):
        try:
            dati = json.loads(FILE_CODA.read_text(encoding="utf-8"))
        except Exception:
            return
        esistenti = {c.name for c, _d in pt.elenco_incontri()}
        for i, st in dati.get("stati", {}).items():
            if i not in esistenti:
                continue
            if st.get("stato") == "In corso":
                st = {"stato": "Interrotta", "nota": "app chiusa durante l'elaborazione"}
            self.stati[i] = {"stato": st.get("stato", "In coda"), "progresso": 0, "nota": st.get("nota", ""),
                             "template": st.get("template")}
        # Chi era in corso torna in fondo? No: come nelle trascrizioni resta «Interrotta» e si rimette a mano.
        self.coda = [i for i in dati.get("coda", []) if i in esistenti and self.stati.get(i, {}).get("stato") == "In coda"]
        self.in_pausa = bool(self.coda)

    def _menu(self, pos):
        r = self.tabella.rowAt(pos.y())
        if r < 0:
            return
        if r not in {i.row() for i in self.tabella.selectedIndexes()}:
            self.tabella.selectRow(r)
        m = QMenu(self)
        m.addAction(tr('✨ Scrivi relazione'), self.scrivi_relazione)
        m.addAction(tr('📎 Aggiungi file…'), self.aggiungi_file)
        if len(self._selezionati()) == 1:
            m.addAction(tr('✏️ Rinomina…'), self.rinomina)
        scelti = self._selezionati()
        if len(scelti) >= 2:
            m.addAction(tr('🧩 Relazione unica di {n} incontri…', n=len(scelti)), self.relazione_unica)
        if len(scelti) == 1 and self._livello.get(scelti[0][0].name, ("",))[0] == "capo":
            aperto = scelti[0][0].name in self._aperti
            m.addAction(tr('▾ Nascondi gli incontri del gruppo') if aperto else tr('▸ Mostra gli incontri del gruppo'),
                        lambda c=scelti[0][0]: self._apri_chiudi(c))
            m.addAction(tr('Separa il gruppo…'), self.separa_gruppo)
        m.addMenu(esporta_trascrizione.menu(self, self._sorgente_trascrizione)).setText(tr('⬇️ Scarica trascrizione'))
        if cervello.attivo():
            m.addAction(tr('🧠 Con chi stai parlando?…'), self.con_chi)
        if any(c.name in self.coda for c, _d in self._selezionati()):
            m.addAction(tr('Togli dalla coda'), self.togli_dalla_coda)
        m.addSeparator()
        m.addAction(tr('Apri cartella'), self.apri_cartella)
        m.addAction(tr('Elimina incontro…'), self.elimina_incontri)
        m.exec(self.tabella.viewport().mapToGlobal(pos))

    def _mostra(self, _riga):
        cartella, d = self._corrente()
        while self.foto_lay.count():
            w = self.foto_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not cartella:
            return
        self.l_titolo.setText(rel.titolo(cartella, d))
        nota_gruppo = ""
        if gruppi.e_capogruppo(cartella):
            d = gruppi.sessione_unita(cartella)  # relazione, foto e trascrizione: la somma del gruppo
            nota_gruppo = f" · relazione unica di {len(d.get('gruppo', []))} incontri"
        elif gruppi.capogruppo_di(cartella):
            capo = pt.INCONTRI / gruppi.capogruppo_di(cartella)
            nota_gruppo = f" · nel gruppo di «{rel.titolo(capo, None, capo.name)}», che ha la relazione unica"
        nomi = ", ".join(p.get("nome", p.get("id", "")) for p in d.get("partecipanti", []))
        ricevuto = {}
        try:
            ricevuto = json.loads((cartella / "ricevuto.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        self.l_info.setText(f"{(d.get('creata') or '')[:16].replace('T', ' ')} · durata {_durata(d.get('durata'))}"
                            + (f" · partecipanti: {nomi}" if nomi else "")
                            + (f" · ricevuto {ricevuto.get('ricevuto', '')} da {ricevuto.get('origine', '')}" if ricevuto else "")
                            + (" · allegati: " + ", ".join(a.get("nome", "") for a in d.get("allegati", []))
                               if d.get("allegati") else "") + nota_gruppo)
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
                                  + (f" · template «{meta['template']['nome']}»" if meta.get("template") else "")
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
        self.b_crm.setEnabled((cartella / rel.FILE_TESTO).exists() and cartella.name != self.in_corso)
        inviato = crm_incontri.esito(cartella)
        if inviato:
            self.l_lavoro.setText(self.l_lavoro.text() + f" · ☁️ in Dynamics dal {inviato.get('inviato', '')}")
        self._aggiorna_vista()

    # -- relazione
    def _carica_modelli_vision(self):
        s = core.carica_impostazioni()
        try:
            vision = rel.modelli_vision(s.get("ollama_url", llm.DEFAULT_URL))
        except Exception:
            vision = []
        self.c_vision.blockSignals(True)
        self.c_vision.clear()
        self.c_vision.addItem(SOLO_OCR, "")
        dim = llm.dimensioni(s.get("ollama_url", llm.DEFAULT_URL))  # GB sul disco accanto a ogni modello
        for nome in vision:
            self.c_vision.addItem(llm.etichetta(nome, dim.get(nome)), nome)
        scelto = s.get("modello_vision")
        if scelto in vision:
            self.c_vision.setCurrentIndex(self.c_vision.findData(scelto))
        elif scelto is None and vision:
            self.c_vision.setCurrentIndex(1)  # prima volta: se c'è un modello vision, si usa
        self.c_vision.blockSignals(False)
        if not vision:
            self.c_vision.setToolTip(tr('Nessun modello vision in Ollama: es. «ollama pull qwen2.5vl:7b» o gemma3'))

    def _vision_scelto(self):
        """Nome del modello vision scelto ('' = solo il testo letto dall'iPhone)."""
        dato = self.c_vision.currentData()
        return dato if dato is not None else ("" if self.c_vision.currentText() == SOLO_OCR else self.c_vision.currentText())

    def _salva_vision(self, nome):
        s = core.carica_impostazioni()
        s["modello_vision"] = nome or ""
        core.salva_impostazioni(s)

    # -- coda delle relazioni (come la coda delle trascrizioni)
    def scrivi_relazione(self):
        scelti = self._selezionati()
        if not scelti:
            return
        gia_fatte = [c for c, _d in scelti if (c / rel.FILE_TESTO).exists() and c.name not in self.coda
                     and c.name != self.in_corso]
        if gia_fatte and QMessageBox.question(
                self, tr('Rifare le relazioni?'),
                tr('{len} degli incontri scelti ha già una relazione (con eventuali tue modifiche): sostituirla?', len=len(gia_fatte))) != QMessageBox.Yes:
            scelti = [x for x in scelti if x[0] not in gia_fatte]
        for cartella, _d in scelti:
            if cartella.name in self.coda or cartella.name == self.in_corso:
                continue
            self.coda.append(cartella.name)
            self.stati[cartella.name] = {"stato": "In coda", "progresso": 0, "nota": "",
                                         "template": self.c_template.currentData()}
            self._aggiorna_riga(self._riga_di(cartella.name))
        self.in_pausa = False
        self._salva_coda()
        self._aggiorna_comandi()
        self._prossima()

    def riprendi_coda(self):
        self.in_pausa = False
        self._prossima()

    def togli_dalla_coda(self):
        for cartella, _d in self._selezionati():
            if cartella.name in self.coda:
                self.coda.remove(cartella.name)
                self.stati.pop(cartella.name, None)
                self._aggiorna_riga(self._riga_di(cartella.name))
        self._salva_coda()
        self._aggiorna_comandi()

    def ferma_coda(self):
        """Come «Ferma coda» delle trascrizioni: si ferma, gli altri restano in coda per «Riprendi»."""
        self.in_pausa = True
        if self.lavoro:
            self.lavoro.ferma()
            self.l_lavoro.setText(tr('Mi fermo appena finisce il passaggio in corso…'))
        self._salva_coda()
        self._aggiorna_comandi()

    def _prossima(self):
        if self.in_pausa:
            self._aggiorna_comandi()
            return
        if self.lavoro or not self.coda:
            if not self.coda and not self.lavoro:
                self.in_corso = None
                self._aggiorna_comandi()
            return
        id_incontro = self.coda.pop(0)
        r = self._riga_di(id_incontro)
        cartella = pt.INCONTRI / id_incontro
        if not (cartella / "sessione.json").exists():
            return self._prossima()
        d = gruppi.sessione_unita(cartella)  # per un capogruppo: la somma degli incontri del gruppo
        s = core.carica_impostazioni()
        vision = self._vision_scelto()
        self.in_corso = id_incontro
        template = (self.stati.get(id_incontro) or {}).get("template") or self.c_template.currentData()
        m_testo, m_foto = rel.modelli_previsti(s.get("modello_chat"), vision or None)
        self.stati[id_incontro] = {"stato": "In corso", "progresso": 3, "nota": "preparo", "template": template,
                                   "modello": m_testo, "modello_foto": m_foto}
        self._aggiorna_riga(r)
        self.lavoro = LavoroRelazione(cartella, d, s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_chat"),
                                      vision or None, self, template=template)
        self.lavoro.sig_stato.connect(lambda t, i=id_incontro: self._nota(i, t))
        self.lavoro.sig_avanzamento.connect(lambda p, i=id_incontro: self._progresso(i, p))
        self.lavoro.sig_fine.connect(lambda i=id_incontro: self._fine(i, None))
        self.lavoro.sig_errore.connect(lambda e, i=id_incontro: self._fine(i, e))
        self._lento.start()
        self._salva_coda()
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
        self._salva_coda()
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
        if QMessageBox.question(self, tr('Elimina'), (tr("Eliminare l'incontro da questo computer (trascrizione, foto e relazione)?") if len(scelti) == 1 else tr('Eliminare {n} incontri da questo computer (trascrizione, foto e relazione)?', n=len(scelti)))) != QMessageBox.Yes:
            return
        import shutil
        for cartella, _d in scelti:
            if cartella.name in self.coda:
                self.coda.remove(cartella.name)
            self.stati.pop(cartella.name, None)
            shutil.rmtree(cartella, ignore_errors=True)
        self._salva_coda()
        self.aggiorna()

    def _aggiorna_vista(self):
        md = self.testo.toPlainText().strip()
        self.vista.cartella, _d = self._corrente()
        if md:
            # Qt mostra _testo_ come sottolineato: le righe in corsivo delle prime relazioni diventano *testo*
            self.vista.setMarkdown(re.sub(r"(?m)^_(.+)_$", r"*\1*", md))
        else:
            self.vista.setMarkdown("_Nessuna relazione ancora: seleziona l'incontro e premi «✨ Scrivi relazione»._")
        self.b_modifica.setEnabled(bool(md))
        if not md and self.b_modifica.isChecked():
            self.b_modifica.setChecked(False)

    def _modalita_modifica(self, attiva):
        if not attiva:
            self._aggiorna_vista()
        self.pila.setCurrentWidget(self.testo if attiva else self.vista)
        self.b_modifica.setText(tr('👁 Anteprima') if attiva else tr('✏️ Modifica'))

    def invia_crm(self):
        cartella, d = self._corrente()
        if not cartella:
            return
        if not crm.configurato():
            QMessageBox.information(self, tr('Dynamics 365'), tr("Prima collega Dynamics in Impostazioni › Dynamics 365 Sales (indirizzo dell'ambiente e accesso)."))
            return
        if self.b_salva_mod.isEnabled():
            self.salva_modifiche()  # su Dynamics va la versione corretta a mano
        if crm_incontri.esito(cartella) and QMessageBox.question(
                self, tr('Già inviato'), tr('Questo incontro è già stato inviato a Dynamics. Inviarlo di nuovo? (Controlla le destinazioni per non creare doppioni.)')) != QMessageBox.Yes:
            return
        if crm_incontri.DialogoCRM(cartella, d, self).exec():
            self.aggiorna()

    def salva_modifiche(self):
        cartella, _d = self._corrente()
        if cartella:
            (cartella / rel.FILE_TESTO).write_text(self.testo.toPlainText(), encoding="utf-8")
            self.b_salva_mod.setEnabled(False)
            self._aggiorna_vista()
            self.finestra.statusBar().showMessage(tr('Modifiche salvate.'), 4000)

    def esporta(self, formato):
        cartella, d = self._corrente()
        testo = self.testo.toPlainText().strip()
        if not cartella or not testo:
            QMessageBox.information(self, tr('Niente da salvare'), tr('Scrivi prima la relazione.'))
            return
        nome = "".join(c if c.isalnum() or c in " -_" else "_" for c in rel.titolo(cartella, d, "Incontro"))[:60].strip()
        estensione = ".docx" if formato == "docx" else ".md"
        f, _ = QFileDialog.getSaveFileName(self, tr('Salva la relazione'), str(Path.home() / "Documents" / (nome + estensione)),
                                           "Word (*.docx)" if formato == "docx" else "Markdown (*.md)")
        if not f:
            return
        if formato == "docx":
            percorso = esporta_word.salva_docx(testo, f, cartella_immagini=cartella)
        else:  # le foto restano nell'incontro: nel .md il percorso completo, così si vedono anche da un'altra cartella
            percorso = Path(f)
            percorso.write_text(re.sub(r"(!\[[^\]]*\]\()<?([^)>]+)>?\)",
                                       lambda m: m.group(1) + "<" + (m.group(2) if Path(m.group(2)).is_absolute()
                                                                     else str(cartella / m.group(2))) + ">)", testo),
                                encoding="utf-8")
        self.finestra.statusBar().showMessage(tr('Salvata in {percorso}', percorso=percorso), 6000)

    def _sorgente_trascrizione(self):
        cartella, d = self._corrente()
        if not cartella:
            return None
        titolo = rel.titolo(cartella, d, "Incontro")
        return (esporta_trascrizione.da_incontro(cartella, sessione=gruppi.sessione_unita(cartella)), titolo,
                Path.home() / "Documents", f"Trascrizione: {titolo}")

    def _apri_chiudi(self, cartella):
        self._aperti.symmetric_difference_update({cartella.name})
        self.aggiorna()

    def _clic_titolo(self, r, colonna):
        """Clic sul ▸/▾ di un capogruppo: apre o chiude il gruppo."""
        if colonna != self.COL_TITOLO or not 0 <= r < len(self._incontri):
            return
        cartella = self._incontri[r][0]
        if self._livello.get(cartella.name, ("",))[0] != "capo":
            return
        from PySide6.QtGui import QCursor
        x = self.tabella.viewport().mapFromGlobal(QCursor.pos()).x() - self.tabella.visualItemRect(self.tabella.item(r, colonna)).x()
        if x < 26:
            self._apri_chiudi(cartella)

    def relazione_unica(self):
        scelti = [c for c, _d in self._selezionati()]
        if len(scelti) < 2:
            return
        if any(c.name == self.in_corso or c.name in self.coda for c in scelti):
            QMessageBox.information(self, tr('Relazione unica'), tr('Uno degli incontri scelti è in coda o in lavorazione: aspetta che finisca.'))
            return
        tutti = []
        for c in scelti:
            for m in gruppi.membri(c):
                if m not in tutti:
                    tutti.append(m)
        tutti.sort(key=lambda c: (json.loads((c / "sessione.json").read_text(encoding="utf-8")).get("creata") or ""))
        elenco = "\n".join(f"• {rel.titolo(c, None, c.name)}" for c in tutti)
        if QMessageBox.question(
                self, tr('Relazione unica'),
                tr("Unisco questi {n} incontri in un gruppo e scrivo una sola relazione sulla somma delle trascrizioni:\n\n"
                   "{elenco}\n\nLa relazione va sul primo in ordine di tempo («{primo}»), che diventa il capogruppo; "
                   "gli altri restano collegati sotto. Se il primo ha già una relazione, viene sostituita.",
                   n=len(tutti), elenco=elenco, primo=rel.titolo(tutti[0], None, tutti[0].name))) != QMessageBox.Yes:
            return
        try:
            capo = gruppi.crea(tutti)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr('Relazione unica'), str(e))
            return
        self._aperti.add(capo.name)
        self.metti_in_coda([capo])

    def metti_in_coda(self, cartelle):
        """Relazione per queste cartelle, in coda come «✨ Scrivi relazione» (senza chiedere conferma)."""
        self.aggiorna()
        for cartella in cartelle:
            if cartella.name in self.coda or cartella.name == self.in_corso:
                continue
            self.coda.append(cartella.name)
            self.stati[cartella.name] = {"stato": "In coda", "progresso": 0, "nota": "",
                                         "template": self.c_template.currentData()}
            r = self._riga_di(cartella.name)
            self._aggiorna_riga(r)
            if r >= 0:
                self.tabella.selectRow(r)
        self.in_pausa = False
        self._salva_coda()
        self._aggiorna_comandi()
        self._prossima()

    def separa_gruppo(self):
        cartella, _d = self._corrente()
        if not cartella or not gruppi.e_capogruppo(cartella):
            return
        if QMessageBox.question(self, tr('Separa il gruppo'),
                                tr('Gli incontri del gruppo tornano indipendenti. La relazione unica resta su «{titolo}».',
                                   titolo=rel.titolo(cartella, None, cartella.name))) != QMessageBox.Yes:
            return
        gruppi.separa(cartella)
        self._aperti.discard(cartella.name)
        self.aggiorna()

    def con_chi(self):
        cartella, d = self._corrente()
        if cartella:
            titolo = rel.titolo(cartella, d)
            cervello_ui.collega(self, cartella, titolo, "incontro")

    def rinomina(self):
        cartella, d = self._corrente()
        if not cartella or cartella.name == self.in_corso:
            return
        attuale = rel.titolo(cartella, d)
        nuovo, ok = QInputDialog.getText(self, tr('Rinomina incontro'), tr('Titolo dell\'incontro:'), text=attuale)
        nuovo = " ".join((nuovo or "").split())
        if not ok or not nuovo or nuovo == attuale:
            return
        try:
            rel.rinomina(cartella, nuovo)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr('Rinomina incontro'), tr('Non riesco a rinominare: {e}', e=e))
            return
        self.aggiorna()
        self._mostra(None)
        self.finestra.statusBar().showMessage(tr('Incontro rinominato in «{nuovo}».', nuovo=nuovo), 5000)

    def apri_cartella(self):
        cartella, _d = self._corrente()
        destinazione = cartella or pt.INCONTRI
        destinazione.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destinazione)))
