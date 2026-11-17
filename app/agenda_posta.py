"""agenda_posta.py - schede «Agenda» e «Posta AI» (Microsoft 365, facoltativo).

Agenda: riunioni dal calendario; per ciascuna Prepara (briefing locale), Registra (microfono), Incarico.
Posta AI: elenco leggero della posta in arrivo; riassunto, «cosa mi si chiede», bozza di risposta e task,
con il modello LOCALE. Il testo delle mail arriva dal tuo tenant e viene elaborato solo su questo computer.
Argo non invia mai mail: le risposte finiscono nelle Bozze di Outlook.
"""
import html
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

import argo_attrezzi as attrezzi
import incarichi
import m365
import tema
import voci_core as core

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]


def etichetta_giorno(dt):
    oggi = datetime.now().date()
    d = dt.date()
    if d == oggi:
        return "Oggi"
    if (d - oggi).days == 1:
        return "Domani"
    return f"{GIORNI[d.weekday()].capitalize()} {d.day} {MESI[d.month - 1]}"


def cartella_registrazioni():
    c = core.carica_impostazioni().get("cartella_registrazioni") or str(Path.home() / "Documents" / "Argo" / "Registrazioni")
    p = Path(c)
    p.mkdir(parents=True, exist_ok=True)
    return p


def nome_sicuro(testo):
    return "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in testo).strip()[:60] or "Riunione"


class SchedaM365(QWidget):
    """Base: mostra un invito a collegare Microsoft 365 finché non è collegato."""
    TITOLO = ""
    SOTTO = ""

    def __init__(self, finestra, parent=None):
        super().__init__(parent)
        self.finestra = finestra
        self.setObjectName("pagina")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pile = QStackedWidget()
        lay.addWidget(self.pile)
        # Stato vuoto (Stile Argo): la pagina conserva titolo e sottotitolo, poi filigrana, motto e cosa fare
        vuota = QWidget()
        vl = QVBoxLayout(vuota)
        vl.setContentsMargins(20, 16, 20, 12)
        self.titolo(vl)
        self.vuoto = tema.StatoVuoto("", "Collega Microsoft 365…",
                                     lambda: self.finestra.vai_a_impostazioni("m365"))
        vl.addWidget(self.vuoto, 1)
        self.pile.addWidget(vuota)
        self.contenuto = QWidget()
        self.pile.addWidget(self.contenuto)

    def titolo(self, lay, extra=None):
        r = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(self.TITOLO)
        t.setProperty("ruolo", "titolo")
        s = QLabel(self.SOTTO)
        s.setProperty("ruolo", "tenue")
        s.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(s)
        r.addLayout(col, 1)
        for w in extra or []:
            r.addWidget(w)
        lay.addLayout(r)

    def motivo_non_pronto(self):
        if not m365.account():
            return "Microsoft 365 non è collegato.\nCollegalo nelle Impostazioni per vedere qui il tuo calendario e la tua posta."
        return None

    def aggiorna_stato(self):
        motivo = self.motivo_non_pronto()
        self.vuoto.imposta_testo(motivo or "")
        self.pile.setCurrentIndex(0 if motivo else 1)
        return motivo is None


