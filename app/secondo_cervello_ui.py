"""secondo_cervello_ui.py - pagina «Secondo cervello» e dialogo «Con chi stai parlando?».

La logica e i dati sono in secondo_cervello.py; qui solo l'interfaccia.
"""
from lingua import tr
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

import cervello_base as base
import cervello_suggerimenti as sug
import secondo_cervello as sc
import veglia

SPIEGAZIONE = (
    "<b>Il Secondo cervello</b> fa crescere a ogni incontro una base di conoscenza che poi ti aiuta: domande da fare "
    "e temi da toccare, prima e durante le interviste (metodo CODE: cattura, organizza, distilla, esprimi).<br><br>"
    "<b>Organizza</b>: all'inizio di un incontro Argo ti chiede <b>con chi stai parlando</b>. Le aziende finiscono in "
    "un catalogo (settore, dimensione, attività, area); le persone <b>non</b> si catalogano per nome, solo per "
    "<b>funzione</b>, e su di loro non si cerca nulla sul web.<br>"
    "<b>Distilla</b>: dagli incontri catalogati il modello locale estrae solo fatti utili al lavoro e li salva nella "
    "<b>Base</b>, anonimizzati in modo <b>irreversibile</b>: niente nomi, niente collegamento all'incontro, niente "
    "questioni personali o giudizi sulle persone.<br>"
    "<b>Esprimi</b>: prima di un incontro, nella scheda <b>Prepara</b> (o con «💡 Suggerimenti» quando scegli con chi "
    "parli), Argo propone domande e temi presi dagli incontri simili della Base.<br>"
    "Tutto resta <b>su questo computer</b>. I suggerimenti durante la trascrizione Live arrivano nella prossima versione.")


class _Lavoro(QObject):
    sig_stato = Signal(str)
    sig_fine = Signal(object)
    sig_errore = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.fermato = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="argo-cervello").start()

    def _run(self):
        try:
            esito, risultato = self.sig_fine, self.fn(self._stato)
        except Exception as e:
            esito, risultato = self.sig_errore, str(e)
        try:
            esito.emit(risultato)
        except RuntimeError:  # dialogo già chiuso: il risultato non serve più
            pass

    def _stato(self, testo):
        try:
            self.sig_stato.emit(testo)
        except RuntimeError:
            pass


def _combo(valori, attuale=""):
    c = QComboBox()
    c.addItem("")
    c.addItems(valori)
    if attuale:
        i = c.findText(attuale)
        c.setCurrentIndex(i if i >= 0 else 0)
    return c


# ---------------------------------------------------------------- aziende
class DialogoAzienda(QDialog):
    def __init__(self, azienda=None, parent=None, nome=""):
        super().__init__(parent)
        a = dict(azienda or {})
        self.id = a.get("id")
        self.fonte = a.get("fonte") or "manuale"
        self.setWindowTitle(tr('Azienda') if self.id else tr('Nuova azienda'))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.e_nome = QLineEdit(a.get("nome") or nome)
        self.e_sito = QLineEdit(a.get("sito", ""))
        self.e_sito.setPlaceholderText(tr('facoltativo · aiuta a distinguere aziende con lo stesso nome'))
        self.c_settore = _combo(sc.SETTORI, a.get("settore", ""))
        self.c_dimensione = _combo(sc.DIMENSIONI, a.get("dimensione", ""))
        self.c_tipo = _combo(sc.TIPI_ATTIVITA, a.get("tipo_attivita", ""))
        self.c_area = _combo(sc.AREE_GEOGRAFICHE, a.get("area", ""))
        self.e_note = QPlainTextEdit(a.get("note", ""))
        self.e_note.setFixedHeight(70)
        self.e_note.setPlaceholderText(tr("Cosa fa l'azienda: prodotti, servizi, mercati. Solo fatti di lavoro."))
        for etichetta, w in (("Nome", self.e_nome), ("Sito", self.e_sito), ("Settore", self.c_settore),
                             ("Dimensione", self.c_dimensione), ("Tipo di attività", self.c_tipo),
                             ("Area geografica", self.c_area), ("Note", self.e_note)):
            form.addRow(etichetta, w)
        lay.addLayout(form)
        riga = QHBoxLayout()
        self.b_web = QPushButton(tr('🔎 Cataloga dal web'))
        self.b_web.setToolTip(tr("Usa la scheda pubblica della pagina Clienti se c'è già, altrimenti la ricerca web; il modello sceglie le categorie. Controllale prima di salvare."))
        self.b_web.clicked.connect(self.cataloga)
        riga.addWidget(self.b_web)
        self.l_stato = QLabel("")
        self.l_stato.setProperty("ruolo", "tenue")
        self.l_stato.setWordWrap(True)
        riga.addWidget(self.l_stato, 1)
        lay.addLayout(riga)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.salva)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.salvata = None

    def cataloga(self):
        nome = self.e_nome.text().strip()
        if not nome:
            QMessageBox.information(self, tr('Nome'), tr("Scrivi prima il nome dell'azienda."))
            return
        sito = self.e_sito.text().strip()
        self.b_web.setEnabled(False)
        self._lavoro = _Lavoro(lambda stato: sc.cataloga(nome, sito, stato=stato), self)
        self._lavoro.sig_stato.connect(self.l_stato.setText)
        self._lavoro.sig_fine.connect(self._compila)
        self._lavoro.sig_errore.connect(self._errore)
        self._lavoro.start()

    def _compila(self, dati):
        self.b_web.setEnabled(True)
        for chiave, combo in (("settore", self.c_settore), ("dimensione", self.c_dimensione),
                              ("tipo_attivita", self.c_tipo), ("area", self.c_area)):
            i = combo.findText(dati.get(chiave, ""))
            if i >= 0:
                combo.setCurrentIndex(i)
        if dati.get("sito") and not self.e_sito.text().strip():
            self.e_sito.setText(dati["sito"])
        if dati.get("note"):
            self.e_note.setPlainText(dati["note"])
        self.fonte = "ricerca"
        self.l_stato.setText(tr('Categorie proposte dalle fonti pubbliche: controllale prima di salvare.'))

    def _errore(self, testo):
        self.b_web.setEnabled(True)
        self.l_stato.setText("")
        QMessageBox.warning(self, tr('Catalogazione'), testo)

    def salva(self):
        try:
            self.salvata = sc.salva_azienda({
                "id": self.id, "nome": self.e_nome.text(), "sito": self.e_sito.text(),
                "settore": self.c_settore.currentText(), "dimensione": self.c_dimensione.currentText(),
                "tipo_attivita": self.c_tipo.currentText(), "area": self.c_area.currentText(),
                "note": self.e_note.toPlainText(), "fonte": self.fonte})
        except ValueError as e:
            QMessageBox.information(self, tr('Azienda'), str(e))
            return
        self.accept()


