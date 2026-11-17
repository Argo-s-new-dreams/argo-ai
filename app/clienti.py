"""clienti.py - pagina Clienti: Dynamics 365 Sales al centro del lavoro presales.

Scheda «Cliente»
  Cerca l'account in Dynamics (nome, sito o dominio). Se non c'è: scheda pubblica con le regole di
  Client Intel Scout (scheda_cliente.py, Ollama Web Search + modello locale) e proposta di account da confermare.
Scheda «Dalla call»
  Una call (incontro dall'iPhone, trascrizione del computer) + invitati dal calendario: per ogni partecipante Argo
  propone l'azienda cercando prima nel CRM (dominio email, azienda dal biglietto, nome); poi relazione, contatti e
  note in Dynamics, e task: ogni volta si sceglie se in Planner o come attività di Dynamics.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget,
)

import chiamate
import crm_dynamics as crm
import crm_incontri
import ponte as pt
import relazione_incontro as rel
import ricerca_web as web
import scheda_cliente as scheda

DA_DECIDERE, INTERNO, NUOVO, ALTRA = "decidere", "interno", "nuovo", "altra"
NOMI_PROPRI = ("io", "me", "io stesso", "me stesso")


def _sono_io(nome):
    return (nome or "").strip().lower() in NOMI_PROPRI


class Lavoro(QObject):
    """Lavoro in un thread «daemon» con stato, avanzamento e risultato."""
    sig_stato = Signal(str)
    sig_avanzamento = Signal(int)
    sig_fine = Signal(object)
    sig_errore = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._stop = False

    def ferma(self):
        self._stop = True

    def fermato(self):
        return self._stop

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="argo-clienti").start()

    def _run(self):
        try:
            self.sig_fine.emit(self.fn(self))
        except Exception as e:
            self.sig_errore.emit(str(e))


def _testo(v):
    return "" if v is None else str(v)


# =============================================================== dialoghi
class DialogoCandidati(QDialog):
    """Omonimia (regola di Client Intel Scout): l'utente sceglie l'azienda giusta."""

    def __init__(self, candidati, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Più aziende con questo nome")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Ho trovato aziende diverse con lo stesso nome. Quale cerchi?"))
        self.lista = QListWidget()
        for c in candidati:
            it = QListWidgetItem(" · ".join(x for x in (c.get("nome"), c.get("sede"), c.get("sito"), c.get("descrizione")) if x))
            it.setData(Qt.UserRole, c)
            self.lista.addItem(it)
        self.lista.setCurrentRow(0)
        lay.addWidget(self.lista)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def scelta(self):
        it = self.lista.currentItem()
        return it.data(Qt.UserRole) if it else None


class DialogoAccount(QDialog):
    """Account proposto dalla scheda pubblica: si crea solo dopo la conferma."""
    CAMPI = [("ragione_sociale", "Ragione sociale *"), ("sito", "Sito"), ("indirizzo", "Indirizzo"), ("cap", "CAP"),
             ("citta", "Città"), ("provincia", "Provincia"), ("nazione", "Nazione"), ("telefono", "Telefono"),
             ("email", "Email"), ("dipendenti", "Dipendenti"), ("settore", "Settore"), ("descrizione", "Descrizione")]

    def __init__(self, proposta, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuovo account in Dynamics")
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        nota = QLabel("Dati presi dalla scheda pubblica: controllali prima di creare l'account.")
        nota.setWordWrap(True)
        lay.addWidget(nota)
        f = QFormLayout()
        self.e = {}
        for chiave, etichetta in self.CAMPI:
            valore = proposta.get(chiave)
            if chiave == "descrizione":
                pezzi = [proposta.get("descrizione"), proposta.get("settore") and f"Settore: {proposta['settore']}",
                         proposta.get("gruppo") and f"Gruppo: {proposta['gruppo']}",
                         proposta.get("partita_iva") and f"P.IVA: {proposta['partita_iva']}",
                         proposta.get("fatturato_euro") and f"Fatturato: {proposta['fatturato_euro']:,.0f} € "
                         f"({proposta.get('fatturato_anno', 's.d.')})"]
                valore = "\n".join(p for p in pezzi if p)
            self.e[chiave] = QLineEdit(_testo(valore))
            f.addRow(etichetta + ":", self.e[chiave])
        lay.addLayout(f)
        self.cb_nota = QCheckBox("Allega la scheda pubblica come nota sull'account")
        self.cb_nota.setChecked(True)
        lay.addWidget(self.cb_nota)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Crea account")
        b.accepted.connect(self._ok)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def _ok(self):
        if not self.e["ragione_sociale"].text().strip():
            QMessageBox.warning(self, "Manca la ragione sociale", "La ragione sociale è obbligatoria.")
            return
        self.accept()

    def valori(self):
        return {k: e.text().strip() for k, e in self.e.items()}


class DialogoTask(QDialog):
    """Dove creare i task delle azioni: Planner oppure attività di Dynamics (si chiede ogni volta)."""

    def __init__(self, azioni, account, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crea i task")
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Azioni dalla relazione (togli la spunta a quelle da non creare):"))
        self.lista = QListWidget()
        for a in azioni:
            it = QListWidgetItem(" · ".join(x for x in (a.get("descrizione"), a.get("responsabile"),
                                                        a.get("scadenza") and "entro " + a["scadenza"]) if x))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, a)
            self.lista.addItem(it)
        lay.addWidget(self.lista, 1)
        lay.addWidget(QLabel("Dove li creo?"))
        self.r_planner = QRadioButton("Planner (Microsoft 365)")
        self.r_dyn = QRadioButton("Attività di Dynamics 365 (collegate al cliente)")
        lay.addWidget(self.r_planner)
        riga_p = QHBoxLayout()
        self.c_piano = QComboBox()
        self.c_bucket = QComboBox()
        riga_p.addWidget(QLabel("   Piano:"))
        riga_p.addWidget(self.c_piano, 1)
        riga_p.addWidget(QLabel("Bucket:"))
        riga_p.addWidget(self.c_bucket, 1)
        lay.addLayout(riga_p)
        lay.addWidget(self.r_dyn)
        riga_d = QHBoxLayout()
        riga_d.addWidget(QLabel("   Cliente:"))
        self.c_account = QComboBox()
        for a in account:
            self.c_account.addItem(a["name"], a["accountid"])
        riga_d.addWidget(self.c_account, 1)
        lay.addLayout(riga_d)
        self.r_dyn.setEnabled(bool(account))
        if not account:
            self.r_dyn.setText(self.r_dyn.text() + " — prima scegli l'azienda dei partecipanti")
        self.r_planner.toggled.connect(self._modo)
        self.c_piano.currentIndexChanged.connect(self._bucket)
        self.l_stato = QLabel("")
        self.l_stato.setProperty("ruolo", "tenue")
        lay.addWidget(self.l_stato)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Crea task")
        b.accepted.connect(self._ok)
        b.rejected.connect(self.reject)
        lay.addWidget(b)
        self._piani_caricati = False
        self.r_planner.setChecked(False)
        self.r_dyn.setChecked(False)
        self._modo()

    def _modo(self):
        planner = self.r_planner.isChecked()
        self.c_piano.setEnabled(planner)
        self.c_bucket.setEnabled(planner)
        self.c_account.setEnabled(self.r_dyn.isChecked())
        if planner and not self._piani_caricati:
            import m365
            try:
                for p in m365.piani():
                    self.c_piano.addItem(p["titolo"], p["id"])
                self._piani_caricati = True
            except Exception as e:
                self.l_stato.setText(f"⚠️ Planner: {e}")

    def _bucket(self):
        import m365
        self.c_bucket.clear()
        if self.c_piano.currentData():
            try:
                for b in m365.bucket(self.c_piano.currentData()):
                    self.c_bucket.addItem(b["nome"], b["id"])
            except Exception as e:
                self.l_stato.setText(f"⚠️ Planner: {e}")

    def _ok(self):
        if not (self.r_planner.isChecked() or self.r_dyn.isChecked()):
            QMessageBox.information(self, "Dove?", "Scegli Planner o Dynamics.")
            return
        if self.r_planner.isChecked() and not (self.c_piano.currentData() and self.c_bucket.currentData()):
            QMessageBox.information(self, "Planner", "Scegli piano e bucket.")
            return
        self.accept()

    def scelte(self):
        return [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.Checked]


# =============================================================== pagina
class SchedaClienti(QWidget):
    COL_NOME, COL_EMAIL, COL_AZIENDA, COL_CONTATTO = range(4)

    def __init__(self, finestra):
        super().__init__()
        self.finestra = finestra
        self.lavoro = None
        lay = QVBoxLayout(self)
        self.schede = QTabWidget()
        self.schede.addTab(self._tab_cliente(), "Cliente")
        self.schede.addTab(self._tab_call(), "Dalla call")
        lay.addWidget(self.schede, 1)
        self.l_stato = QLabel("")
        self.l_stato.setProperty("ruolo", "tenue")
        self.l_stato.setWordWrap(True)
        self.barra = QProgressBar()
        self.barra.setFixedHeight(8)
        self.barra.setTextVisible(False)
        self.barra.setVisible(False)
        lay.addWidget(self.barra)
        lay.addWidget(self.l_stato)
        self._aggiorna_stato_servizi()

    # ------------------------------------------------------------ servizi
    def _aggiorna_stato_servizi(self):
        manca = []
        if not crm.configurato():
            manca.append("Dynamics (Impostazioni › Dynamics 365 Sales)")
        if not web.configurata():
            manca.append("chiave di Ollama Web Search (Impostazioni › Ricerca web)")
        self.l_stato.setText(("Da configurare: " + "; ".join(manca)) if manca else
                             "🔒 Trascrizioni e partecipanti restano su questo computer; sul web esce solo il nome "
                             "dell'azienda; su Dynamics va solo ciò che confermi.")

    def _avvia(self, fn, fine, stato_iniziale="", con_barra=False):
        if self.lavoro:
            QMessageBox.information(self, "Attendi", "Sto già lavorando: aspetta la fine.")
            return
        self.lavoro = Lavoro(fn, self)
        self.lavoro.sig_stato.connect(self.l_stato.setText)
        self.lavoro.sig_avanzamento.connect(self.barra.setValue)

        def ok(r):
            self.lavoro = None
            self.barra.setVisible(False)
            fine(r)

        def ko(e):
            self.lavoro = None
            self.barra.setVisible(False)
            self.l_stato.setText(f"⚠️ {e}")

        self.lavoro.sig_fine.connect(ok)
        self.lavoro.sig_errore.connect(ko)
        self.barra.setValue(0)
        self.barra.setVisible(con_barra)
        self.l_stato.setText(stato_iniziale)
        self.lavoro.start()

    # ------------------------------------------------------------ scheda Cliente
    def _tab_cliente(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        riga = QHBoxLayout()
        self.e_cerca = QLineEdit()
        self.e_cerca.setPlaceholderText("Nome dell'azienda, sito o dominio email (es. weleda.it)")
        self.e_cerca.returnPressed.connect(self.cerca_cliente)
        riga.addWidget(self.e_cerca, 3)
        self.e_extra = QLineEdit()
        self.e_extra.setPlaceholderText("Sito, sede o P.IVA (solo se ci sono omonimi)")
        riga.addWidget(self.e_extra, 2)
        lay.addLayout(riga)
        comandi = QHBoxLayout()
        b_cerca = QPushButton("🔍 Cerca in Dynamics")
        b_cerca.setProperty("primario", True)
        b_cerca.clicked.connect(self.cerca_cliente)
        comandi.addWidget(b_cerca)
        self.b_scheda = QPushButton("🌐 Scheda pubblica")
        self.b_scheda.setToolTip("Regole di Client Intel Scout: fonti pubbliche con data, niente dati inventati, "
                                 "10 sezioni. Ricerca con Ollama Web Search, scrittura con il modello locale.")
        self.b_scheda.clicked.connect(self.scheda_pubblica)
        comandi.addWidget(self.b_scheda)
        self.b_crea = QPushButton("➕ Crea account…")
        self.b_crea.setEnabled(False)
        self.b_crea.clicked.connect(self.crea_account)
        comandi.addWidget(self.b_crea)
        comandi.addStretch()
        self.b_apri = QPushButton("Apri in Dynamics")
        self.b_apri.setEnabled(False)
        self.b_apri.clicked.connect(self._apri_account)
        comandi.addWidget(self.b_apri)
        lay.addLayout(comandi)
        div = QSplitter(Qt.Horizontal)
        self.t_account = QTableWidget(0, 4)
        self.t_account.setHorizontalHeaderLabels(["Account", "Città", "Sito", "Dipendenti"])
        self.t_account.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t_account.verticalHeader().setVisible(False)
        self.t_account.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t_account.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t_account.itemSelectionChanged.connect(self._mostra_account)
        div.addWidget(self.t_account)
        self.v_cliente = QTextBrowser()
        self.v_cliente.setOpenExternalLinks(True)
        self.v_cliente.setMarkdown("*Cerca un cliente: se non è in Dynamics, prepara la scheda pubblica.*")
        div.addWidget(self.v_cliente)
        div.setStretchFactor(1, 2)
        lay.addWidget(div, 1)
        self._account = []
        self._scheda = None
        return w

    def cerca_cliente(self):
        testo = self.e_cerca.text().strip()
        if not testo:
            return
        if not crm.configurato():
            QMessageBox.information(self, "Dynamics", "Prima collega Dynamics in Impostazioni › Dynamics 365 Sales.")
            return
        self._avvia(lambda _l: crm.cerca_account(testo), self._account_trovati, f"Cerco «{testo}» in Dynamics…")

    def _account_trovati(self, account):
        self._account = account
        self.t_account.setRowCount(len(account))
        for r, a in enumerate(account):
            for c, v in enumerate((a.get("name"), a.get("address1_city"), a.get("websiteurl"), a.get("numberofemployees"))):
                self.t_account.setItem(r, c, QTableWidgetItem(_testo(v)))
        testo = self.e_cerca.text().strip()
        salvate = scheda.schede_salvate(testo)
        if account:
            self.l_stato.setText(f"{len(account)} account trovati in Dynamics.")
            self.t_account.selectRow(0)
        else:
            self.v_cliente.setMarkdown(f"### «{testo}» non è in Dynamics\n\nPremi **🌐 Scheda pubblica** per raccogliere "
                                       "le informazioni pubbliche e proporre l'account."
                                       + (f"\n\nC'è già una scheda del {salvate[0].stem[7:15]}: la apro qui sotto.\n\n---\n\n"
                                          + salvate[0].read_text(encoding="utf-8") if salvate else ""))
            self.l_stato.setText("Nessun account trovato.")

    def _account_corrente(self):
        r = self.t_account.currentRow()
        return self._account[r] if 0 <= r < len(self._account) else None

    def _mostra_account(self):
        a = self._account_corrente()
        self.b_apri.setEnabled(bool(a))
        if not a:
            return
        righe = [f"## {a.get('name')}", ""]
        for etichetta, chiave in (("Sito", "websiteurl"), ("Città", "address1_city"), ("Nazione", "address1_country"),
                                  ("Telefono", "telephone1"), ("Email", "emailaddress1"), ("Dipendenti", "numberofemployees")):
            if a.get(chiave):
                righe.append(f"- **{etichetta}:** {a[chiave]}")
        if a.get("description"):
            righe += ["", a["description"]]
        self.v_cliente.setMarkdown("\n".join(righe) + "\n\n*Carico i contatti…*")

        def fine(contatti):
            elenco = "\n".join(f"- {c.get('fullname')}" + (f" · {c['jobtitle']}" if c.get("jobtitle") else "")
                               + (f" · {c['emailaddress1']}" if c.get("emailaddress1") else "") for c in contatti)
            self.v_cliente.setMarkdown("\n".join(righe) + "\n\n### Contatti\n\n" + (elenco or "*Nessun contatto.*"))
            self.l_stato.setText("")

        self._avvia(lambda _l: crm.contatti_account(a["accountid"]), fine)

    def _apri_account(self):
        a = self._account_corrente()
        if a:
            QDesktopServices.openUrl(QUrl(crm.link("account", a["accountid"])))

    def scheda_pubblica(self, scelta=None):
        nome = self.e_cerca.text().strip()
        if not nome:
            QMessageBox.information(self, "Scheda pubblica", "Scrivi il nome dell'azienda.")
            return
        if not web.configurata():
            QMessageBox.information(self, "Ricerca web", "Serve la chiave di Ollama Web Search: Impostazioni › Ricerca web.")
            return
        extra = self.e_extra.text().strip()

        def fn(lav):
            return scheda.ricerca(nome, extra, stato=lav.sig_stato.emit, avanzamento=lav.sig_avanzamento.emit,
                                  stop=lav.fermato, scelta_candidato=scelta if isinstance(scelta, dict) else None)

        self._avvia(fn, self._scheda_pronta, f"Scheda pubblica di «{nome}»…", con_barra=True)

    def _scheda_pronta(self, r):
        if r["stato"] == "ambiguo":
            d = DialogoCandidati(r["candidati"], self)
            if d.exec() and d.scelta():
                self.scheda_pubblica(d.scelta())
            else:
                self.l_stato.setText("Più aziende omonime: indica sito, sede o P.IVA e riprova.")
            return
        self._scheda = r
        self.v_cliente.setMarkdown(r["markdown"])
        self.b_crea.setEnabled(crm.configurato())
        self.l_stato.setText(f"Scheda salvata in {r['cartella']}. Rileggila: poi «➕ Crea account…».")

    def crea_account(self):
        if not self._scheda:
            return
        d = DialogoAccount(self._scheda["account"], self)
        if not d.exec():
            return
        campi, con_nota, testo = d.valori(), d.cb_nota.isChecked(), self._scheda["markdown"]

        def fn(_l):
            aid = crm.crea_account(campi)
            if con_nota:
                crm.crea_nota("account", aid, f"Profilo pubblico · {campi['ragione_sociale']}", testo)
            return aid

        def fine(aid):
            self.l_stato.setText(f"✅ Account creato: {campi['ragione_sociale']}")
            QDesktopServices.openUrl(QUrl(crm.link("account", aid)))
            self.e_cerca.setText(campi["ragione_sociale"])
            self.cerca_cliente()

        self._avvia(fn, fine, "Creo l'account in Dynamics…")

    # ------------------------------------------------------------ scheda Dalla call
    def _tab_call(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        riga = QHBoxLayout()
        riga.addWidget(QLabel("Call:"))
        self.c_call = QComboBox()
        self.c_call.currentIndexChanged.connect(self._call_scelta)
        riga.addWidget(self.c_call, 1)
        self.b_importa = QToolButton()
        self.b_importa.setText("Dal computer ▾")
        self.b_importa.setToolTip("Porta una trascrizione fatta con Trascrivi tra le call (e tra gli Incontri)")
        self.b_importa.setPopupMode(QToolButton.InstantPopup)
        self.b_importa.clicked.connect(self._menu_trascrizioni)
        riga.addWidget(self.b_importa)
        b_agg = QPushButton("↻")
        b_agg.setToolTip("Aggiorna l'elenco")
        b_agg.clicked.connect(self.aggiorna_call)
        riga.addWidget(b_agg)
        lay.addLayout(riga)

        comandi = QHBoxLayout()
        b_proponi = QPushButton("🏢 Proponi aziende dal CRM")
        b_proponi.setProperty("primario", True)
        b_proponi.setToolTip("Per ogni partecipante: dominio email, azienda del biglietto da visita, nome → account in Dynamics")
        b_proponi.clicked.connect(self.proponi_aziende)
        comandi.addWidget(b_proponi)
        b_cal = QPushButton("📅 Invitati dal calendario")
        b_cal.setToolTip("Aggiunge gli invitati (con email) della riunione di Outlook più vicina all'orario della call")
        b_cal.clicked.connect(self.invitati_calendario)
        comandi.addWidget(b_cal)
        b_add = QPushButton("+ Partecipante")
        b_add.clicked.connect(lambda: self._aggiungi_riga({"nome": ""}))
        comandi.addWidget(b_add)
        comandi.addStretch()
        lay.addLayout(comandi)

        self.t_part = QTableWidget(0, 4)
        self.t_part.setHorizontalHeaderLabels(["Partecipante", "Email", "Azienda", "Contatto in CRM"])
        h = self.t_part.horizontalHeader()
        h.setSectionResizeMode(self.COL_NOME, QHeaderView.Stretch)
        h.setSectionResizeMode(self.COL_AZIENDA, QHeaderView.Stretch)
        self.t_part.setColumnWidth(self.COL_EMAIL, 220)
        self.t_part.setColumnWidth(self.COL_CONTATTO, 130)
        self.t_part.verticalHeader().setVisible(False)
        lay.addWidget(self.t_part, 2)

        azioni = QHBoxLayout()
        self.b_rel = QPushButton("✨ Relazione")
        self.b_rel.clicked.connect(self.relazione)
        azioni.addWidget(self.b_rel)
        self.b_crm = QPushButton("☁️ Salva in Dynamics")
        self.b_crm.setToolTip("Contatti nuovi per i partecipanti spuntati e relazione come nota sugli account scelti")
        self.b_crm.clicked.connect(self.salva_crm)
        azioni.addWidget(self.b_crm)
        self.b_task = QPushButton("✅ Crea task…")
        self.b_task.setToolTip("Le azioni della relazione: in Planner o come attività di Dynamics (scegli ogni volta)")
        self.b_task.clicked.connect(self.crea_task)
        azioni.addWidget(self.b_task)
        azioni.addStretch()
        lay.addLayout(azioni)
        self.v_rel = QTextBrowser()
        self.v_rel.setOpenExternalLinks(True)
        lay.addWidget(self.v_rel, 3)
        self._call = []
        self.aggiorna_call()
        return w

    def aggiorna_call(self):
        attuale = self.c_call.currentData()
        self._call = pt.elenco_incontri()
        self.c_call.blockSignals(True)
        self.c_call.clear()
        for cartella, d in self._call:
            titolo = rel.carica(cartella).get("relazione", {}).get("titolo") or d.get("titolo", cartella.name)
            fonte = "💻" if d.get("origine_file") else "📱"
            self.c_call.addItem(f"{fonte} {(d.get('creata') or '')[:10]} · {titolo}", cartella.name)
        self.c_call.blockSignals(False)
        i = self.c_call.findData(attuale)
        self.c_call.setCurrentIndex(i if i >= 0 else 0)
        self._call_scelta()

    def _menu_trascrizioni(self):
        m = QMenu(self)
        voci = chiamate.trascrizioni_desktop()
        for job, gia in voci:
            nome = Path(job["file"]).name
            a = m.addAction(("✓ " if gia else "") + nome)
            a.triggered.connect(lambda _c=False, j=job: self._importa(j))
        if not voci:
            m.addAction("Nessuna trascrizione completata in Trascrivi").setEnabled(False)
        m.exec(self.b_importa.mapToGlobal(self.b_importa.rect().bottomLeft()))

    def _importa(self, job):
        try:
            id_incontro = chiamate.importa_trascrizione(job["json"])
        except Exception as e:
            QMessageBox.warning(self, "Trascrizione", str(e))
            return
        self.aggiorna_call()
        self.c_call.setCurrentIndex(max(0, self.c_call.findData(id_incontro)))
        if hasattr(self.finestra, "tab_incontri"):
            self.finestra.tab_incontri.aggiorna()

    def _corrente(self):
        i = self.c_call.currentIndex()
        return self._call[i] if 0 <= i < len(self._call) else (None, None)

    def _salvataggio(self, cartella):
        return Path(cartella) / "argo-clienti.json"

    def _call_scelta(self):
        cartella, d = self._corrente()
        self.t_part.setRowCount(0)
        if not cartella:
            self.v_rel.setMarkdown("*Nessuna call: arrivano dall'iPhone (Incontri) o dal computer («Dal computer ▾»).*")
            return
        try:
            salvati = json.loads(self._salvataggio(cartella).read_text(encoding="utf-8"))
        except Exception:
            salvati = None
        if salvati:
            for p in salvati.get("partecipanti", []):
                self._aggiungi_riga(p)
        else:
            relazione = rel.carica(cartella).get("relazione") or {}
            nomi = set()
            for c in relazione.get("contatti") or []:  # dai biglietti da visita: hanno azienda ed email
                nome = " ".join(x for x in (c.get("nome"), c.get("cognome")) if x)
                nomi.add(nome.lower())
                self._aggiungi_riga({"nome": nome, "email": c.get("email", ""), "azienda_testo": c.get("azienda", ""),
                                     "ruolo": c.get("ruolo", "")})
            for p in d.get("partecipanti", []):
                nome = p.get("nome") or p.get("id")
                if nome.lower() not in nomi and not nome.lower().startswith(("parlante", "sconosciuto")):
                    self._aggiungi_riga({"nome": nome, "scelta": (INTERNO, None), "crea_contatto": False}
                                        if _sono_io(nome) else {"nome": nome})
        testo = (Path(cartella) / rel.FILE_TESTO)
        self.v_rel.setMarkdown(testo.read_text(encoding="utf-8") if testo.exists() else
                               "*Nessuna relazione: premi «✨ Relazione».*")

    def _aggiungi_riga(self, p):
        r = self.t_part.rowCount()
        self.t_part.insertRow(r)
        it = QTableWidgetItem(p.get("nome", ""))
        it.setData(Qt.UserRole, p)
        self.t_part.setItem(r, self.COL_NOME, it)
        self.t_part.setItem(r, self.COL_EMAIL, QTableWidgetItem(p.get("email", "")))
        combo = QComboBox()
        combo.addItem("❓ Da decidere", (DA_DECIDERE, None))
        combo.addItem("🏠 Interno (la mia azienda)", (INTERNO, None))
        for a in p.get("proposte", []):
            combo.addItem(f"🏢 {a['name']}" + (f" · {a['citta']}" if a.get("citta") else ""), ("account", a))
        combo.addItem("🔎 Altra azienda in Dynamics…", (ALTRA, None))
        combo.addItem("➕ Nuovo cliente (scheda pubblica)…", (NUOVO, None))
        scelta = p.get("scelta")
        if scelta:
            for i in range(combo.count()):
                dati = combo.itemData(i)
                if dati[0] == scelta[0] and (dati[1] or {}).get("accountid") == (scelta[1] or {}).get("accountid"):
                    combo.setCurrentIndex(i)
        combo.activated.connect(lambda _i, c=combo, riga=it: self._azienda_scelta(c, riga))
        self.t_part.setCellWidget(r, self.COL_AZIENDA, combo)
        cb = QCheckBox("crea se manca")
        cb.setChecked(bool(p.get("crea_contatto", True)))
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(6, 0, 0, 0)
        bl.addWidget(cb)
        box.cb = cb
        self.t_part.setCellWidget(r, self.COL_CONTATTO, box)

    def _righe(self):
        out = []
        for r in range(self.t_part.rowCount()):
            p = dict(self.t_part.item(r, self.COL_NOME).data(Qt.UserRole) or {})
            p["nome"] = self.t_part.item(r, self.COL_NOME).text().strip()
            p["email"] = (self.t_part.item(r, self.COL_EMAIL).text() if self.t_part.item(r, self.COL_EMAIL) else "").strip()
            combo = self.t_part.cellWidget(r, self.COL_AZIENDA)
            p["scelta"] = combo.currentData() if combo else (DA_DECIDERE, None)
            p["crea_contatto"] = self.t_part.cellWidget(r, self.COL_CONTATTO).cb.isChecked()
            p["proposte"] = [combo.itemData(i)[1] for i in range(combo.count()) if combo.itemData(i)[0] == "account"]
            out.append(p)
        return out

    def _salva_righe(self):
        cartella, _d = self._corrente()
        if cartella:
            self._salvataggio(cartella).write_text(json.dumps({"partecipanti": self._righe(),
                                                               "aggiornato": datetime.now().strftime("%Y-%m-%d %H:%M")},
                                                              ensure_ascii=False, indent=2), encoding="utf-8")

    def _azienda_scelta(self, combo, riga):
        tipo, _dati = combo.currentData()
        if tipo == ALTRA:
            testo, ok = QInputDialog.getText(self, "Cerca in Dynamics", "Nome, sito o dominio dell'azienda:")
            if ok and testo.strip():
                def fine(account):
                    if not account:
                        QMessageBox.information(self, "Dynamics", f"«{testo}» non è in Dynamics: usa «Nuovo cliente».")
                        combo.setCurrentIndex(0)
                        return
                    for a in account:
                        combo.insertItem(combo.count() - 2, f"🏢 {a['name']}", ("account", {
                            "accountid": a["accountid"], "name": a["name"], "citta": a.get("address1_city")}))
                    combo.setCurrentIndex(combo.count() - 2 - len(account))
                    self._salva_righe()
                self._avvia(lambda _l: crm.cerca_account(testo.strip()), fine, f"Cerco «{testo}» in Dynamics…")
            else:
                combo.setCurrentIndex(0)
            return
        if tipo == NUOVO:
            p = riga.data(Qt.UserRole) or {}
            self.schede.setCurrentIndex(0)
            self.e_cerca.setText(p.get("azienda_testo") or (crm.dominio_email(p.get("email")) or ""))
            self.l_stato.setText("Cerca il cliente o prepara la scheda pubblica; poi torna su «Dalla call» e scegli l'account.")
            combo.setCurrentIndex(0)
            return
        self._salva_righe()

    def invitati_calendario(self):
        cartella, d = self._corrente()
        if not cartella:
            return

        def fine(r):
            oggetto, persone = r
            if not persone:
                self.l_stato.setText("Nessuna riunione di calendario vicina all'orario della call (o Microsoft 365 non collegato).")
                return
            presenti = {self.t_part.item(i, self.COL_NOME).text().lower(): i for i in range(self.t_part.rowCount())}
            aggiunti = 0
            for p in persone:
                riga = presenti.get(p["nome"].lower())
                if riga is not None:
                    self.t_part.setItem(riga, self.COL_EMAIL, QTableWidgetItem(p["email"]))
                else:
                    self._aggiungi_riga(p)
                    aggiunti += 1
            self._salva_righe()
            self.l_stato.setText(f"📅 «{oggetto}»: {len(persone)} invitati ({aggiunti} nuovi). Ora «🏢 Proponi aziende».")

        self._avvia(lambda _l: chiamate.invitati(d), fine, "Cerco la riunione nel calendario…")

    def proponi_aziende(self):
        if not crm.configurato():
            QMessageBox.information(self, "Dynamics", "Prima collega Dynamics in Impostazioni › Dynamics 365 Sales.")
            return
        righe = self._righe()
        import m365
        mio_dominio = crm.dominio_email(m365.account() or "")

        def fn(lav):
            esiti = []
            for i, p in enumerate(righe, 1):
                lav.sig_stato.emit(f"Cerco l'azienda di {p['nome'] or p['email']} ({i}/{len(righe)})…")
                dominio = crm.dominio_email(p.get("email"))
                if _sono_io(p.get("nome")) or (mio_dominio and dominio == mio_dominio):
                    esiti.append(("interno", []))
                    continue
                trovati = {}
                contatto = crm.contatto_per_email(p.get("email"))
                if contatto and contatto.get("_parentcustomerid_value"):
                    try:  # il contatto esiste già: la sua azienda è la prima proposta
                        a = crm.account(contatto["_parentcustomerid_value"])
                        trovati[a["accountid"]] = a
                    except crm.ErroreCRM:
                        pass
                for a in crm.account_per_dominio(dominio):
                    trovati[a["accountid"]] = a
                if p.get("azienda_testo"):
                    for a in crm.cerca_account(p["azienda_testo"]):
                        trovati[a["accountid"]] = a
                esiti.append(("crm", list(trovati.values())[:6], contatto))
            return esiti

        def fine(esiti):
            n = 0
            for r, (p, esito) in enumerate(zip(righe, esiti)):
                if esito[0] == "interno":
                    p["scelta"] = (INTERNO, None)
                    p["crea_contatto"] = False
                else:
                    p["proposte"] = [{"accountid": a["accountid"], "name": a["name"], "citta": a.get("address1_city")}
                                     for a in esito[1]]
                    if len(p["proposte"]) == 1:
                        p["scelta"] = ("account", p["proposte"][0])
                    p["crea_contatto"] = not esito[2]  # c'è già un contatto con quella email: non si duplica
                    n += bool(p["proposte"])
            self.t_part.setRowCount(0)
            for p in righe:
                self._aggiungi_riga(p)
            self._salva_righe()
            self.l_stato.setText(f"Aziende proposte per {n} partecipanti su {len(righe)}: controlla la colonna «Azienda». "
                                 "Dove non c'è nulla: «Altra azienda» o «Nuovo cliente».")

        self._avvia(fn, fine, "Cerco le aziende nel CRM…")

    def relazione(self):
        cartella, d = self._corrente()
        if not cartella:
            return
        if (Path(cartella) / rel.FILE_TESTO).exists() and QMessageBox.question(
                self, "Relazione", "Esiste già una relazione: rifarla?") != QMessageBox.Yes:
            return
        import voci_core as core
        import llm_locale as llm
        s = core.carica_impostazioni()

        def fn(lav):
            return rel.scrivi_relazione(cartella, d, s.get("ollama_url", llm.DEFAULT_URL), s.get("modello_chat"),
                                        s.get("modello_vision") or None, stato=lav.sig_stato.emit,
                                        stop=lav.fermato, avanzamento=lav.sig_avanzamento.emit)

        def fine(_r):
            self._call_scelta()
            self.l_stato.setText("Relazione pronta: rileggila, poi «☁️ Salva in Dynamics» e «✅ Crea task…».")
            if hasattr(self.finestra, "tab_incontri"):
                self.finestra.tab_incontri.aggiorna()

        self._avvia(fn, fine, "Scrivo la relazione…", con_barra=True)

    def _account_scelti(self):
        visti = {}
        for p in self._righe():
            tipo, dati = p["scelta"]
            if tipo == "account" and dati:
                visti[dati["accountid"]] = {"accountid": dati["accountid"], "name": dati["name"]}
        return list(visti.values())

    def salva_crm(self):
        cartella, _d = self._corrente()
        if not cartella:
            return
        righe = self._righe()
        account = self._account_scelti()
        if not account:
            QMessageBox.information(self, "Dynamics", "Scegli prima l'azienda di almeno un partecipante.")
            return
        testo_file = Path(cartella) / rel.FILE_TESTO
        testo = testo_file.read_text(encoding="utf-8") if testo_file.exists() else ""
        titolo = (rel.carica(cartella).get("relazione") or {}).get("titolo") or _d.get("titolo", "Call")
        nuovi = [p for p in righe if p["scelta"][0] == "account" and p["crea_contatto"] and p["nome"]]
        domanda = (f"Su Dynamics:\n• {len(nuovi)} contatti nuovi\n"
                   + (f"• relazione come nota su: {', '.join(a['name'] for a in account)}" if testo else "• (nessuna relazione da allegare)")
                   + "\n\nProcedo?")
        if QMessageBox.question(self, "Salva in Dynamics", domanda) != QMessageBox.Yes:
            return

        def fn(lav):
            record = []
            for p in nuovi:
                lav.sig_stato.emit(f"Creo il contatto {p['nome']}…")
                cid = crm.crea_contatto({"nome": p["nome"], "email": p.get("email"), "ruolo": p.get("ruolo")},
                                        p["scelta"][1]["accountid"])
                record.append({"tipo": "contact", "id": cid, "nome": p["nome"], "link": crm.link("contact", cid)})
            if testo:
                for a in account:
                    lav.sig_stato.emit(f"Relazione come nota su {a['name']}…")
                    crm.crea_nota("account", a["accountid"], f"Relazione · {titolo}", testo)
                    record.append({"tipo": "account", "id": a["accountid"], "nome": a["name"],
                                   "link": crm.link("account", a["accountid"])})
            return record

        def fine(record):
            for p in righe:
                if p in nuovi:
                    p["crea_contatto"] = False
            vecchio = crm_incontri.esito(cartella) or {}
            storico = vecchio.get("storico", []) + ([{"inviato": vecchio.get("inviato"), "record": vecchio["record"]}]
                                                     if vecchio.get("record") else [])
            (Path(cartella) / crm_incontri.FILE_CRM).write_text(json.dumps({
                "inviato": datetime.now().strftime("%Y-%m-%d %H:%M"), "ambiente": crm.ambiente(), "record": record,
                "storico": storico}, ensure_ascii=False, indent=2), encoding="utf-8")
            self._salva_righe()
            self.l_stato.setText("☁️ Salvato in Dynamics: " + ", ".join(f"{r['nome']} ({r['tipo']})" for r in record))
            if hasattr(self.finestra, "tab_incontri"):
                self.finestra.tab_incontri.aggiorna()

        self._avvia(fn, fine, "Salvo in Dynamics…")

    def crea_task(self):
        cartella, _d = self._corrente()
        if not cartella:
            return
        azioni = (rel.carica(cartella).get("relazione") or {}).get("azioni") or []
        if not azioni:
            QMessageBox.information(self, "Task", "La relazione non ha azioni: premi prima «✨ Relazione».")
            return
        d = DialogoTask(azioni, self._account_scelti(), self)
        if not d.exec():
            return
        scelte = d.scelte()
        if d.r_planner.isChecked():
            import m365
            piano, bucket = d.c_piano.currentData(), d.c_bucket.currentData()
            persone = [{"nome": p["nome"], "email": p["email"]} for p in self._righe() if p.get("email")]

            def fn(_l):
                utenti = m365.trova_utenti(persone)
                return m365.crea_task(piano, bucket, [{"titolo": a.get("descrizione", "Azione"),
                                                       "responsabile": a.get("responsabile")} for a in scelte], utenti)

            self._avvia(fn, lambda r: self.l_stato.setText(f"✅ {len(r)} task creati in Planner "
                                                           f"({sum(1 for t in r if t['assegnato'])} assegnati)."),
                        "Creo i task in Planner…")
        else:
            aid, nome = d.c_account.currentData(), d.c_account.currentText()

            def fn(_l):
                return [crm.crea_attivita("account", aid, a) for a in scelte]

            self._avvia(fn, lambda r: self.l_stato.setText(f"✅ {len(r)} attività create in Dynamics su {nome}."),
                        "Creo le attività in Dynamics…")
