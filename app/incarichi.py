"""incarichi.py - «Incarichi» in stile Cowork: una ricetta esegue più attrezzi di Argo in fila, con un piano
visibile, una pausa di conferma sui nomi e i risultati salvati come file NUOVI nella cartella della call.

Ricetta disponibile: Call → verbale + mail di recap + task.
Tutto in locale: trascrizione con WhisperX (coda del Trascrittore), testi con il modello in Ollama.
"""
import csv
import json
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

import argo_attrezzi as attrezzi
import esporta_word as word
import llm_locale as llm
import m365
import tema
import voci_core as core

LINGUE_MAIL = [("Italiano", "it"), ("English", "en"), ("Deutsch", "de")]
TONI = ["cordiale e professionale", "formale", "informale e breve"]
FORMATO_DATA = "%d/%m/%Y"


# =============================================================== logica (senza interfaccia)
def file_nuovo(cartella, nome):
    """Non sovrascrive mai: se il file esiste aggiunge _2, _3…"""
    p = Path(cartella) / nome
    if not p.exists():
        return p
    i = 2
    while True:
        q = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not q.exists():
            return q
        i += 1


def scrivi_verbale(lav, trascrizione):
    istruzione = attrezzi.MODELLI_VERBALE["Verbale della riunione"]
    blocchi = llm.spezza(trascrizione, 9000)
    sistema = {"role": "system", "content": attrezzi.SISTEMA_VERBALE}
    if len(blocchi) == 1:
        return attrezzi.chat_llm(lav, [sistema, {"role": "user", "content": f"{istruzione}\n\nTRASCRIZIONE:\n{trascrizione}"}],
                                 mostra=False)
    appunti = []
    for i, b in enumerate(blocchi, 1):
        if lav.fermato():
            return ""
        lav.stato(f"Riunione lunga: leggo la parte {i} di {len(blocchi)}…")
        appunti.append(attrezzi.chat_llm(lav, [sistema, {"role": "user", "content":
                                         "Estrai in punti elenco: partecipanti, argomenti, decisioni, azioni (con "
                                         f"responsabile e scadenza se dette), punti aperti.\n\nPARTE {i}:\n{b}"}], mostra=False))
    return attrezzi.chat_llm(lav, [sistema, {"role": "user", "content": f"{istruzione}\n\nAPPUNTI DALLE PARTI DELLA RIUNIONE:\n"
                                                                     + "\n\n".join(appunti)}], mostra=False)


def scrivi_mail(lav, verbale, lingua="it", tono=TONI[0], destinatari="", note=""):
    nome_lingua = {"it": "italiano", "en": "inglese", "de": "tedesco"}.get(lingua, "italiano")
    richiesta = (
        f"Scrivi in {nome_lingua} una mail di recap della riunione, tono {tono}. "
        "Prima riga: 'Oggetto: …'. Poi saluto, ringraziamento breve, punti principali, decisioni, "
        "prossimi passi con responsabile e scadenza, chiusura cordiale senza firma. Massimo 220 parole. "
        "Usa SOLO le informazioni del verbale: se un dato manca non inventarlo.")
    if destinatari.strip():
        richiesta += f" La mail è indirizzata a: {destinatari.strip()}."
    if note.strip():
        richiesta += f" Indicazioni aggiuntive: {note.strip()}"
    return attrezzi.chat_llm(lav, [{"role": "system", "content": "Sei un assistente che scrive mail di lavoro chiare."},
                                   {"role": "user", "content": f"{richiesta}\n\nVERBALE:\n{verbale}"}], mostra=False)


def estrai_task(lav, verbale, data_riunione):
    richiesta = (
        "Dal verbale estrai le azioni da fare come JSON: una lista di oggetti con i campi "
        '"titolo" (breve, inizia con un verbo), "responsabile" (nome come nel verbale, oppure ""), '
        '"scadenza" (come detta nel verbale, oppure ""), "scadenza_iso" (data AAAA-MM-GG se ricavabile con certezza '
        f'sapendo che la riunione è del {data_riunione}, altrimenti null). '
        "Rispondi SOLO con il JSON, senza testo prima o dopo. Non inventare azioni.")
    risposta = attrezzi.chat_llm(lav, [{"role": "system", "content": "Estrai dati strutturati. Rispondi solo con JSON valido."},
                                       {"role": "user", "content": f"{richiesta}\n\nVERBALE:\n{verbale}"}],
                                 temperatura=0.1, mostra=False)
    return analizza_task(risposta)