# =============================================================== Agenda
class SchedaAgenda(SchedaM365):
    TITOLO = "Agenda"
    SOTTO = "Le tue riunioni da Microsoft 365. Prepara, registra e poi trasforma la call in un incarico."

    def __init__(self, finestra, parent=None):
        super().__init__(finestra, parent)
        self.eventi = []
        lay = QVBoxLayout(self.contenuto)
        lay.setContentsMargins(20, 16, 20, 12)
        self.c_giorni = QComboBox()
        for testo, g in (("Oggi e domani", 2), ("7 giorni", 7), ("14 giorni", 14)):
            self.c_giorni.addItem(testo, g)
        self.c_giorni.setCurrentIndex(1)
        b_agg = QPushButton("Aggiorna")
        b_agg.clicked.connect(self.carica)
        self.titolo(lay, [self.c_giorni, b_agg])
        sp = QSplitter(Qt.Horizontal)
        self.lista = QListWidget()
        self.lista.setSpacing(2)
        self.lista.currentRowChanged.connect(self.mostra)
        sp.addWidget(self.lista)
        dx = QWidget()
        dl = QVBoxLayout(dx)
        dl.setContentsMargins(16, 0, 0, 0)
        self.d_titolo = QLabel("Seleziona una riunione")
        self.d_titolo.setProperty("ruolo", "titolo")
        self.d_titolo.setWordWrap(True)
        self.d_meta = QLabel("")
        self.d_meta.setProperty("ruolo", "tenue")
        self.d_meta.setWordWrap(True)
        self.d_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dl.addWidget(self.d_titolo)
        dl.addWidget(self.d_meta)
        bar = QHBoxLayout()
        self.b_prep = QPushButton("Prepara")
        self.b_prep.setToolTip("Briefing locale: partecipanti, verbali precedenti con le stesse persone, azioni aperte")
        self.b_reg = QPushButton("● Registra")
        self.b_reg.setToolTip("Apre la pagina Registra con il titolo di questa riunione")
        self.b_inc = QPushButton("Incarico →")
        self.b_inc.setProperty("primario", True)
        self.b_out = QPushButton("Apri in Outlook")
        self.b_join = QPushButton("Partecipa")
        for b in (self.b_prep, self.b_reg, self.b_join, self.b_out):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.b_inc)
        dl.addLayout(bar)
        self.l_reg = QLabel("")
        self.l_reg.setProperty("ruolo", "tenue")
        dl.addWidget(self.l_reg)
        self.out = QTextBrowser()
        self.out.setOpenExternalLinks(True)
        dl.addWidget(self.out, 1)
        sp.addWidget(dx)
        sp.setSizes([380, 700])
        lay.addWidget(sp, 1)
        self.b_prep.clicked.connect(self.prepara)
        self.b_reg.clicked.connect(self.registra)
        self.b_inc.clicked.connect(self.incarico)
        self.b_out.clicked.connect(lambda: self._apri("link"))
        self.b_join.clicked.connect(lambda: self._apri("link_riunione"))
        self.lavoro = None
        self.mostra(-1)

    def showEvent(self, e):
        super().showEvent(e)
        if self.aggiorna_stato() and not self.eventi:
            self.carica()

    def evento(self):
        i = self.lista.currentRow()
        it = self.lista.item(i) if i >= 0 else None
        k = it.data(Qt.UserRole) if it else None
        return self.eventi[k] if isinstance(k, int) and 0 <= k < len(self.eventi) else None

    def carica(self):
        if not self.aggiorna_stato():
            return
        self.lista.clear()
        self.lista.addItem("Leggo il calendario…")
        giorni = self.c_giorni.currentData()
        lav = attrezzi.Lavoro(lambda _l: m365.eventi(giorni), self)
        lav.sig_fine.connect(self._caricati)
        lav.sig_errore.connect(lambda e: (self.lista.clear(), self.lista.addItem(f"Errore: {e}")))
        self._lav_cal = lav
        lav.start()

    def _caricati(self, evs):
        c = tema.colori()
        self.eventi = evs
        self.lista.clear()
        giorno = None
        adesso = datetime.now()
        for k, ev in enumerate(evs):
            ini = datetime.fromisoformat(ev["inizio"])
            g = etichetta_giorno(ini)
            if g != giorno:
                giorno = g
                h = QListWidgetItem(g.upper())
                h.setFlags(Qt.NoItemFlags)
                h.setForeground(QColor(c["tenue"]))
                f = h.font()
                f.setBold(True)
                f.setPointSizeF(f.pointSizeF() - 1)
                h.setFont(f)
                self.lista.addItem(h)
            fine = datetime.fromisoformat(ev["fine"])
            orario = "tutto il giorno" if ev["giornata"] else f"{ini:%H:%M}–{fine:%H:%M}"
            dove = " · Teams" if ev["online"] else (f" · {ev['luogo']}" if ev["luogo"] else "")
            it = QListWidgetItem(f"{ev['oggetto']}\n{orario}{dove} · {len(ev['persone'])} persone")
            it.setData(Qt.UserRole, k)
            it.setSizeHint(QSize(0, 52))
            if ini <= adesso <= fine:
                it.setForeground(QColor(c["accento"]))
            elif fine < adesso:
                it.setForeground(QColor(c["tenue"]))
            self.lista.addItem(it)
        if not evs:
            self.lista.addItem("Nessuna riunione nel periodo.")

    def mostra(self, _i):
        ev = self.evento()
        for b in (self.b_prep, self.b_inc, self.b_out):
            b.setEnabled(bool(ev))
        self.b_join.setEnabled(bool(ev and ev.get("link_riunione")))
        if not ev:
            self.d_titolo.setText("Seleziona una riunione")
            self.d_meta.setText("")
            self.out.setHtml("")
            return
        ini, fine = datetime.fromisoformat(ev["inizio"]), datetime.fromisoformat(ev["fine"])
        self.d_titolo.setText(ev["oggetto"])
        persone = ", ".join(p["nome"] for p in ev["persone"]) or "nessun partecipante"
        dove = "Teams" if ev["online"] else (ev["luogo"] or "luogo non indicato")
        self.d_meta.setText(f"{etichetta_giorno(ini)} · {ini:%H:%M}–{fine:%H:%M} · {dove}\nPartecipanti: {persone}")
        c = tema.colori()
        prev = html.escape(ev.get("anteprima") or "").strip()
        self.out.setHtml(f"<p style='color:{c['tenue']}'>Agenda / invito:</p><p>{prev or '—'}</p>"
                         f"<p style='color:{c['tenue']}'>Premi <b>Prepara</b> per un briefing con i verbali precedenti "
                         "e le azioni aperte con queste persone (tutto in locale).</p>")

    def _apri(self, chiave):
        ev = self.evento()
        if ev and ev.get(chiave):
            QDesktopServices.openUrl(QUrl(ev[chiave]))

    # ---- Prepara: briefing locale
    def _materiale(self, ev):
        """Verbali e task delle riunioni precedenti in cui compaiono i partecipanti (cerca vicino alle trascrizioni)."""
        nomi = {p["nome"].split()[0].lower() for p in ev["persone"] if p["nome"] and "@" not in p["nome"]}
        nomi |= {p["email"].split("@")[0].split(".")[0].lower() for p in ev["persone"]}
        nomi.discard("")
        cartelle = {Path(j["file"]).parent for j in self.finestra.jobs if j.get("file")}
        cartelle.add(cartella_registrazioni())
        trovati = []
        for c in cartelle:
            if not c.exists():
                continue
            for f in list(c.glob("*_verbale*.md"))[:200]:
                try:
                    testo = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                low = testo.lower()
                if any(n in low for n in nomi if len(n) > 2):
                    trovati.append((f.stat().st_mtime, f, testo))
        trovati.sort(reverse=True)
        return trovati[:3]

    def prepara(self):
        ev = self.evento()
        if not ev or not attrezzi.pronto_llm(self):
            return
        mat = self._materiale(ev)
        fonti = "\n\n".join(f"--- Verbale «{f.stem}» ({time.strftime('%d/%m/%Y', time.localtime(t))}):\n{x[:6000]}"
                            for t, f, x in mat)
        persone = ", ".join(f"{p['nome']} <{p['email']}>" for p in ev["persone"])
        richiesta = (
            "Prepara un breve briefing per la riunione qui sotto, in italiano, in Markdown: "
            "1) obiettivo probabile (dall'invito), 2) chi partecipa, 3) cosa è emerso nelle riunioni precedenti "
            "con queste persone, 4) azioni ancora aperte e di chi sono, 5) tre domande utili da fare. "
            "Usa SOLO le informazioni fornite; se non ci sono verbali precedenti dillo chiaramente.\n\n"
            f"RIUNIONE: {ev['oggetto']} · {ev['inizio'].replace('T', ' ')}\nPARTECIPANTI: {persone}\n"
            f"INVITO: {ev.get('anteprima') or '(vuoto)'}\n\nVERBALI PRECEDENTI:\n{fonti or '(nessuno trovato)'}")
        self.out.setPlainText("")
        self.b_prep.setEnabled(False)
        lav = attrezzi.Lavoro(lambda l: attrezzi.chat_llm(l, [{"role": "user", "content": richiesta}]), self)
        lav.sig_token.connect(lambda t: self.out.insertPlainText(t))
        lav.sig_fine.connect(lambda r: (self.out.setMarkdown(attrezzi.visibile(r) +
                                                            (f"\n\n*Fonti: {', '.join(f.name for _, f, _ in mat)}*" if mat else "")),
                                        self.b_prep.setEnabled(True)))
        lav.sig_errore.connect(lambda e: (self.out.setPlainText(f"Errore: {e}"), self.b_prep.setEnabled(True)))
        self.lavoro = lav
        lav.start()

    # ---- Registra
    def registra(self):
        """Una sola funzione di registrazione in tutta l'app (Stile Argo · Organizzazione): dall'Agenda si apre
        la pagina Registra con il titolo della riunione già compilato. Lì ci sono Live, archivio, audio della call
        e sorgenti, che il vecchio registratore dell'Agenda (solo microfono) non aveva."""
        ev = self.evento()
        reg = self.finestra.tab_registra
        if ev and not reg.occupata():
            reg.e_titolo.setText(ev["oggetto"])
        self.finestra.vai_a(reg)

    # ---- Incarico
    def incarico(self):
        ev = self.evento()
        inc = self.finestra.tab_incarichi
        reg = self.finestra.tab_registra
        if reg.occupata():
            QMessageBox.information(self, "Registrazione", "Ferma prima la registrazione nella pagina Registra.")
            return
        # l'ultima registrazione archiviata dalla pagina Registra (in Live resta solo il testo, niente audio)
        f = Path(reg.risultato) if reg.risultato and str(reg.risultato).endswith(".wav") else None
        if f and f.exists():
            inc.imposta_file(str(f))
        if ev:
            inc.persone = ev["persone"]
            inc.e_dest.setText(", ".join(f"{p['nome']} <{p['email']}>" for p in ev["persone"]))
            inc.l_riunione.setText(f"Riunione: «{ev['oggetto']}» · {ev['inizio'].replace('T', ' ')} · "
                                   f"{len(ev['persone'])} persone. Togli dai destinatari chi non deve ricevere il recap.")
        self.finestra.tabs.setCurrentWidget(inc)
        if not (f and f.exists()):
            QMessageBox.information(self, "Incarico", "Partecipanti compilati. Scegli ora la registrazione della call "
                                    "con «Scegli audio o video…».")


