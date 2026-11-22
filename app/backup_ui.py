"""backup_ui.py - Impostazioni › Backup e più computer.

Gruppi: dove salvare, backup (ora, alla chiusura, periodico), chiavi e token cifrati, ripristino, configurazione
condivisa tra più computer. La logica è in backup.py.
"""
from lingua import tr
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import argo_attrezzi as attrezzi
import backup
import veglia
import voci_core as core

ALTRA = "__altra__"


def _nota(testo):
    l = QLabel(testo)
    l.setWordWrap(True)
    l.setProperty("ruolo", "tenue")
    return l


def _dimensione(byte):
    return f"{byte / 1e6:.1f} MB".replace(".", ",") if byte >= 1e5 else f"{byte / 1e3:.0f} KB"


def _quando(iso):
    return (iso or "")[:16].replace("T", " ")


def _riempi_cartelle(combo, attuale, sotto, locale):
    """Tendina delle cartelle: locale, cartelle sincronizzate trovate, altra cartella."""
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(tr('Su questo computer · {locale}', locale=locale), str(locale))
    if not backup.cloud_vietato():
        for etichetta, base in backup.cartelle_cloud():
            combo.addItem(f"{etichetta} · {base / sotto}", str(base / sotto))
    if attuale and combo.findData(str(attuale)) < 0:
        combo.addItem(f"{attuale}", str(attuale))
    combo.addItem(tr('Altra cartella…'), ALTRA)
    i = combo.findData(str(attuale)) if attuale else 0
    combo.setCurrentIndex(max(0, i))
    combo.blockSignals(False)