# ---------------------------------------------------------------- funzioni
class DialogoFunzione(QDialog):
    def __init__(self, funzione=None, parent=None):
        super().__init__(parent)
        f = dict(funzione or {})
        self.id = f.get("id")
        self.setWindowTitle(tr('Funzione'))
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        nota = QLabel(tr('Le persone si catalogano per <b>funzione</b>, non per identità: <b>niente nomi</b>.'))
        nota.setWordWrap(True)
        lay.addWidget(nota)
        form = QFormLayout()
        self.e_ruolo = QLineEdit(f.get("ruolo", ""))
        self.e_ruolo.setPlaceholderText(tr('es. Responsabile IT, Buyer, Titolare, Responsabile di produzione'))
        self.c_area = _combo(sc.AREE_FUNZIONE, f.get("area", ""))
        self.c_livello = _combo(sc.LIVELLI, f.get("livello", ""))
        form.addRow(tr('Ruolo'), self.e_ruolo)
        form.addRow(tr('Area'), self.c_area)
        form.addRow(tr('Livello'), self.c_livello)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.salva)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.salvata = None

    def salva(self):
        try:
            self.salvata = sc.salva_funzione({"id": self.id, "ruolo": self.e_ruolo.text(),
                                              "area": self.c_area.currentText(),
                                              "livello": self.c_livello.currentText()})
        except ValueError as e:
            QMessageBox.information(self, tr('Funzione'), str(e))
            return
        self.accept()


