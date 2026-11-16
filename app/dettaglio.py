"""dettaglio.py - pannello di dettaglio di una trascrizione: corsie colorate dei parlanti e testo con i nomi."""
import html
import json
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

import tema
import voci_core as core


def mmss(t):
    t = int(max(0, t or 0))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class CorsieParlanti(QWidget):
    """Una corsia per parlante: dove e quanto parla ciascuno lungo la registrazione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.corsie = []      # (nome, colore, [(t0, t1)])
        self.durata = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._aggiorna_altezza()

    def imposta(self, corsie, durata):
        self.corsie, self.durata = corsie, max(durata, 1.0)
        self._aggiorna_altezza()
        self.update()

    def _aggiorna_altezza(self):
        self.setFixedHeight(max(1, len(self.corsie)) * 24 + 30)

    def paintEvent(self, _):
        c = tema.colori()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["pannello"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        if not self.corsie:
            p.setPen(QColor(c["tenue"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Seleziona una trascrizione completata")
            return
        x0, x1 = 96, self.width() - 14
        f = QFont(p.font())
        f.setPointSizeF(max(f.pointSizeF() - 1, 8))
        p.setFont(f)
        for i, (nome, col, tratti) in enumerate(self.corsie):
            y = 10 + i * 24
            p.setPen(QColor(col))
            p.drawText(QRectF(12, y, x0 - 18, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(nome, Qt.ElideRight, x0 - 18))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["pannello2"]))
            p.drawRoundedRect(QRectF(x0, y + 1, x1 - x0, 14), 4, 4)
            colore = QColor(col)
            colore.setAlphaF(0.9)
            p.setBrush(colore)
            for a, b in tratti:
                xa = x0 + (x1 - x0) * a / self.durata
                xb = x0 + (x1 - x0) * b / self.durata
                p.drawRoundedRect(QRectF(xa, y + 1, max(xb - xa, 1.5), 14), 3, 3)
        p.setPen(QColor(c["debole"]))
        y = self.height() - 16
        for k in range(5):
            t = self.durata * k / 4
            x = x0 + (x1 - x0) * k / 4
            al = Qt.AlignLeft if k == 0 else (Qt.AlignRight if k == 4 else Qt.AlignHCenter)
            r = QRectF(x, y, 60, 14) if k == 0 else (QRectF(x - 60, y, 60, 14) if k == 4 else QRectF(x - 40, y, 80, 14))
            p.drawText(r, al | Qt.AlignVCenter, mmss(t))


class DettaglioTrascrizione(QWidget):
    """Titolo, azioni, corsie dei parlanti e trascrizione colorata del file selezionato nella coda."""
    nomi = Signal()
    marca = Signal()
    word = Signal()
    verbale = Signal()
    apri = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        self.titolo = QLabel("Nessun file selezionato")
        self.titolo.setProperty("ruolo", "titolo")
        self.titolo.setWordWrap(True)
        self.meta = QLabel("Scegli un file nella coda per vedere chi parla e cosa dice.")
        self.meta.setProperty("ruolo", "tenue")
        self.meta.setWordWrap(True)
        lay.addWidget(self.titolo)
        lay.addWidget(self.meta)
        bar = QHBoxLayout()
        self.bottoni = []
        for testo, sig, prim in (("Nomi dei parlanti", self.nomi, False), ("Marca voci", self.marca, False),
                                 ("Apri testo", self.apri, False), ("Word", self.word, False),
                                 ("Verbale →", self.verbale, True)):
            b = QPushButton(testo)
            if prim:
                b.setProperty("primario", True)
            b.clicked.connect(sig.emit)
            bar.addWidget(b)
            self.bottoni.append(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.corsie = CorsieParlanti()
        lay.addWidget(self.corsie)
        self.testo = QTextBrowser()
        self.testo.setOpenLinks(False)
        lay.addWidget(self.testo, 1)
        self.mostra(None)

    def mostra(self, job):
        c = tema.colori()
        completata = bool(job and job.get("stato") == "Completata" and job.get("json") and Path(job["json"]).exists())
        for b in self.bottoni:
            b.setEnabled(completata)
        self.bottoni[1].setEnabled(bool(job))  # Marca voci funziona anche prima della trascrizione
        self.corsie.setVisible(bool(job))
        if not job:
            self.titolo.setText("Nessun file selezionato")
            self.meta.setText("Scegli un file nella coda per vedere chi parla e cosa dice.")
            self.corsie.imposta([], 1)
            self.testo.setHtml(tema.stato_vuoto("Trascina qui un audio o un video, oppure scegli un file nella coda."))
            return
        self.titolo.setText(Path(job["file"]).name)
        if not completata:
            stato = job.get("stato", "")
            nota = f" · {job['nota']}" if job.get("nota") else ""
            self.meta.setText(f"{stato}{nota} · partecipanti: {job.get('parlanti') or 'auto'}")
            self.corsie.imposta([], 1)
            self.testo.setHtml(f"<p style='color:{c['tenue']}'>La trascrizione comparirà qui quando sarà completata.</p>")
            return
        try:
            dati = json.loads(Path(job["json"]).read_text(encoding="utf-8"))
            mappa, _, _ = core.mappa_nomi(dati)
        except Exception as e:
            self.meta.setText(f"Impossibile leggere la trascrizione: {e}")
            return
        segs = [s for s in dati.get("segments", []) if (s.get("text") or "").strip()]
        durata = max((s.get("end", 0) for s in segs), default=1.0)
        nomi = []
        for s in segs:
            n = mappa.get(s.get("speaker"), "Non attribuito")
            if n not in nomi:
                nomi.append(n)
        palette = c["parlanti"]
        colore = {n: palette[i % len(palette)] for i, n in enumerate(nomi)}
        tratti = {n: [] for n in nomi}
        for s in segs:
            tratti[mappa.get(s.get("speaker"), "Non attribuito")].append((s.get("start", 0), s.get("end", 0)))
        self.corsie.imposta([(n, colore[n], tratti[n]) for n in nomi], durata)
        self.meta.setText(f"{mmss(durata)} · {len(nomi)} parlanti: {', '.join(nomi)}")
        righe, ultimo = [], None
        for s in segs:
            n = mappa.get(s.get("speaker"), "Non attribuito")
            t = html.escape(s["text"].strip())
            if righe and n == ultimo:
                righe[-1][2].append(t)
            else:
                righe.append([s.get("start", 0), n, [t]])
                ultimo = n
        corpo = "".join(
            f"<p style='margin:0 0 12px 0; line-height:150%'>"
            f"<span style='font-family:Menlo,Consolas,monospace; font-size:11px; color:{c['debole']}'>{mmss(t0)}</span>"
            f"&nbsp;&nbsp;<b style='color:{colore[n]}'>{html.escape(n)}</b>&nbsp;&nbsp;"
            f"<span style='color:{c['testo2']}'>{' '.join(parti)}</span></p>"
            for t0, n, parti in righe)
        self.testo.setHtml(corpo)