class PannelloBackup(QWidget):
    def __init__(self, finestra):
        super().__init__()
        self.finestra = finestra
        self.gruppi = []
        s = core.carica_impostazioni()

        # -- dove
        g = QGroupBox(tr('Dove salvare i backup'))
        f = QFormLayout(g)
        self.c_dove = QComboBox()
        self.c_dove.activated.connect(lambda _i: self._scegli_cartella(self.c_dove, "backup_cartella",
                                                                       backup.SOTTOCARTELLA + "/Backup"))
        f.addRow(tr('Cartella:'), self.c_dove)
        self.l_dove = QLabel("")
        self.l_dove.setWordWrap(True)
        f.addRow("", self.l_dove)
        f.addRow(_nota("Le cartelle di OneDrive e Google Drive compaiono se sul computer c'è l'app di "
                       "sincronizzazione (OneDrive, Google Drive per desktop): Argo scrive lì e ci pensa l'app a "
                       "portarle nel cloud, senza altri accessi. Ogni backup salvato lì compare in «Cosa è uscito "
                       "da questo computer»."))
        self.gruppi.append(("backup_dove", g))

        # -- backup
        g = QGroupBox(tr('Backup'))
        lg = QVBoxLayout(g)
        lg.addWidget(_nota("«Configurazione»: impostazioni, template delle relazioni, glossario (pochi KB). "
                           "«Completo»: anche voci, incontri, clienti, Secondo cervello e indice dei Documenti: può "
                           "pesare GB per audio e foto degli incontri. Le trascrizioni salvate accanto ai tuoi file "
                           "audio non sono nella cartella di Argo e non entrano nel backup."))
        r = QHBoxLayout()
        for testo, livello in (("💾 Backup configurazione ora", "configurazione"), ("💾 Backup completo ora", "completo")):
            b = QPushButton(testo)
            b.clicked.connect(lambda _c=False, lv=livello: self.fai_backup(lv))
            r.addWidget(b)
        r.addStretch(1)
        lg.addLayout(r)
        f = QFormLayout()
        self.c_chiusura = QComboBox()
        for testo, dato in (("Nessuno", ""), ("Configurazione", "configurazione"), ("Completo", "completo")):
            self.c_chiusura.addItem(testo, dato)
        self.c_chiusura.setCurrentIndex(max(0, self.c_chiusura.findData(s.get("backup_alla_chiusura", "configurazione"))))
        self.c_chiusura.currentIndexChanged.connect(lambda _i: self._salva("backup_alla_chiusura", self.c_chiusura.currentData()))
        f.addRow(tr('Alla chiusura di Argo:'), self.c_chiusura)
        riga = QHBoxLayout()
        self.c_periodo = QComboBox()
        for testo, dato in (("Mai", ""), ("Ogni giorno", "giorno"), ("Ogni settimana", "settimana")):
            self.c_periodo.addItem(testo, dato)
        self.c_periodo.setCurrentIndex(max(0, self.c_periodo.findData(s.get("backup_periodico", ""))))
        self.c_periodo.currentIndexChanged.connect(lambda _i: self._salva("backup_periodico", self.c_periodo.currentData()))
        self.c_periodo_livello = QComboBox()
        self.c_periodo_livello.addItem(tr('configurazione'), "configurazione")
        self.c_periodo_livello.addItem(tr('completo'), "completo")
        self.c_periodo_livello.setCurrentIndex(max(0, self.c_periodo_livello.findData(
            s.get("backup_periodico_livello", "completo"))))
        self.c_periodo_livello.currentIndexChanged.connect(
            lambda _i: self._salva("backup_periodico_livello", self.c_periodo_livello.currentData()))
        riga.addWidget(self.c_periodo)
        riga.addWidget(QLabel(tr('backup')))
        riga.addWidget(self.c_periodo_livello)
        riga.addStretch(1)
        f.addRow(tr('Programmato:'), riga)
        self.s_conserva = QSpinBox()
        self.s_conserva.setRange(1, 100)
        self.s_conserva.setValue(int(s.get("backup_conserva") or 10))
        self.s_conserva.valueChanged.connect(lambda v: self._salva("backup_conserva", v))
        f.addRow(tr('Conserva gli ultimi:'), self.s_conserva)
        lg.addLayout(f)
        self.l_ultimo = _nota("")
        lg.addWidget(self.l_ultimo)
        self.gruppi.append(("backup", g))

        # -- chiavi
        g = QGroupBox(tr('Chiavi e token nel backup (cifrati)'))
        lg = QVBoxLayout(g)
        lg.addWidget(_nota("Con una password, i backup portano anche token di Hugging Face, chiavi di Claude e Ollama "
                           "Cloud e l'accesso a Microsoft 365, cifrati (AES-256): chi trova il file senza la password "
                           "non li legge. La password non si salva; su questo computer resta solo la chiave che ne "
                           "deriva, così anche i backup automatici portano le chiavi. Su un altro computer Argo ti "
                           "chiede la password. Se la dimentichi, le chiavi nei backup non si recuperano."))
        r = QHBoxLayout()
        self.l_password = QLabel("")
        r.addWidget(self.l_password, 1)
        self.b_password = QPushButton("")
        self.b_password.clicked.connect(self.imposta_password)
        r.addWidget(self.b_password)
        self.b_togli_password = QPushButton(tr('Togli'))
        self.b_togli_password.clicked.connect(self.togli_password)
        r.addWidget(self.b_togli_password)
        lg.addLayout(r)
        self.gruppi.append(("backup_chiavi", g))

        # -- ripristino
        g = QGroupBox(tr('Ripristino'))
        lg = QVBoxLayout(g)
        lg.addWidget(_nota("I backup trovati nella cartella scelta e nelle cartelle di OneDrive e Google Drive, anche "
                           "quelli fatti su altri computer. Prima di ripristinare Argo fa da solo un backup di "
                           "sicurezza in Documenti › Argo › Backup › Prima del ripristino. Da un altro computer "
                           "arrivano le impostazioni comuni; modelli, audio e prestazioni restano quelli di qui."))
        self.t_backup = QTableWidget(0, 6)
        self.t_backup.setHorizontalHeaderLabels([tr('Data'), tr('Livello'), tr('Computer'), tr('Dove'), tr('Dimensione'), tr('Chiavi')])
        self.t_backup.verticalHeader().setVisible(False)
        self.t_backup.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t_backup.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t_backup.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t_backup.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.t_backup.setMinimumHeight(170)
        lg.addWidget(self.t_backup)
        r = QHBoxLayout()
        b = QPushButton(tr('↻ Aggiorna elenco'))
        b.clicked.connect(self.aggiorna_elenco)
        r.addWidget(b)
        r.addStretch(1)
        b = QPushButton(tr('Da un file…'))
        b.clicked.connect(self.ripristina_da_file)
        r.addWidget(b)
        b = QPushButton(tr('Ripristina…'))
        b.clicked.connect(self.ripristina_selezionato)
        r.addWidget(b)
        lg.addLayout(r)
        self.gruppi.append(("ripristino", g))

        # -- più computer
        g = QGroupBox(tr('Configurazione condivisa tra i tuoi computer (Mac e Windows)'))
        lg = QVBoxLayout(g)
        lg.addWidget(_nota("Con la stessa cartella cloud su più computer, Argo legge la configurazione all'avvio e "
                           "scrive la propria alla chiusura: impostazioni comuni, template delle relazioni, glossario, "
                           "collegamenti. Non si condividono mai: chiavi e token, modelli e indirizzo di Ollama, modello "
                           "e calcolo della trascrizione, microfono e audio, uso del computer, cartelle, canale degli "
                           "aggiornamenti. Se cambi qualcosa su due computer, vince la modifica più recente e l'altra "
                           "resta in un backup."))
        self.cb_condividi = QCheckBox(tr('Condividi la configurazione tra i miei computer'))
        self.cb_condividi.setChecked(bool(s.get("condivisione_attiva")))
        self.cb_condividi.toggled.connect(self._cambia_condivisione)
        lg.addWidget(self.cb_condividi)
        f = QFormLayout()
        self.c_condivisa = QComboBox()
        self.c_condivisa.activated.connect(lambda _i: self._scegli_cartella(self.c_condivisa, "condivisione_cartella",
                                                                            backup.SOTTOCARTELLA))
        f.addRow(tr('Cartella condivisa:'), self.c_condivisa)
        lg.addLayout(f)
        r = QHBoxLayout()
        self.l_condivisa = QLabel("")
        self.l_condivisa.setWordWrap(True)
        r.addWidget(self.l_condivisa, 1)
        self.b_sincronizza = QPushButton(tr('⇅ Sincronizza ora'))
        self.b_sincronizza.clicked.connect(self.sincronizza_ora)
        r.addWidget(self.b_sincronizza)
        lg.addLayout(r)
        self.gruppi.append(("piu_computer", g))
        self.aggiorna()

    # -------------------------------------------------------- stato
    def _salva(self, chiave, valore):
        s = core.carica_impostazioni()
        s[chiave] = valore
        core.salva_impostazioni(s)

    def aggiorna(self):
        s = core.carica_impostazioni()
        _riempi_cartelle(self.c_dove, s.get("backup_cartella") or backup.cartella_locale(),
                         backup.SOTTOCARTELLA + "/Backup", backup.cartella_locale())
        c = backup.cartella_backup()
        servizio = backup.nel_cloud(c)
        self.l_dove.setText(tr('☁️ Nel cloud ({servizio})', servizio=servizio) if servizio else tr('🔒 Su questo computer'))
        ultimi = s.get("backup_ultimo") or {}
        self.l_ultimo.setText("Ultimi backup: " + (", ".join(f"{backup.LIVELLI[k].lower()} {_quando(v)}"
                                                             for k, v in ultimi.items() if k in backup.LIVELLI)
                                                   or "nessuno"))
        if backup.password_impostata():
            self.l_password.setText(tr('🔐 Password impostata: chiavi e token entrano nei backup, cifrati.'))
            self.b_password.setText(tr('Cambia password…'))
        else:
            self.l_password.setText(tr('Nessuna password: chiavi e token restano fuori dai backup.'))
            self.b_password.setText(tr('Imposta password…'))
        self.b_togli_password.setVisible(backup.password_impostata())
        vietata = backup.condivisione_vietata()
        self.cb_condividi.setEnabled(not vietata)
        if vietata:
            self.cb_condividi.setToolTip(tr('Disattivata dai criteri della tua azienda'))
        prima_cloud = next(iter(backup.cartelle_cloud()), None)
        predefinita = s.get("condivisione_cartella") or (str(prima_cloud[1] / backup.SOTTOCARTELLA) if prima_cloud else "")
        _riempi_cartelle(self.c_condivisa, predefinita, backup.SOTTOCARTELLA,
                         Path.home() / "Documents" / backup.SOTTOCARTELLA)
        self.c_condivisa.setEnabled(self.cb_condividi.isChecked())
        self.b_sincronizza.setEnabled(backup.condivisione_attiva())
        ultimo = backup.stato_condivisa()
        if not backup.condivisione_attiva():
            self.l_condivisa.setText(tr('Spenta.'))
        elif ultimo:
            self.l_condivisa.setText(tr('Ultima configurazione condivisa: da {valore}, {quando}.', valore=ultimo[0], quando=_quando(ultimo[1])))
        else:
            self.l_condivisa.setText(tr('Ancora nessuna configurazione condivisa: la scrivo alla chiusura (o con «Sincronizza ora»).'))
        self.aggiorna_elenco()

    def aggiorna_elenco(self):
        self._trovati = backup.elenco()
        self.t_backup.setRowCount(0)
        for n, (f, m, byte) in enumerate(self._trovati):
            self.t_backup.insertRow(n)
            valori = [_quando(m.get("creato")), backup.LIVELLI.get(m.get("livello"), m.get("livello")),
                      m.get("computer", "") + (" (questo)" if m.get("id_computer") == backup.id_computer() else ""),
                      backup.nel_cloud(f.parent) or "Questo computer", _dimensione(byte),
                      "🔐" if "chiavi e token (cifrati)" in m.get("contenuto", []) else ""]
            for c, v in enumerate(valori):
                it = QTableWidgetItem(v)
                it.setToolTip(str(f))
                self.t_backup.setItem(n, c, it)

    def _scegli_cartella(self, combo, chiave, sotto):
        dato = combo.currentData()
        if dato == ALTRA:
            scelta = QFileDialog.getExistingDirectory(self, tr('Cartella'), str(Path.home()))
            if not scelta:
                self.aggiorna()
                return
            dato = scelta
        if backup.cloud_vietato() and backup.nel_cloud(dato):
            QMessageBox.information(self, tr('Cartella cloud'), tr('Le cartelle cloud sono disattivate dai criteri della tua azienda: scegli una cartella su questo computer.'))
            self.aggiorna()
            return
        self._salva(chiave, dato)
        self.aggiorna()
        if hasattr(self.finestra, "_aggiorna_badge"):
            self.finestra._aggiorna_badge()

    # -------------------------------------------------------- lavori in un thread
    def _esegui(self, titolo, fn, fine):
        """Lavoro con finestra di attesa; fine(risultato) o messaggio d'errore."""
        attesa = QProgressDialog(titolo, None, 0, 0, self)
        attesa.setWindowTitle(tr('Argo'))
        attesa.setWindowModality(Qt.WindowModal)
        attesa.setMinimumDuration(300)
        lav = attrezzi.Lavoro(lambda l: fn(l), self)
        lav.sig_stato.connect(attesa.setLabelText)
        lav.sig_fine.connect(lambda r: (attesa.close(), fine(r)))
        lav.sig_errore.connect(lambda e: (attesa.close(), self._errore(e)))
        self._lav = lav
        lav.start()

    def _errore(self, testo):
        if testo == "SERVE_PASSWORD":
            return
        QMessageBox.warning(self, tr('Backup'), testo)
        self.aggiorna()

    def fai_backup(self, livello):
        def lavoro(lav):
            with veglia.tieni("backup"):
                return backup.crea(livello, stato=lav.stato, stop=lav.fermato)
        self._esegui(f"Backup {backup.LIVELLI[livello].lower()} in corso…", lavoro, self._backup_fatto)

    def _backup_fatto(self, file):
        self.aggiorna()
        self.finestra.statusBar().showMessage(tr('✅ Backup salvato: {name}', name=file.name), 15000)

    # -------------------------------------------------------- password
    def imposta_password(self):
        d = QDialog(self)
        d.setWindowTitle(tr('Password dei backup'))
        lay = QVBoxLayout(d)
        lay.addWidget(_nota("Almeno 8 caratteri. Servirà per ripristinare chiavi e token su un altro computer: "
                            "conservala (per esempio nel tuo gestore di password). Se la cambi, i backup già fatti "
                            "restano apribili solo con la password vecchia."))
        f = QFormLayout()
        e1, e2 = QLineEdit(), QLineEdit()
        for e in (e1, e2):
            e.setEchoMode(QLineEdit.Password)
        f.addRow(tr('Password:'), e1)
        f.addRow(tr('Ripeti:'), e2)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        while d.exec() == QDialog.Accepted:
            if e1.text() != e2.text():
                QMessageBox.information(self, tr('Password'), tr('Le due password non coincidono.'))
                continue
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                backup.imposta_password(e1.text())
            except backup.ErroreBackup as err:
                QMessageBox.information(self, tr('Password'), str(err))
                continue
            finally:
                QApplication.restoreOverrideCursor()
            break
        self.aggiorna()

    def togli_password(self):
        if QMessageBox.question(self, tr('Togliere la password?'), tr('I prossimi backup non porteranno più chiavi e token. I backup già fatti restano cifrati con la password di prima.')) == QMessageBox.Yes:
            backup.imposta_password("")
            self.aggiorna()

    # -------------------------------------------------------- ripristino
    def ripristina_selezionato(self):
        r = self.t_backup.currentRow()
        if r < 0 or r >= len(getattr(self, "_trovati", [])):
            QMessageBox.information(self, tr('Ripristino'), tr("Scegli un backup dall'elenco."))
            return
        self._ripristina(self._trovati[r][0])

    def ripristina_da_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr('Backup di Argo'), str(backup.cartella_backup()), "Backup di Argo (*.zip)")
        if f:
            self._ripristina(Path(f))

    def _ripristina(self, file):
        m = backup.leggi_manifesto(file)
        if not m:
            QMessageBox.warning(self, tr('Ripristino'), tr('Questo file non è un backup di Argo.'))
            return
        stesso = m.get("id_computer") == backup.id_computer()
        livello = backup.LIVELLI.get(m.get("livello"), m.get("livello"))
        d = QDialog(self)
        d.setWindowTitle(tr('Ripristinare il backup?'))
        lay = QVBoxLayout(d)
        testo = (f"<b>Backup {livello.lower()}</b> del {_quando(m.get('creato'))}, da <b>{m.get('computer')}</b>"
                 f"{' (questo computer)' if stesso else ''}.<br><br>Sostituisce le impostazioni"
                 + (", il glossario e i dati (voci, incontri, clienti, Secondo cervello)" if m.get("livello") == "completo"
                    else " e il glossario")
                 + ". Prima faccio un backup di sicurezza dello stato attuale. Poi Argo si riavvia.")
        l = QLabel(testo)
        l.setWordWrap(True)
        lay.addWidget(l)
        cb_computer = QCheckBox(tr('Anche le impostazioni del singolo computer (modelli, audio, prestazioni)'))
        cb_computer.setChecked(stesso)
        cb_computer.setVisible(not stesso)
        lay.addWidget(cb_computer)
        segreti = backup.segreti_nel_backup(file)
        cb_segreti = QCheckBox(tr('Anche chiavi e token (cifrati)'))
        cb_segreti.setChecked(bool(segreti))
        cb_segreti.setVisible(bool(segreti))
        lay.addWidget(cb_segreti)
        bb = QDialogButtonBox()
        bb.addButton(tr('Ripristina e riavvia'), QDialogButtonBox.AcceptRole)
        bb.addButton(tr('Annulla'), QDialogButtonBox.RejectRole)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() != QDialog.Accepted:
            return
        password = None
        if cb_segreti.isChecked() and backup.serve_password(file):
            password, ok = QInputDialog.getText(self, tr('Password dei backup'), tr('Il backup viene da un altro computer: scrivi la password dei backup per ripristinare chiavi e token.'),
                                                QLineEdit.Password)
            if not ok:
                return
        anche = cb_computer.isChecked()
        con_segreti = cb_segreti.isChecked()

        def lavoro(lav):
            with veglia.tieni("ripristino"):
                return backup.ripristina(file, stato=lav.stato, anche_computer=anche, password=password,
                                         segreti=con_segreti)
        self._esegui("Ripristino in corso…", lavoro, self._ripristinato)

    def _ripristinato(self, esito):
        chiavi = f" Chiavi e token: {len(esito['segreti'])} ripristinati." if esito.get("segreti") else ""
        QMessageBox.information(self, tr('Ripristino completato'), tr('Ripristinato il backup del {quando} da {computer}.{chiavi}\n\nLo stato di prima è in:\n{sicurezza}\n\nArgo ora si riavvia.', quando=_quando(esito['creato']), computer=esito['computer'], chiavi=chiavi, sicurezza=esito['sicurezza']))
        import aggiornamenti
        self.finestra._senza_backup_alla_chiusura = True  # appena ripristinato: alla chiusura niente backup
        aggiornamenti.riavvia()
        QApplication.quit()

    # -------------------------------------------------------- più computer
    def _cambia_condivisione(self, acceso):
        s = core.carica_impostazioni()
        s["condivisione_attiva"] = bool(acceso)
        if acceso and not s.get("condivisione_cartella"):
            dato = self.c_condivisa.currentData()
            if dato and dato != ALTRA:
                s["condivisione_cartella"] = dato
        if not acceso:
            s.pop("condivisione_impronta", None)
        core.salva_impostazioni(s)
        if acceso and backup.condivisione_attiva():
            self.sincronizza_ora()
        self.aggiorna()
        if hasattr(self.finestra, "_aggiorna_badge"):
            self.finestra._aggiorna_badge()

    def sincronizza_ora(self):
        try:
            da = backup.leggi_condivisa()
            scritta = backup.scrivi_condivisa(forza=not da and backup.stato_condivisa() is None)
        except Exception as e:
            QMessageBox.warning(self, tr('Configurazione condivisa'), str(e))
            return
        self.aggiorna()
        if da:
            if QMessageBox.question(self, tr('Configurazione aggiornata'),
                                    tr('Ho preso la configurazione da {da}. Per vederla ovunque Argo deve riavviarsi. Riavvio ora?', da=da)) == QMessageBox.Yes:
                import aggiornamenti
                aggiornamenti.riavvia()
                QApplication.quit()
        else:
            self.finestra.statusBar().showMessage("Configurazione condivisa " + ("pubblicata." if scritta else
                                                                                 "già allineata."), 10000)