# =============================================================== Posta AI
class SchedaPosta(SchedaM365):
    TITOLO = "Posta AI"
    SOTTO = ("Riassunti, richieste e bozze di risposta con il modello locale. Le mail non vanno a nessun servizio AI "
             "esterno; le risposte restano bozze in Outlook.")

    def __init__(self, finestra, parent=None):
        super().__init__(finestra, parent)
        self.mail = []
        self.attuale = None
        self.lavoro = None
        lay = QVBoxLayout(self.contenuto)
        lay.setContentsMargins(20, 16, 20, 12)
        self.c_filtro = QComboBox()
        self.c_filtro.addItem("Non lette", True)
        self.c_filtro.addItem("Tutte (ultime 40)", False)
        self.c_filtro.currentIndexChanged.connect(lambda _: self.carica())
        b_agg = QPushButton("Aggiorna")
        b_agg.clicked.connect(self.carica)
        self.titolo(lay, [self.c_filtro, b_agg])
        sp = QSplitter(Qt.Horizontal)
        self.lista = QListWidget()
        self.lista.setSpacing(2)
        self.lista.currentRowChanged.connect(self.apri)
        sp.addWidget(self.lista)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(14, 0, 8, 0)
        self.m_ogg = QLabel("Seleziona una mail")
        self.m_ogg.setProperty("ruolo", "titolo")
        self.m_ogg.setWordWrap(True)
        self.m_meta = QLabel("")
        self.m_meta.setProperty("ruolo", "tenue")
        self.m_meta.setWordWrap(True)
        self.m_testo = QTextBrowser()
        self.m_testo.setOpenExternalLinks(True)
        # le mail HTML hanno colori pensati per lo sfondo chiaro: si mostrano su «carta», come in Outlook
        self.m_testo.setObjectName("mail")
        self.m_testo.document().setDefaultStyleSheet(f"a {{ color: {tema.CARTA_MAIL['link']}; }}")
        ml.addWidget(self.m_ogg)
        ml.addWidget(self.m_meta)
        ml.addWidget(self.m_testo, 1)
        rb = QHBoxLayout()
        self.b_letta = QPushButton("Segna come letta")
        self.b_outlook = QPushButton("Apri in Outlook")
        rb.addWidget(self.b_letta)
        rb.addWidget(self.b_outlook)
        rb.addStretch()
        ml.addLayout(rb)
        sp.addWidget(mid)
        dx = QWidget()
        dl = QVBoxLayout(dx)
        dl.setContentsMargins(8, 0, 0, 0)
        s = QLabel("ASSISTENTE LOCALE")
        s.setProperty("ruolo", "sezione")
        dl.addWidget(s)
        ra = QHBoxLayout()
        self.b_riass = QPushButton("Riassumi")
        self.b_chiede = QPushButton("Cosa mi si chiede")
        ra.addWidget(self.b_riass)
        ra.addWidget(self.b_chiede)
        dl.addLayout(ra)
        rr = QHBoxLayout()
        self.c_tono = QComboBox()
        self.c_tono.addItems(incarichi.TONI)
        self.e_istr = QLineEdit()
        self.e_istr.setPlaceholderText("Come rispondere, es. «accetto, propongo giovedì alle 10»")
        rr.addWidget(self.c_tono)
        dl.addLayout(rr)
        dl.addWidget(self.e_istr)
        rr2 = QHBoxLayout()
        self.b_risp = QPushButton("Scrivi risposta")
        self.b_risp.setProperty("primario", True)
        self.c_tutti = QComboBox()
        self.c_tutti.addItem("Rispondi", False)
        self.c_tutti.addItem("Rispondi a tutti", True)
        rr2.addWidget(self.b_risp)
        rr2.addWidget(self.c_tutti)
        dl.addLayout(rr2)
        self.uscita = QPlainTextEdit()
        self.uscita.setPlaceholderText("Qui compaiono riassunto, richieste o bozza di risposta. Puoi modificare il testo.")
        dl.addWidget(self.uscita, 1)
        rb2 = QHBoxLayout()
        self.b_bozza = QPushButton("Salva come bozza in Outlook")
        self.b_task = QPushButton("Crea task in Planner")
        b_copia = QPushButton("Copia")
        b_copia.clicked.connect(lambda: attrezzi.copia(self.uscita.toPlainText()))
        rb2.addWidget(self.b_bozza)
        rb2.addWidget(b_copia)
        dl.addLayout(rb2)
        dl.addWidget(self.b_task)
        self.l_stato = QLabel("")
        self.l_stato.setProperty("ruolo", "tenue")
        self.l_stato.setWordWrap(True)
        dl.addWidget(self.l_stato)
        sp.addWidget(dx)
        sp.setSizes([330, 470, 400])
        lay.addWidget(sp, 1)
        self.b_riass.clicked.connect(lambda: self.ai("riassunto"))
        self.b_chiede.clicked.connect(lambda: self.ai("richieste"))
        self.b_risp.clicked.connect(lambda: self.ai("risposta"))
        self.b_bozza.clicked.connect(self.salva_bozza)
        self.b_task.clicked.connect(self.crea_task)
        self.b_letta.clicked.connect(self.segna_letta)
        self.b_outlook.clicked.connect(lambda: self.attuale and QDesktopServices.openUrl(QUrl(self.attuale["link"])))
        self._abilita(False)

    def motivo_non_pronto(self):
        m = super().motivo_non_pronto()
        if m:
            return m
        if not m365.lettura_posta_attiva():
            return ("La lettura della posta è disattivata.\nAttivala in Impostazioni → Microsoft 365 → «Leggi la posta "
                    "per Posta AI». Le mail vengono elaborate solo su questo computer.")
        return None

    def showEvent(self, e):
        super().showEvent(e)
        if self.aggiorna_stato() and not self.mail:
            self.carica()

    def _abilita(self, on):
        for b in (self.b_riass, self.b_chiede, self.b_risp, self.b_letta, self.b_outlook, self.b_task):
            b.setEnabled(on)
        self.b_bozza.setEnabled(on and getattr(self, "_ultima_azione", "") == "risposta")

    def carica(self):
        if not self.aggiorna_stato():
            return
        self.lista.clear()
        self.lista.addItem("Leggo la posta…")
        solo = self.c_filtro.currentData()
        lav = attrezzi.Lavoro(lambda _l: m365.posta(solo), self)
        lav.sig_fine.connect(self._caricata)
        lav.sig_errore.connect(lambda e: (self.lista.clear(), self.lista.addItem(f"Errore: {e}")))
        self._lav_posta = lav
        lav.start()

    def _caricata(self, mail):
        c = tema.colori()
        self.mail = mail
        self.lista.clear()
        for k, m in enumerate(mail):
            segni = ("● " if not m["letta"] else "") + ("! " if m["importante"] else "") + ("📎 " if m["allegati"] else "")
            prev = " ".join(m["anteprima"].split())[:90]
            it = QListWidgetItem(f"{segni}{m['da']['nome']}  ·  {m['quando'][11:16] or m['quando']}\n{m['oggetto']}\n{prev}")
            it.setData(Qt.UserRole, k)
            it.setSizeHint(QSize(0, 70))
            if not m["letta"]:
                it.setForeground(QColor(c["testo"]))
            else:
                it.setForeground(QColor(c["tenue"]))
            self.lista.addItem(it)
        if not mail:
            self.lista.addItem("Nessuna mail da mostrare. 🎉" if self.c_filtro.currentData() else "Nessuna mail.")

    def apri(self, _i):
        it = self.lista.currentItem()
        k = it.data(Qt.UserRole) if it else None
        if not isinstance(k, int):
            return
        m = self.mail[k]
        self.m_ogg.setText(m["oggetto"])
        self.m_meta.setText(f"{m['da']['nome']} <{m['da']['email']}> · {m['quando']}")
        self.m_testo.setPlainText("Carico il messaggio…")
        self.uscita.clear()
        self._ultima_azione = ""
        lav = attrezzi.Lavoro(lambda _l: m365.messaggio(m["id"]), self)

        def ok(msg):
            self.attuale = msg
            a = ", ".join(msg["a"])
            self.m_meta.setText(f"{msg['da']['nome']} <{msg['da']['email']}> · {msg['quando']}" + (f"\nA: {a}" if a else "")
                                + ("\n📎 con allegati (aprili in Outlook)" if msg["allegati"] else ""))
            self.m_testo.setHtml(msg.get("html") or "")
            self._abilita(True)

        lav.sig_fine.connect(ok)
        lav.sig_errore.connect(lambda e: self.m_testo.setPlainText(f"Errore: {e}"))
        self._lav_msg = lav
        lav.start()

    def ai(self, tipo):
        m = self.attuale
        if not m or not attrezzi.pronto_llm(self):
            return
        self._ultima_azione = tipo
        istr = self.e_istr.text().strip()
        tono = self.c_tono.currentText()
        conv_id = m.get("conversazione")
        self.uscita.clear()
        self.l_stato.setText("Il modello locale sta lavorando…")
        for b in (self.b_riass, self.b_chiede, self.b_risp, self.b_bozza):
            b.setEnabled(False)

        def fn(lav):
            try:
                storia = m365.conversazione(conv_id)
            except Exception:
                storia = []
            filo = "\n\n".join(f"--- {x['da']['nome']} ({x['quando']}):\n{x['testo'][:4000]}" for x in storia[-6:]) \
                or f"--- {m['da']['nome']} ({m['quando']}):\n{m['testo'][:8000]}"
            if tipo == "riassunto":
                rich = ("Riassumi in italiano questa conversazione email in 3-6 punti elenco: chi scrive, cosa è "
                        "successo, cosa resta da decidere. Usa solo le informazioni presenti.")
            elif tipo == "richieste":
                rich = ("Elenca in italiano cosa viene chiesto a me (il destinatario) nell'ultima mail: una riga per "
                        "richiesta, con scadenza se c'è. Se non c'è nessuna richiesta, scrivilo.")
            else:
                rich = (f"Scrivi la risposta all'ultima mail, tono {tono}, nella stessa lingua della mail. Solo il corpo "
                        "della mail, senza oggetto e senza firma. Non inventare impegni, date o cifre."
                        + (f" Indicazioni di chi risponde: {istr}" if istr else ""))
            return attrezzi.chat_llm(lav, [{"role": "system", "content": "Sei un assistente di posta preciso e sobrio."},
                                           {"role": "user", "content": f"{rich}\n\nCONVERSAZIONE:\n{filo}"}])

        lav = attrezzi.Lavoro(fn, self)
        lav.sig_token.connect(lambda t: self.uscita.insertPlainText(t))
        lav.sig_fine.connect(lambda r: (self.uscita.setPlainText(attrezzi.visibile(r).strip()), self._abilita(True),
                                        self.l_stato.setText("Fatto, in locale. Rileggi prima di usarlo.")))
        lav.sig_errore.connect(lambda e: (self.l_stato.setText(f"Errore: {e}"), self._abilita(True)))
        self.lavoro = lav
        lav.start()

    def salva_bozza(self):
        m, testo = self.attuale, self.uscita.toPlainText().strip()
        if not m or not testo:
            return
        a_tutti = self.c_tutti.currentData()
        lav = attrezzi.Lavoro(lambda _l: m365.bozza_risposta(m["id"], testo, a_tutti), self)
        lav.sig_fine.connect(lambda r: self.l_stato.setText(
            f"Bozza di risposta salvata in Outlook ({'a tutti' if a_tutti else 'al mittente'}). Non è stata inviata."))
        lav.sig_errore.connect(lambda e: self.l_stato.setText(f"Errore: {e}"))
        self._lav_b = lav
        lav.start()

    def segna_letta(self):
        m = self.attuale
        if not m:
            return
        lav = attrezzi.Lavoro(lambda _l: m365.segna_letta(m["id"]), self)
        lav.sig_fine.connect(lambda _r: (self.l_stato.setText("Segnata come letta."), self.carica()))
        lav.sig_errore.connect(lambda e: self.l_stato.setText(f"Errore: {e}"))
        self._lav_l = lav
        lav.start()

    def crea_task(self):
        m = self.attuale
        if not m or not attrezzi.pronto_llm(self):
            return
        self.l_stato.setText("Estraggo le richieste come task…")
        oggi = time.strftime(incarichi.FORMATO_DATA)
        lav = attrezzi.Lavoro(lambda l: (incarichi.estrai_task(l, f"Mail di {m['da']['nome']} del {m['quando']}:\n"
                                                               f"{m['testo'][:8000]}", oggi), m365.piani()), self)

        def scegli(r):
            task, piani = r
            if not task:
                self.l_stato.setText("Nessuna richiesta da trasformare in task.")
                return
            if not piani:
                self.l_stato.setText("Nessun piano Planner trovato.")
                return
            from PySide6.QtWidgets import QInputDialog
            nomi = [p["titolo"] for p in piani]
            elenco = "\n".join(f"• {t['titolo']}" + (f" (entro {t['scadenza']})" if t["scadenza"] else "") for t in task)
            scelto, ok = QInputDialog.getItem(self, "Crea task in Planner",
                                              f"Creo questi task nel piano scelto:\n{elenco}\n\nPiano:", nomi, 0, False)
            if not ok:
                self.l_stato.setText("Annullato.")
                return
            pid = piani[nomi.index(scelto)]["id"]

            def crea(_l):
                b = m365.bucket(pid)
                if not b:
                    raise m365.ErroreM365("il piano non ha bucket")
                for t in task:
                    t["responsabile"] = ""  # dalla posta i task sono miei: non assegno ad altri
                return m365.crea_task(pid, b[0]["id"], task, {})

            l2 = attrezzi.Lavoro(crea, self)
            l2.sig_fine.connect(lambda c: self.l_stato.setText(f"{len(c)} task creati in «{scelto}»."))
            l2.sig_errore.connect(lambda e: self.l_stato.setText(f"Errore: {e}"))
            self._lav_t2 = l2
            l2.start()

        lav.sig_fine.connect(scegli)
        lav.sig_errore.connect(lambda e: self.l_stato.setText(f"Errore: {e}"))
        self._lav_t = lav
        lav.start()