def analizza_task(risposta):
    """Legge la lista di task anche se il modello aggiunge testo o blocchi ```json attorno."""
    m = re.search(r"\[.*\]", risposta or "", re.S)
    if not m:
        return []
    try:
        dati = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for d in dati if isinstance(dati, list) else []:
        if isinstance(d, dict) and str(d.get("titolo", "")).strip():
            iso = d.get("scadenza_iso")
            out.append({"titolo": str(d["titolo"]).strip(), "responsabile": str(d.get("responsabile") or "").strip(),
                        "scadenza": str(d.get("scadenza") or "").strip(),
                        "scadenza_iso": iso if isinstance(iso, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else None})
    return out


# =============================================================== interfaccia
STATI = {"attesa": "○", "corso": "◐", "fatto": "●", "chiede": "?", "errore": "✕", "saltato": "–"}


class Passo(QFrame):
    def __init__(self, titolo, parent=None):
        super().__init__(parent)
        self.setProperty("ruolo", "scheda")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        self.icona = QLabel(STATI["attesa"])
        self.icona.setFixedWidth(26)
        self.icona.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.titolo = QLabel(titolo)
        self.titolo.setStyleSheet("font-weight: 600;")
        self.dettaglio = QLabel("")
        self.dettaglio.setProperty("ruolo", "tenue")
        self.dettaglio.setWordWrap(True)
        col.addWidget(self.titolo)
        col.addWidget(self.dettaglio)
        self.extra = QVBoxLayout()
        col.addLayout(self.extra)
        self.azioni = QHBoxLayout()
        self.azioni.setSpacing(6)
        self.azioni.addStretch()
        col.addLayout(self.azioni)
        self.icona.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        lay.addWidget(self.icona)
        lay.addLayout(col, 1)
        self.imposta("attesa")

    def imposta(self, stato, dettaglio=None):
        c = tema.colori()
        colore = {"attesa": c["debole"], "corso": c["accento"], "fatto": c["ok"], "chiede": c["warn"],
                  "errore": c["err"], "saltato": c["debole"]}[stato]
        self.icona.setText(STATI[stato])
        self.icona.setStyleSheet(f"color: {colore}; font-size: 18px; font-weight: 700;")
        if dettaglio is not None:
            self.dettaglio.setText(dettaglio)

    def pulisci_azioni(self):
        for l in (self.azioni, self.extra):
            while l.count():
                it = l.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
        self.azioni.addStretch()

    def aggiungi_azione(self, testo, fn, primario=False):
        b = QPushButton(testo)
        if primario:
            b.setProperty("primario", True)
        b.clicked.connect(fn)
        self.azioni.addWidget(b)
        return b


class SchedaIncarichi(QWidget):
    PASSI = ["Trascrizione con i parlanti", "Nomi dei parlanti", "Verbale", "Verbale in Word", "Mail di recap",
             "Task dalle azioni", "Bozza in Outlook", "Task in Planner"]

    def __init__(self, finestra, parent=None):
        super().__init__(parent)
        self.finestra = finestra
        self.setObjectName("pagina")
        self.file = None
        self.json = None
        self.job = None
        self.lavoro = None
        self.in_corso = False
        self.prodotti = []
        self.registro = None
        self.verbale = ""
        self.task = []
        esterno = QHBoxLayout(self)
        esterno.setContentsMargins(0, 0, 0, 0)
        sp = QSplitter(Qt.Horizontal)
        esterno.addWidget(sp)

        # ---- colonna 1: ricetta e richiesta
        sx = QWidget()
        l1 = QVBoxLayout(sx)
        l1.setContentsMargins(20, 16, 14, 14)
        l1.setSpacing(10)
        t = QLabel("Incarichi")
        t.setProperty("ruolo", "titolo")
        s = QLabel("Argo esegue più attrezzi in fila. Tu approvi i passi importanti; i risultati sono file nuovi "
                   "nella cartella della call, niente viene sovrascritto o inviato.")
        s.setProperty("ruolo", "tenue")
        s.setWordWrap(True)
        l1.addWidget(t)
        l1.addWidget(s)
        l1.addWidget(self._sezione("RICETTA"))
        r = QHBoxLayout()
        for i, testo in enumerate(["Call → recap + task", "Contratti → confronto", "Riunione DE → verbale IT"]):
            b = QPushButton(testo)
            b.setProperty("pillola", True)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setEnabled(i == 0)
            if i:
                b.setToolTip("Prossimamente")
            r.addWidget(b)
        r.addStretch()
        l1.addLayout(r)
        l1.addWidget(self._sezione("CALL"))
        rf = QHBoxLayout()
        self.l_file = QLabel("Nessun file scelto")
        self.l_file.setWordWrap(True)
        b_file = QPushButton("Scegli audio o video…")
        b_file.clicked.connect(self.scegli_file)
        rf.addWidget(self.l_file, 1)
        rf.addWidget(b_file)
        l1.addLayout(rf)
        rp = QHBoxLayout()
        rp.addWidget(QLabel("Partecipanti:"))
        self.s_parl = QSpinBox()
        self.s_parl.setRange(0, 20)
        self.s_parl.setSpecialValueText("Auto")
        rp.addWidget(self.s_parl)
        rp.addStretch()
        l1.addLayout(rp)
        l1.addWidget(self._sezione("MAIL DI RECAP"))
        rd = QHBoxLayout()
        self.e_dest = QLineEdit()
        self.e_dest.setPlaceholderText("Destinatari (facoltativo), es. Markus Huber <markus@azienda.it>")
        self.b_cal = QPushButton("Dal calendario")
        self.b_cal.setToolTip("Microsoft 365: prende titolo e partecipanti della riunione registrata")
        self.b_cal.clicked.connect(self.dal_calendario)
        rd.addWidget(self.e_dest, 1)
        rd.addWidget(self.b_cal)
        l1.addLayout(rd)
        self.l_riunione = QLabel("")
        self.l_riunione.setProperty("ruolo", "tenue")
        self.l_riunione.setWordWrap(True)
        l1.addWidget(self.l_riunione)
        rl = QHBoxLayout()
        self.c_lingua = QComboBox()
        for n, v in LINGUE_MAIL:
            self.c_lingua.addItem(n, v)
        self.c_tono = QComboBox()
        self.c_tono.addItems(TONI)
        rl.addWidget(QLabel("Lingua:"))
        rl.addWidget(self.c_lingua)
        rl.addWidget(QLabel("Tono:"))
        rl.addWidget(self.c_tono, 1)
        l1.addLayout(rl)
        self.e_note = QPlainTextEdit()
        self.e_note.setPlaceholderText("Indicazioni aggiuntive (facoltative), es. «metti in evidenza le scadenze»")
        self.e_note.setMaximumHeight(80)
        l1.addWidget(self.e_note)
        l1.addStretch()
        self.b_esegui = QPushButton("▶ Esegui l'incarico")
        self.b_esegui.setProperty("primario", True)
        self.b_esegui.clicked.connect(self.esegui_o_ferma)
        l1.addWidget(self.b_esegui)
        sp.addWidget(sx)

        # ---- colonna 2: piano
        mid = QWidget()
        l2 = QVBoxLayout(mid)
        l2.setContentsMargins(14, 16, 14, 14)
        l2.setSpacing(8)
        l2.addWidget(self._sezione(f"PIANO · {len(self.PASSI)} PASSI"))
        self.passi = []
        for titolo in self.PASSI:
            p = Passo(titolo)
            self.passi.append(p)
            l2.addWidget(p)
        l2.addStretch()
        self.stato = QLabel("Scegli la call e premi «Esegui».")
        self.stato.setProperty("ruolo", "tenue")
        self.stato.setWordWrap(True)
        l2.addWidget(self.stato)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(mid)
        sp.addWidget(scroll)

        # ---- colonna 3: risultati
        dx = QWidget()
        l3 = QVBoxLayout(dx)
        l3.setContentsMargins(14, 16, 20, 14)
        l3.addWidget(self._sezione("RISULTATI"))
        self.ris = QTabWidget()
        self.t_mail = QPlainTextEdit()
        self.t_mail.setPlaceholderText("La mail di recap comparirà qui. Puoi modificarla prima di copiarla.")
        self.t_task = QTableWidget(0, 3)
        self.t_task.setHorizontalHeaderLabels(["Task", "Responsabile", "Scadenza"])
        self.t_task.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t_task.verticalHeader().setVisible(False)
        self.t_task.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t_verb = QPlainTextEdit()
        self.t_verb.setReadOnly(True)
        self.l_file_prod = QLabel("")
        self.l_file_prod.setWordWrap(True)
        self.l_file_prod.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ris.addTab(self.t_mail, "Mail")
        self.ris.addTab(self.t_task, "Task")
        self.ris.addTab(self.t_verb, "Verbale")
        self.ris.addTab(self.l_file_prod, "File")
        l3.addWidget(self.ris, 1)
        rb = QHBoxLayout()
        b_cm = QPushButton("Copia mail")
        b_cm.clicked.connect(lambda: attrezzi.copia(self.t_mail.toPlainText()))
        b_ct = QPushButton("Copia task")
        b_ct.clicked.connect(self.copia_task)
        b_cart = QPushButton("Apri cartella")
        b_cart.clicked.connect(lambda: self.file and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file.parent))))
        for b in (b_cm, b_ct, b_cart):
            rb.addWidget(b)
        rb.addStretch()
        l3.addLayout(rb)
        sp.addWidget(dx)
        sp.setSizes([360, 380, 460])

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._controlla_trascrizione)
        self.persone = []
        self.aggiorna_m365()

    def aggiorna_m365(self):
        acc = m365.account()
        self.b_cal.setEnabled(bool(acc))
        if not acc:
            self.b_cal.setToolTip("Collega Microsoft 365 in Impostazioni per usarlo")

    def _sezione(self, testo):
        l = QLabel(testo)
        l.setProperty("ruolo", "sezione")
        return l

    # ------------------------------------------------------------ preparazione
    def scegli_file(self):
        filtro = "Audio o video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm *.m4v);;Tutti i file (*)"
        f, _ = QFileDialog.getOpenFileName(self, "Registrazione della call", str(Path.home()), filtro)
        if f:
            self.imposta_file(f)

    def imposta_file(self, f):
        self.file = Path(f)
        j = core.json_atteso(self.file)
        gia = j.exists()
        self.l_file.setText(f"<b>{self.file.name}</b><br><span>{'già trascritta: salto la trascrizione' if gia else 'da trascrivere'}</span>")
        for p in self.passi:
            p.imposta("attesa", "")
            p.pulisci_azioni()

    def dal_calendario(self):
        if not self.file:
            QMessageBox.information(self, "Calendario", "Scegli prima la registrazione della call.")
            return
        from datetime import datetime
        quando = datetime.fromtimestamp(self.file.stat().st_mtime).astimezone()
        self.l_riunione.setText("Cerco nel calendario…")
        lav = attrezzi.Lavoro(lambda _l: m365.riunione_vicina(quando), self)

        def fatto(ev):
            self._lav_cal = None
            if not ev:
                self.l_riunione.setText("Nessuna riunione trovata nel calendario vicino all'ora della registrazione.")
                return
            self.persone = ev["persone"]
            self.e_dest.setText(", ".join(f"{p['nome']} <{p['email']}>" for p in ev["persone"]))
            self.l_riunione.setText(f"Riunione: «{ev['oggetto']}» · {ev['inizio']} · {len(ev['persone'])} persone. "
                                    "Togli dai destinatari chi non deve ricevere il recap.")

        lav.sig_fine.connect(fatto)
        lav.sig_errore.connect(lambda e: self.l_riunione.setText(f"Calendario non disponibile: {e}"))
        self._lav_cal = lav
        lav.start()

    def log(self, testo):
        self.stato.setText(testo)
        if self.registro:
            with open(self.registro, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {testo}\n")

    # ------------------------------------------------------------ esecuzione
    def esegui_o_ferma(self):
        if self.in_corso:
            self.ferma()
            return
        if not self.file or not self.file.exists():
            QMessageBox.information(self, "Incarico", "Scegli prima la registrazione della call.")
            return
        if not attrezzi.pronto_llm(self):
            return
        self.in_corso = True
        self.b_esegui.setText("■ Ferma l'incarico")
        self.prodotti, self.task, self.verbale = [], [], ""
        self.t_mail.clear()
        self.t_verb.clear()
        self.t_task.setRowCount(0)
        self.registro = file_nuovo(self.file.parent, f"{self.file.stem}_incarico_registro.txt")
        self.log(f"Incarico avviato: Call → recap + task su {self.file.name}")
        for p in self.passi:
            p.imposta("attesa", "")
            p.pulisci_azioni()
        self.passo_trascrizione()

    def ferma(self):
        self.timer.stop()
        if self.lavoro:
            self.lavoro.ferma()
        self._fine("Incarico fermato.")

    def _fine(self, msg):
        self.in_corso = False
        self.b_esegui.setText("▶ Esegui l'incarico")
        self.log(msg)
        self.l_file_prod.setText("<br>".join(str(p) for p in self.prodotti) or "Nessun file creato.")

    def _errore(self, i, msg):
        self.passi[i].imposta("errore", msg)
        self._fine(f"Errore al passo «{self.PASSI[i]}»: {msg}")

    # 1. trascrizione
    def passo_trascrizione(self):
        p = self.passi[0]
        self.json = core.json_atteso(self.file)
        if self.json.exists():
            p.imposta("saltato", "Già trascritta: uso la trascrizione esistente.")
            self.log("Trascrizione già presente.")
            return self.passo_nomi()
        fw = self.finestra
        self.job = next((j for j in fw.jobs if Path(j["file"]) == self.file), None)
        if self.job is None:
            fw.aggiungi_file([str(self.file)])
            self.job = next((j for j in fw.jobs if Path(j["file"]) == self.file), None)
        if self.job is None:
            return self._errore(0, "formato del file non supportato")
        self.job.update(parlanti=self.s_parl.value(), stato="In attesa", progresso=0, nota="dall'incarico")
        fw._ridisegna_coda()
        fw._salva_coda()
        if not fw.in_esecuzione:
            fw.avvia_o_ferma()
        p.imposta("corso", "In coda nel Trascrittore…")
        self.log("Trascrizione avviata nella coda del Trascrittore.")
        self.timer.start(1000)

    def _controlla_trascrizione(self):
        j = self.job
        if not j:
            return
        stato = j.get("stato")
        if stato == "Completata":
            self.timer.stop()
            self.json = Path(j["json"])
            self.passi[0].imposta("fatto", j.get("nota", "Completata"))
            self.log("Trascrizione completata.")
            self.passo_nomi()
        elif stato in ("Errore", "Interrotta"):
            self.timer.stop()
            self._errore(0, j.get("nota") or stato)
        else:
            self.passi[0].imposta("corso", f"{j.get('nota') or stato} · {int(j.get('progresso', 0))}%")

    # 2. nomi: pausa di conferma
    def passo_nomi(self):
        p = self.passi[1]
        try:
            out, mappa, _, _ = core.identifica(self.json)
        except Exception as e:
            return self._errore(1, f"lettura della trascrizione: {e}")
        self.txt = Path(out)
        nomi = sorted(set(mappa.values()))
        p.imposta("chiede", "Trovati: " + ", ".join(nomi) + ". Controlla i nomi prima di continuare.")
        p.pulisci_azioni()
        p.aggiungi_azione("Correggi nomi…", self._rivedi_nomi)
        p.aggiungi_azione("Conferma", self._nomi_confermati, primario=True)
        self.log("In attesa di conferma dei nomi dei parlanti.")

    def _rivedi_nomi(self):
        if self.finestra.rivedi_json(self.json):
            self.passo_nomi()

    def _nomi_confermati(self):
        if not self.in_corso:
            return
        p = self.passi[1]
        p.pulisci_azioni()
        out, mappa, _, _ = core.identifica(self.json)
        self.txt = Path(out)
        p.imposta("fatto", ", ".join(sorted(set(mappa.values()))))
        self.log("Nomi confermati.")
        self.passo_llm()

    # 3-6. passi con il modello locale
    def passo_llm(self):
        trascrizione = self.txt.read_text(encoding="utf-8", errors="replace")
        lingua, tono = self.c_lingua.currentData(), self.c_tono.currentText()
        dest, note = self.e_dest.text(), self.e_note.toPlainText()
        data = time.strftime(FORMATO_DATA, time.localtime(self.file.stat().st_mtime))
        stem = self.file.stem

        def fn(lav):
            esiti = {}
            lav.stato("2|corso|Scrivo il verbale…")
            esiti["verbale"] = scrivi_verbale(lav, trascrizione)
            if lav.fermato():
                return esiti
            f = file_nuovo(self.file.parent, f"{stem}_verbale.md")
            f.write_text(esiti["verbale"] + "\n", encoding="utf-8")
            esiti["f_verbale"] = f
            lav.stato(f"2|fatto|{f.name}")
            lav.stato("3|corso|Creo il documento Word…")
            fw = word.salva_docx(esiti["verbale"], file_nuovo(self.file.parent, f"{stem}_verbale.docx"),
                                 "Verbale della riunione", f"{stem} · {data}")
            esiti["f_word"] = fw
            lav.stato(f"3|fatto|{Path(fw).name}")
            lav.stato("4|corso|Scrivo la mail di recap…")
            esiti["mail"] = scrivi_mail(lav, esiti["verbale"], lingua, tono, dest, note)
            if lav.fermato():
                return esiti
            fm = file_nuovo(self.file.parent, f"{stem}_recap_mail.txt")
            fm.write_text(esiti["mail"] + "\n", encoding="utf-8")
            esiti["f_mail"] = fm
            lav.stato(f"4|fatto|{fm.name}")
            lav.stato("5|corso|Estraggo i task dalle azioni…")
            esiti["task"] = estrai_task(lav, esiti["verbale"], data)
            ft = file_nuovo(self.file.parent, f"{stem}_task.csv")
            with open(ft, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["Task", "Responsabile", "Scadenza", "Scadenza (data)"])
                for t in esiti["task"]:
                    w.writerow([t["titolo"], t["responsabile"], t["scadenza"], t["scadenza_iso"] or ""])
            fj = ft.with_suffix(".json")
            fj = file_nuovo(fj.parent, fj.name)
            fj.write_text(json.dumps(esiti["task"], ensure_ascii=False, indent=1), encoding="utf-8")
            esiti["f_task"] = ft
            lav.stato(f"5|fatto|{len(esiti['task'])} task · {ft.name}")
            return esiti

        self.lavoro = attrezzi.Lavoro(fn, self)
        self.lavoro.sig_stato.connect(self._stato_llm)
        self.lavoro.sig_fine.connect(self._fine_llm)
        self.lavoro.sig_errore.connect(lambda e: self._errore(self._passo_attuale, e))
        self._passo_attuale = 2
        self.lavoro.start()

    def _stato_llm(self, testo):
        parti = testo.split("|", 2)
        if len(parti) == 3 and parti[0].isdigit():
            i, st, det = int(parti[0]), parti[1], parti[2]
            self._passo_attuale = i
            self.passi[i].imposta(st, det)
            self.log(f"{self.PASSI[i]}: {det}")
        else:
            self.passi[self._passo_attuale].imposta("corso", testo)

    def _fine_llm(self, esiti):
        self.lavoro = None
        self.verbale = esiti.get("verbale", "")
        self.t_verb.setPlainText(self.verbale)
        self.t_mail.setPlainText(esiti.get("mail", ""))
        self.task = esiti.get("task", [])
        self.t_task.setRowCount(len(self.task))
        for r, t in enumerate(self.task):
            for c, v in enumerate((t["titolo"], t["responsabile"] or "non indicato", t["scadenza"] or "non indicata")):
                self.t_task.setItem(r, c, QTableWidgetItem(v))
        for k in ("f_verbale", "f_word", "f_mail", "f_task"):
            if esiti.get(k):
                self.prodotti.append(esiti[k])
        if self.registro:
            self.prodotti.append(self.registro)
        if not self.in_corso:
            return
        if "f_task" not in esiti:
            return self._fine("Incarico fermato prima della fine.")
        self.ris.setCurrentWidget(self.t_mail)
        self.passo_outlook()

    # 7-8. Microsoft 365 (facoltativo, sempre con conferma)
    def passo_outlook(self):
        p = self.passi[6]
        if not m365.account():
            p.imposta("saltato", "Microsoft 365 non collegato: copia la mail con «Copia mail».")
            self.passi[7].imposta("saltato", "Microsoft 365 non collegato: copia i task con «Copia task».")
            return self._fine(f"Incarico completato: {len(self.task)} task, mail di recap pronta. Rileggi prima di inviare.")
        self.dest = m365.destinatari_da_testo(self.e_dest.text())
        chi = ", ".join(d["email"] for d in self.dest) or "nessun destinatario (li aggiungi in Outlook)"
        p.imposta("chiede", f"Creo una BOZZA (non la invio) per: {chi}. Prima puoi modificare la mail a destra.")
        p.pulisci_azioni()
        p.aggiungi_azione("Salta", lambda: (p.pulisci_azioni(), p.imposta("saltato", "Saltato."), self.passo_planner()))
        p.aggiungi_azione("Crea bozza", self._crea_bozza, primario=True)
        self.log("In attesa di conferma per la bozza in Outlook.")

    def _crea_bozza(self):
        p = self.passi[6]
        p.pulisci_azioni()
        p.imposta("corso", "Creo la bozza in Outlook…")
        mail = self.t_mail.toPlainText()
        lav = attrezzi.Lavoro(lambda _l: m365.crea_bozza(mail, self.dest), self)

        def ok(r):
            p.imposta("fatto", f"Bozza «{r['oggetto']}» nelle Bozze di Outlook.")
            if r.get("link"):
                p.aggiungi_azione("Apri", lambda: QDesktopServices.openUrl(QUrl(r["link"])))
            self.log(f"Bozza creata in Outlook: {r['oggetto']}")
            self.passo_planner()

        lav.sig_fine.connect(ok)
        lav.sig_errore.connect(lambda e: (p.imposta("errore", e), self.log(f"Outlook: {e}"), self.passo_planner()))
        self._lav_m365 = lav
        lav.start()

    def passo_planner(self):
        p = self.passi[7]
        if not self.task:
            p.imposta("saltato", "Nessun task da creare.")
            return self._fine("Incarico completato.")
        p.imposta("corso", "Leggo i tuoi piani di Planner…")
        lav = attrezzi.Lavoro(lambda _l: m365.piani(), self)

        def scelta(piani):
            if not piani:
                p.imposta("errore", "Nessun piano Planner trovato: creane uno in Planner o Teams.")
                return self._fine("Incarico completato (senza Planner).")
            self.c_piano = QComboBox()
            self.c_piano.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.c_piano.setMinimumContentsLength(14)
            for pi in piani:
                self.c_piano.addItem(pi["titolo"], pi["id"])
            p.imposta("chiede", f"Creo {len(self.task)} task nel piano scelto, nel primo bucket. "
                                "Assegno le persone riconosciute tra i partecipanti della riunione.")
            p.pulisci_azioni()
            p.extra.addWidget(self.c_piano)
            p.aggiungi_azione("Salta", lambda: (p.pulisci_azioni(), p.imposta("saltato", "Saltato."),
                                                self._fine("Incarico completato.")))
            p.aggiungi_azione("Crea task", self._crea_task, primario=True)
            self.log("In attesa di conferma per i task in Planner.")

        lav.sig_fine.connect(scelta)
        lav.sig_errore.connect(lambda e: (p.imposta("errore", e), self._fine("Incarico completato (senza Planner).")))
        self._lav_m365 = lav
        lav.start()

    def _crea_task(self):
        p = self.passi[7]
        piano = self.c_piano.currentData()
        nome_piano = self.c_piano.currentText()
        p.pulisci_azioni()
        p.imposta("corso", f"Creo i task in «{nome_piano}»…")
        task, persone = list(self.task), list(self.persone) or m365.destinatari_da_testo(self.e_dest.text())

        def fn(_l):
            b = m365.bucket(piano)
            if not b:
                raise m365.ErroreM365("il piano non ha bucket")
            utenti = m365.trova_utenti(persone)
            return m365.crea_task(piano, b[0]["id"], task, utenti), b[0]["nome"]

        lav = attrezzi.Lavoro(fn, self)

        def ok(r):
            creati, nome_bucket = r
            assegnati = sum(1 for c in creati if c["assegnato"])
            p.imposta("fatto", f"{len(creati)} task in «{nome_piano}» › {nome_bucket} · {assegnati} assegnati.")
            self.log(f"Planner: {len(creati)} task creati in {nome_piano} ({assegnati} assegnati).")
            self._fine(f"Incarico completato: bozza in Outlook e {len(creati)} task in Planner. Rileggi prima di inviare.")

        lav.sig_fine.connect(ok)
        lav.sig_errore.connect(lambda e: (p.imposta("errore", e), self._fine(f"Planner: {e}")))
        self._lav_m365 = lav
        lav.start()

    def copia_task(self):
        righe = []
        for r in range(self.t_task.rowCount()):
            righe.append("\t".join(self.t_task.item(r, c).text() if self.t_task.item(r, c) else "" for c in range(3)))
        attrezzi.copia("\n".join(righe))