def alla_chiusura(finestra):
    """Dalla closeEvent: backup alla chiusura e configurazione condivisa. Non blocca mai la chiusura."""
    if getattr(finestra, "_senza_backup_alla_chiusura", False):
        return
    s = core.carica_impostazioni()
    livello = s.get("backup_alla_chiusura", "configurazione")
    try:
        backup.scrivi_condivisa()
    except Exception as e:
        finestra.statusBar().showMessage(tr('Configurazione condivisa non scritta: {e}', e=e))
    if not livello:
        return
    attesa = QProgressDialog(tr('Backup {lower} prima di chiudere…', lower=backup.LIVELLI.get(livello, livello).lower()), tr('Salta'),
                             0, 0, finestra)
    attesa.setWindowTitle(tr('Argo'))
    attesa.setWindowModality(Qt.ApplicationModal)
    attesa.setMinimumDuration(500)
    lav = attrezzi.Lavoro(lambda l: backup.crea(livello, stato=l.stato, stop=l.fermato), finestra)
    lav.sig_stato.connect(attesa.setLabelText)
    lav.start()
    while lav.isRunning():
        QApplication.processEvents()
        if attesa.wasCanceled():
            lav.ferma()
        time.sleep(0.05)
    attesa.close()


def periodico(finestra):
    """Dal timer: se è ora del backup programmato, lo fa in un thread."""
    livello = backup.da_fare_periodico()
    if not livello or getattr(finestra, "_lav_backup", None):
        return

    def lavoro(lav):
        with veglia.tieni("backup programmato"):
            return backup.crea(livello, stato=lav.stato, stop=lav.fermato)
    lav = attrezzi.Lavoro(lavoro, finestra)
    lav.sig_fine.connect(lambda f: (setattr(finestra, "_lav_backup", None),
                                    finestra.statusBar().showMessage(tr('✅ Backup programmato salvato: {name}', name=f.name), 10000)))
    lav.sig_errore.connect(lambda e: (setattr(finestra, "_lav_backup", None),
                                      finestra.statusBar().showMessage(tr('Backup programmato non riuscito: {e}', e=e), 15000)))
    finestra._lav_backup = lav
    lav.start()