# ---------------------------------------------------------------- suggerimenti prima dell'incontro
class PannelloSuggerimenti(QWidget):
    """Domande e temi dagli incontri simili della Base. Con scelta=True mostra anche azienda e funzioni da scegliere
    (scheda «Prepara»); altrimenti usa quelle passate (dialogo «Con chi stai parlando?»)."""

    def __init__(self, azienda_id="", funzioni_id=(), scelta=False, parent=None):
        super().__init__(parent)
        self.azienda_id, self.funzioni_id = azienda_id, list(funzioni_id or [])
        self._lavoro = None
        self._testo = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.c_azienda = self.l_funzioni = None
        if scelta:
            form = QFormLayout()
            self.c_azienda = QComboBox()
            form.addRow(tr('Azienda'), self.c_azienda)
            self.l_funzioni = QListWidget()
            self.l_funzioni.setSelectionMode(QAbstractItemView.MultiSelection)
            self.l_funzioni.setFixedHeight(96)
            form.addRow(tr('Persone (funzioni)'), self.l_funzioni)
            lay.addLayout(form)
            self.riempi()
        else:
            l_ctx = QLabel(tr('<b>Contesto</b>: {contesto}',
                              contesto=sug.descrivi_contesto(azienda_id, funzioni_id) or tr('non indicato')))
            l_ctx.setWordWrap(True)
            lay.addWidget(l_ctx)
        riga = QHBoxLayout()
        self.e_argomento = QLineEdit()
        self.e_argomento.setPlaceholderText(tr("Argomento previsto (facoltativo), per esempio «migrazione al cloud»"))
        self.e_argomento.returnPressed.connect(lambda: self.suggerisci(False))
        riga.addWidget(self.e_argomento, 1)
        self.b_suggerisci = QPushButton(tr('💡 Suggerisci'))
        self.b_suggerisci.setToolTip(tr('Domande, temi e cosa è emerso negli incontri simili della Base. Senza modello, subito.'))
        self.b_suggerisci.clicked.connect(lambda: self.suggerisci(False))
        riga.addWidget(self.b_suggerisci)
        self.b_modello = QPushButton(tr('✨ Scaletta su misura'))
        self.b_modello.setToolTip(tr('Il modello locale riordina i suggerimenti in una scaletta per questo incontro. Usa solo la Base anonima.'))
        self.b_modello.clicked.connect(lambda: self.suggerisci(True))
        riga.addWidget(self.b_modello)
        lay.addLayout(riga)
        self.v = QTextBrowser()
        self.v.setOpenExternalLinks(False)
        lay.addWidget(self.v, 1)
        riga = QHBoxLayout()
        self.l_stato = QLabel("")
        self.l_stato.setProperty("ruolo", "tenue")
        self.l_stato.setWordWrap(True)
        riga.addWidget(self.l_stato, 1)
        self.b_copia = QPushButton(tr('Copia'))
        self.b_copia.setEnabled(False)
        self.b_copia.clicked.connect(lambda: QApplication.clipboard().setText(self._testo))
        riga.addWidget(self.b_copia)
        lay.addLayout(riga)
        if not base.voci():
            self.v.setMarkdown(tr("La Base è ancora vuota: distilla qualche incontro (scheda Incontri › ✨ Distilla) e "
                                  "qui troverai domande e temi dagli incontri simili."))

    def riempi(self):
        if self.c_azienda is None:
            return
        attuale = self.c_azienda.currentData()
        self.c_azienda.clear()
        self.c_azienda.addItem(tr('— qualsiasi —'), "")
        for a in sc.aziende():
            self.c_azienda.addItem(sc.descrivi_azienda(a), a["id"])
        i = self.c_azienda.findData(attuale)
        self.c_azienda.setCurrentIndex(i if i >= 0 else 0)
        scelte = {self.l_funzioni.item(n).data(Qt.UserRole) for n in range(self.l_funzioni.count())
                  if self.l_funzioni.item(n).isSelected()}
        self.l_funzioni.clear()
        for f in sc.funzioni():
            voce = QListWidgetItem(sc.descrivi_funzione(f))
            voce.setData(Qt.UserRole, f["id"])
            self.l_funzioni.addItem(voce)
            voce.setSelected(f["id"] in scelte)

    def _scelta(self):
        if self.c_azienda is None:
            return self.azienda_id, self.funzioni_id
        return (self.c_azienda.currentData() or "",
                [i.data(Qt.UserRole) for i in self.l_funzioni.selectedItems()])

    def suggerisci(self, con_modello):
        if self._lavoro:
            return
        azienda_id, funzioni_id = self._scelta()
        argomento = self.e_argomento.text().strip()
        if not azienda_id and not funzioni_id and not argomento:
            self.l_stato.setText(tr("Scegli l'azienda o almeno una funzione, oppure scrivi l'argomento."))
            return
        for b in (self.b_suggerisci, self.b_modello):
            b.setEnabled(False)
        self.l_stato.setText(tr('Il modello prepara la scaletta…') if con_modello else tr('Cerco gli incontri simili…'))
        self._lavoro = _Lavoro(lambda _stato: sug.prepara(azienda_id, funzioni_id, argomento, con_modello), self)
        self._lavoro.sig_fine.connect(self._mostra)
        self._lavoro.sig_errore.connect(self._errore)
        self._lavoro.start()

    def _fine(self):
        self._lavoro = None
        for b in (self.b_suggerisci, self.b_modello):
            b.setEnabled(True)

    def _mostra(self, esito):
        self._fine()
        suggerimenti, trovati = esito
        if not trovati:
            self._testo = ""
            self.b_copia.setEnabled(False)
            self.v.setMarkdown(tr("Nella Base non ci sono ancora incontri simili a questo. Prova con meno criteri "
                                  "(solo l'azienda o solo una funzione) o con un argomento."))
            self.l_stato.setText("")
            return
        titoli = {"domande": tr('Domande da fare'), "temi": tr('Temi da toccare'),
                  "emerso": tr('Cosa è emerso in casi simili')}
        self._testo = sug.in_markdown(suggerimenti, trovati, titoli)
        fonti = "\n".join(f"- {v.get('mese', '')} · {base.descrivi(v) or tr('contesto non indicato')}"
                           for _p, v in trovati)
        self.v.setMarkdown(self._testo + "\n\n---\n" + tr('**Dagli incontri simili della Base ({n})**', n=len(trovati))
                           + "\n\n" + fonti)
        self.b_copia.setEnabled(bool(self._testo))
        self.l_stato.setText(tr('Suggerimenti dalla Base anonima: niente è uscito da questo computer.'))

    def _errore(self, testo):
        self._fine()
        self.l_stato.setText("")
        QMessageBox.warning(self, tr('Suggerimenti'), testo)


class DialogoSuggerimenti(QDialog):
    def __init__(self, azienda_id, funzioni_id, titolo="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Suggerimenti per «{titolo}»', titolo=titolo) if titolo else tr('Suggerimenti'))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        self.pannello = PannelloSuggerimenti(azienda_id, funzioni_id, parent=self)
        lay.addWidget(self.pannello, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.pannello.suggerisci(False)


# ---------------------------------------------------------------- «Con chi stai parlando?»
class DialogoInterlocutori(QDialog):
    """Azienda e funzioni delle persone di un incontro. scelta() -> (id azienda, [id funzioni])."""
    NUOVA = "__nuova__"

    def __init__(self, titolo="", esistente=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Con chi stai parlando?'))
        self.setMinimumWidth(540)
        e = dict(esistente or {})
        lay = QVBoxLayout(self)
        testa = QLabel(tr('<b>{titolo}</b><br>', titolo=titolo) if titolo else "")
        testa.setText(testa.text() + "Serve al Secondo cervello per collegare l'incontro ad azienda e funzioni. "
                      "Puoi saltare e completarlo dopo.")
        testa.setWordWrap(True)
        lay.addWidget(testa)
        form = QFormLayout()
        riga_az = QHBoxLayout()
        self.c_azienda = QComboBox()
        self.c_azienda.setEditable(False)
        riga_az.addWidget(self.c_azienda, 1)
        form.addRow(tr('Azienda'), riga_az)
        lay.addLayout(form)
        self._riempi_aziende(e.get("azienda", ""))
        self.c_azienda.activated.connect(self._azienda_scelta)

        lay.addWidget(QLabel(tr('Persone, per funzione (niente nomi):')))
        self.l_funzioni = QListWidget()
        self.l_funzioni.setFixedHeight(110)
        lay.addWidget(self.l_funzioni)
        for id_f in e.get("funzioni", []):
            f = sc.funzione(id_f)
            if f:
                self._aggiungi_voce(f)
        riga_f = QHBoxLayout()
        self.c_funzione = QComboBox()
        self._riempi_funzioni()
        riga_f.addWidget(self.c_funzione, 1)
        b_agg = QPushButton(tr('Aggiungi'))
        b_agg.clicked.connect(self._aggiungi_scelta)
        riga_f.addWidget(b_agg)
        b_nuova = QPushButton(tr('Nuova funzione…'))
        b_nuova.clicked.connect(self._nuova_funzione)
        riga_f.addWidget(b_nuova)
        b_togli = QPushButton(tr('Togli'))
        b_togli.clicked.connect(lambda: [self.l_funzioni.takeItem(self.l_funzioni.row(i))
                                         for i in self.l_funzioni.selectedItems()])
        riga_f.addWidget(b_togli)
        lay.addLayout(riga_f)

        self._titolo = titolo
        bb = QDialogButtonBox()
        self.b_sugg = bb.addButton(tr('💡 Suggerimenti'), QDialogButtonBox.ActionRole)
        self.b_sugg.setToolTip(tr("Domande e temi dagli incontri simili della Base, per prepararti all'incontro"))
        self.b_sugg.setEnabled(bool(base.voci()))
        self.b_sugg.clicked.connect(self._suggerimenti)
        bb.addButton(tr('Salta'), QDialogButtonBox.RejectRole)
        bb.addButton(tr('Salva'), QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _riempi_aziende(self, attuale=""):
        self.c_azienda.clear()
        self.c_azienda.addItem(tr('— nessuna o non lo so —'), "")
        for a in sc.aziende():
            self.c_azienda.addItem(sc.descrivi_azienda(a), a["id"])
        self.c_azienda.addItem(tr('➕ Nuova azienda…'), self.NUOVA)
        i = self.c_azienda.findData(attuale)
        self.c_azienda.setCurrentIndex(i if i >= 0 else 0)

    def _azienda_scelta(self, _indice):
        if self.c_azienda.currentData() != self.NUOVA:
            return
        d = DialogoAzienda(parent=self)
        self._riempi_aziende(d.salvata["id"] if d.exec() == QDialog.Accepted and d.salvata else "")

    def _riempi_funzioni(self):
        self.c_funzione.clear()
        for f in sc.funzioni():
            self.c_funzione.addItem(sc.descrivi_funzione(f), f["id"])

    def _aggiungi_voce(self, f):
        if any(self.l_funzioni.item(n).data(Qt.UserRole) == f["id"] for n in range(self.l_funzioni.count())):
            return
        voce = QListWidgetItem(sc.descrivi_funzione(f))
        voce.setData(Qt.UserRole, f["id"])
        self.l_funzioni.addItem(voce)

    def _aggiungi_scelta(self):
        f = sc.funzione(self.c_funzione.currentData())
        if f:
            self._aggiungi_voce(f)

    def _nuova_funzione(self):
        d = DialogoFunzione(parent=self)
        if d.exec() == QDialog.Accepted and d.salvata:
            self._riempi_funzioni()
            self._aggiungi_voce(d.salvata)

    def _suggerimenti(self):
        azienda_id, funzioni_id = self.scelta()
        if not azienda_id and not funzioni_id:
            QMessageBox.information(self, tr('Suggerimenti'), tr("Scegli prima l'azienda o almeno una funzione."))
            return
        d = DialogoSuggerimenti(azienda_id, funzioni_id, self._titolo, self.parent() or self)
        d.setModal(False)
        d.show()  # resta aperto accanto, anche dopo «Salva»

    def scelta(self):
        return (self.c_azienda.currentData() if self.c_azienda.currentData() != self.NUOVA else "",
                [self.l_funzioni.item(n).data(Qt.UserRole) for n in range(self.l_funzioni.count())])


def chiedi(parent, titolo="", esistente=None):
    """Mostra il dialogo; ritorna (azienda, funzioni) o None se l'utente salta."""
    d = DialogoInterlocutori(titolo, esistente, parent)
    if d.exec() != QDialog.Accepted:
        return None
    return d.scelta()


def collega(parent, riferimento, titolo, origine):
    """Dal menu di un incontro o di un file: apre il dialogo già compilato e salva. True se salvato."""
    esistente = sc.interlocutori_di(riferimento)
    scelta = chiedi(parent, titolo, esistente)
    if scelta is None:
        return False
    sc.salva_interlocutori(riferimento, titolo, origine, *scelta, id_=(esistente or {}).get("id"))
    return True


# ---------------------------------------------------------------- pagina
def _tabella(colonne):
    t = QTableWidget(0, len(colonne))
    t.setHorizontalHeaderLabels(colonne)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setShowGrid(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def _riga(t, valori, id_):
    r = t.rowCount()
    t.insertRow(r)
    for c, v in enumerate(valori):
        it = QTableWidgetItem(str(v or ""))
        if c == 0:
            it.setData(Qt.UserRole, id_)
        t.setItem(r, c, it)


def _id_selezionato(t):
    r = t.currentRow()
    return t.item(r, 0).data(Qt.UserRole) if r >= 0 and t.item(r, 0) else None


class PaginaCervello(QWidget):
    cambiato = Signal()  # acceso/spento o Base cambiata: la barra in basso si aggiorna

    def __init__(self, finestra=None, parent=None):
        super().__init__(parent)
        self.finestra = finestra
        lay = QVBoxLayout(self)
        testa = QFrame()
        testa.setProperty("ruolo", "scheda")
        tl = QVBoxLayout(testa)
        self.l_spiega = QLabel(SPIEGAZIONE)
        self.l_spiega.setWordWrap(True)
        self.l_spiega.setTextFormat(Qt.RichText)
        tl.addWidget(self.l_spiega)
        riga = QHBoxLayout()
        self.l_stato = QLabel("")
        riga.addWidget(self.l_stato, 1)
        self.b_interruttore = QPushButton("")
        self.b_interruttore.clicked.connect(self.cambia)
        riga.addWidget(self.b_interruttore)
        tl.addLayout(riga)
        lay.addWidget(testa)

        self.schede = QTabWidget()
        lay.addWidget(self.schede, 1)
        # incontri
        w = QWidget()
        wl = QVBoxLayout(w)
        self.t_incontri = _tabella(["Data", "Titolo", "Da", "Azienda", "Persone (funzioni)", "Base"])
        self.t_incontri.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_incontri.doubleClicked.connect(self.modifica_incontro)
        wl.addWidget(self.t_incontri, 1)
        riga = QHBoxLayout()
        self.l_lavoro = QLabel("")
        self.l_lavoro.setProperty("ruolo", "tenue")
        self.l_lavoro.setWordWrap(True)
        riga.addWidget(self.l_lavoro, 1)
        self.b_distilla = QPushButton(tr('✨ Distilla'))
        self.b_distilla.setToolTip(tr('Estrae i fatti di lavoro dagli incontri selezionati e li salva, anonimi, nella Base. Solo con il modello su questo computer.'))
        self.b_distilla.clicked.connect(lambda: self.distilla(False))
        self.b_nuovi = QPushButton(tr('✨ Distilla i nuovi'))
        self.b_nuovi.setToolTip(tr('Tutti gli incontri catalogati non ancora nella Base'))
        self.b_nuovi.clicked.connect(lambda: self.distilla(True))
        self.b_ferma = QPushButton(tr('■ Ferma'))
        self.b_ferma.hide()
        self.b_ferma.clicked.connect(self.ferma)
        for b in (self.b_distilla, self.b_nuovi, self.b_ferma):
            riga.addWidget(b)
        for testo, azione in (("Modifica…", self.modifica_incontro), ("Togli la scheda", self.togli_incontro)):
            b = QPushButton(testo)
            b.clicked.connect(azione)
            riga.addWidget(b)
        wl.addLayout(riga)
        self.schede.addTab(w, tr('Incontri'))
        # base
        w = QWidget()
        wl = QVBoxLayout(w)
        nota = QLabel(tr("Solo fatti di lavoro, anonimi: categoria dell'azienda, funzioni, mese. Nessun nome e nessun collegamento all'incontro di origine. Puoi correggere o eliminare ogni voce."))
        nota.setProperty("ruolo", "tenue")
        nota.setWordWrap(True)
        wl.addWidget(nota)
        div = QSplitter(Qt.Vertical)
        self.t_base = _tabella(["Mese", "Contesto", "Sintesi"])
        self.t_base.itemSelectionChanged.connect(self._mostra_voce)
        self.t_base.doubleClicked.connect(self.modifica_voce)
        div.addWidget(self.t_base)
        self.v_base = QTextBrowser()
        div.addWidget(self.v_base)
        div.setSizes([260, 240])
        wl.addWidget(div, 1)
        wl.addLayout(self._comandi([("Modifica…", self.modifica_voce), ("Elimina", self.elimina_voce)]))
        self.schede.addTab(w, tr('Base'))
        self._scheda_base = w
        # prepara
        w = QWidget()
        wl = QVBoxLayout(w)
        nota = QLabel(tr("Prima di un incontro: scegli il tipo di azienda e le funzioni delle persone, e Argo propone "
                         "domande e temi dagli incontri simili della Base."))
        nota.setProperty("ruolo", "tenue")
        nota.setWordWrap(True)
        wl.addWidget(nota)
        self.p_prepara = PannelloSuggerimenti(scelta=True, parent=w)
        wl.addWidget(self.p_prepara, 1)
        self.schede.addTab(w, tr('💡 Prepara'))
        # aziende
        w = QWidget()
        wl = QVBoxLayout(w)
        self.t_aziende = _tabella(["Nome", "Settore", "Dimensione", "Tipo di attività", "Area", "Incontri"])
        self.t_aziende.doubleClicked.connect(self.modifica_azienda)
        wl.addWidget(self.t_aziende, 1)
        wl.addLayout(self._comandi([("➕ Nuova…", self.nuova_azienda), ("Modifica…", self.modifica_azienda),
                                    ("Elimina", self.elimina_azienda)]))
        self.schede.addTab(w, tr('Aziende'))
        # funzioni
        w = QWidget()
        wl = QVBoxLayout(w)
        self.t_funzioni = _tabella(["Ruolo", "Area", "Livello", "Incontri"])
        self.t_funzioni.doubleClicked.connect(self.modifica_funzione)
        wl.addWidget(self.t_funzioni, 1)
        wl.addLayout(self._comandi([("➕ Nuova…", self.nuova_funzione), ("Modifica…", self.modifica_funzione),
                                    ("Elimina", self.elimina_funzione)]))
        self.schede.addTab(w, tr('Funzioni'))
        self.aggiorna()

    def _comandi(self, voci):
        riga = QHBoxLayout()
        riga.addStretch()
        for testo, azione in voci:
            b = QPushButton(testo)
            b.clicked.connect(azione)
            riga.addWidget(b)
        return riga

    # -- stato
    def aggiorna(self):
        acceso, vietato = sc.attivo(), sc.vietato()
        if vietato:
            self.l_stato.setText(tr('🔒 Disattivato dai criteri della tua azienda.'))
        else:
            self.l_stato.setText(tr("🟢 Attivo: ti chiedo con chi parli all'inizio di ogni registrazione.")
                                 if acceso else tr('⚪ Spento.'))
        self.b_interruttore.setText(tr('Spegni…') if acceso else tr('Attiva il Secondo cervello'))
        self.b_interruttore.setEnabled(not vietato)
        self.schede.setEnabled(acceso)
        uso_az, uso_f = {}, {}
        incontri = sc.incontri()
        for i in incontri:
            uso_az[i.get("azienda")] = uso_az.get(i.get("azienda"), 0) + 1
            for f in i.get("funzioni", []):
                uso_f[f] = uso_f.get(f, 0) + 1
        aziende = {a["id"]: a for a in sc.aziende()}
        funzioni = {f["id"]: f for f in sc.funzioni()}
        self.t_incontri.setRowCount(0)
        for i in incontri:
            _riga(self.t_incontri, [i.get("quando", "")[:16].replace("T", " "), i.get("titolo") or
                                    Path(i.get("riferimento", "")).name, sc.ORIGINI.get(i.get("origine"), ""),
                                    (aziende.get(i.get("azienda")) or {}).get("nome", ""),
                                    "; ".join(sc.descrivi_funzione(funzioni.get(f)) for f in i.get("funzioni", [])
                                              if funzioni.get(f)),
                                    "✓" if i.get("base") and base.voce(i["base"]) else ""], i["id"])
        self.t_aziende.setRowCount(0)
        for a in aziende.values():
            _riga(self.t_aziende, [a.get("nome"), a.get("settore"), a.get("dimensione"), a.get("tipo_attivita"),
                                   a.get("area"), uso_az.get(a["id"], 0)], a["id"])
        self.t_funzioni.setRowCount(0)
        for f in funzioni.values():
            _riga(self.t_funzioni, [f.get("ruolo"), f.get("area"), f.get("livello"), uso_f.get(f["id"], 0)], f["id"])
        self.t_base.setRowCount(0)
        for v in sorted(base.voci(), key=lambda x: x.get("mese", ""), reverse=True):
            _riga(self.t_base, [v.get("mese"), base.descrivi(v), (v.get("contenuti") or {}).get("sintesi", "")], v["id"])
        self.v_base.clear()
        if hasattr(self, "p_prepara"):
            self.p_prepara.riempi()
        self.schede.setTabText(self.schede.indexOf(self._scheda_base), tr('Base ({rowcount})', rowcount=self.t_base.rowCount()))
        for t in (self.t_incontri, self.t_aziende, self.t_funzioni, self.t_base):
            t.resizeColumnsToContents()
        self.cambiato.emit()
        self.t_base.setColumnWidth(2, 600)

    def cambia(self):
        if not sc.attivo():
            sc.imposta(True)
        else:
            box = QMessageBox(QMessageBox.Question, tr('Spegnere il Secondo cervello?'),
                              tr('Spento, Argo non chiede più con chi parli. Cosa faccio dei cataloghi, delle schede degli incontri e della Base? Gli incontri e le trascrizioni restano dove sono.'),
                              parent=self)
            b_tieni = box.addButton(tr('Spegni e tieni i dati'), QMessageBox.AcceptRole)
            b_canc = box.addButton(tr('Spegni e cancella tutto'), QMessageBox.DestructiveRole)
            box.addButton(tr('Annulla'), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_tieni:
                sc.imposta(False)
            elif box.clickedButton() is b_canc:
                sc.imposta(False)
                sc.svuota()
        self.aggiorna()

    # -- incontri
    def modifica_incontro(self, *_):
        id_ = _id_selezionato(self.t_incontri)
        voce = sc.interlocutori_di(id_) if id_ else None
        if voce:
            scelta = chiedi(self, voce.get("titolo", ""), voce)
            if scelta is not None:
                sc.salva_interlocutori(voce.get("riferimento"), voce.get("titolo"), voce.get("origine"), *scelta,
                                       id_=id_)
            self.aggiorna()

    def togli_incontro(self):
        id_ = _id_selezionato(self.t_incontri)
        if id_ and QMessageBox.question(self, tr('Togliere la scheda?'), tr("Tolgo solo azienda e funzioni collegate a questo incontro; l'incontro resta.")) == QMessageBox.Yes:
            sc.elimina_interlocutori(id_)
            self.aggiorna()

    # -- distillazione
    def distilla(self, nuovi):
        if getattr(self, "_lavoro", None):
            return
        if nuovi:
            schede = [i for i in sc.incontri() if not (i.get("base") and base.voce(i["base"]))]
        else:
            righe = sorted({x.row() for x in self.t_incontri.selectedIndexes()})
            ids = [self.t_incontri.item(r, 0).data(Qt.UserRole) for r in righe if self.t_incontri.item(r, 0)]
            schede = [sc.interlocutori_di(i) for i in ids if sc.interlocutori_di(i)]
        if not schede:
            QMessageBox.information(self, tr('Distilla'), tr('Nessun incontro da distillare.') if nuovi else
                                    tr('Seleziona uno o più incontri.'))
            return
        rifare = [s for s in schede if s.get("base") and base.voce(s["base"])]
        if rifare and QMessageBox.question(self, tr('Distillare di nuovo?'), tr('{len} incontri sono già nella Base: la voce vecchia viene sostituita. Procedo?', len=len(rifare))) != QMessageBox.Yes:
            return
        lavoro = _Lavoro(lambda stato: self._distilla_tutti(schede, stato), self)
        self._lavoro = lavoro
        lavoro.sig_stato.connect(self.l_lavoro.setText)
        lavoro.sig_fine.connect(self._fine_distilla)
        lavoro.sig_errore.connect(self._fine_distilla)
        for b in (self.b_distilla, self.b_nuovi):
            b.setEnabled(False)
        self.b_ferma.show()
        lavoro.start()

    def _distilla_tutti(self, schede, stato):
        fatti, errori = 0, []
        with veglia.tieni("secondo cervello"):
            for n, s in enumerate(schede, 1):
                if self._lavoro.fermato:
                    break
                prefisso = f"[{n} di {len(schede)}] " if len(schede) > 1 else ""
                try:
                    base.distilla(s, stato=lambda testo: stato(prefisso + testo), stop=lambda: self._lavoro.fermato)
                    fatti += 1
                except Exception as e:
                    errori.append(f"«{s.get('titolo') or 'incontro'}»: {e}")
        esito = f"Nella Base: {fatti} incontri." if fatti else "Nessun incontro aggiunto alla Base."
        return esito + ("\n" + "\n".join(errori) if errori else "")

    def _fine_distilla(self, esito):
        self._lavoro = None
        for b in (self.b_distilla, self.b_nuovi):
            b.setEnabled(True)
        self.b_ferma.hide()
        self.l_lavoro.setText(str(esito).split("\n")[0])
        if "\n" in str(esito):
            QMessageBox.information(self, tr('Distilla'), str(esito))
        self.aggiorna()

    def ferma(self):
        if getattr(self, "_lavoro", None):
            self._lavoro.fermato = True
            self.l_lavoro.setText(tr('Mi fermo dopo il passo in corso…'))

    # -- base
    def _mostra_voce(self):
        v = base.voce(_id_selezionato(self.t_base))
        self.v_base.setMarkdown(f"*{v.get('mese', '')} · {base.descrivi(v)}*\n\n" + base.in_testo(v) if v else "")

    def modifica_voce(self, *_):
        v = base.voce(_id_selezionato(self.t_base))
        if not v:
            return
        d = QDialog(self)
        d.setWindowTitle(tr('Voce della Base'))
        d.resize(640, 520)
        lay = QVBoxLayout(d)
        nota = QLabel(tr("Correggi o togli le voci; mantieni i titoli «## …» e i trattini. Al salvataggio Argo ripassa l'anonimizzazione e il filtro etico."))
        nota.setWordWrap(True)
        lay.addWidget(nota)
        e = QPlainTextEdit(base.in_testo(v))
        lay.addWidget(e, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() == QDialog.Accepted:
            base.modifica_voce(v["id"], e.toPlainText())
            self.aggiorna()

    def elimina_voce(self):
        id_ = _id_selezionato(self.t_base)
        if id_ and QMessageBox.question(self, tr('Eliminare la voce?'), tr("La voce sparisce dalla Base. L'incontro di origine resta e si può distillare di nuovo.")) == QMessageBox.Yes:
            base.elimina_voce(id_)
            self.aggiorna()

    # -- aziende
    def nuova_azienda(self):
        if DialogoAzienda(parent=self).exec() == QDialog.Accepted:
            self.aggiorna()

    def modifica_azienda(self, *_):
        a = sc.azienda(_id_selezionato(self.t_aziende))
        if a and DialogoAzienda(a, self).exec() == QDialog.Accepted:
            self.aggiorna()

    def elimina_azienda(self):
        a = sc.azienda(_id_selezionato(self.t_aziende))
        if a and QMessageBox.question(self, tr("Eliminare l'azienda?"), tr('Elimino «{get}» dal catalogo; gli incontri collegati restano senza azienda.', get=a.get('nome'))) == QMessageBox.Yes:
            sc.elimina_azienda(a["id"])
            self.aggiorna()

    # -- funzioni
    def nuova_funzione(self):
        if DialogoFunzione(parent=self).exec() == QDialog.Accepted:
            self.aggiorna()

    def modifica_funzione(self, *_):
        f = sc.funzione(_id_selezionato(self.t_funzioni))
        if f and DialogoFunzione(f, self).exec() == QDialog.Accepted:
            self.aggiorna()

    def elimina_funzione(self):
        f = sc.funzione(_id_selezionato(self.t_funzioni))
        if f and QMessageBox.question(self, tr('Eliminare la funzione?'), tr('Elimino «{descrivi_funzione}»; gli incontri collegati la perdono.', descrivi_funzione=sc.descrivi_funzione(f))) == QMessageBox.Yes:
            sc.elimina_funzione(f["id"])
            self.aggiorna()
