"""voci_strumenti.py - strumenti per creare le impronte vocali direttamente da Argo.

1. RegistraVoceDialog: registra la voce di una persona dal microfono (con consenso) e la passa all'anagrafe.
2. MarcaVociDialog: ascolta un audio, marca sulla forma d'onda i tratti in cui parla ciascuna persona
   (anche partendo dai parlanti già trovati dalla trascrizione) e crea le impronte in un colpo solo.

L'audio resta sul computer: si usano ffmpeg per leggere i file e sounddevice per microfono e altoparlanti.
"""
from lingua import tr
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

try:  # anteprima video (Qt Multimedia, incluso in PySide6)
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    VIDEO_OK = True
except Exception:  # pragma: no cover
    VIDEO_OK = False

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv"}

import tema
import voci_core as core

SR = 16000
BLOCCO = 160  # 10 ms: risoluzione della forma d'onda
MIN_SECONDI = 10
CONSIGLIATI = 20
COLORI = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777"]
TESTO_LETTURA = (
    "Buongiorno, sto registrando la mia voce per Argo, la cassetta degli attrezzi AI. "
    "Questa registrazione resta su questo computer e serve solo a riconoscere chi parla nelle riunioni. "
    "Oggi a Cuneo il tempo è variabile: al mattino c'era il sole, nel pomeriggio è arrivata la pioggia. "
    "Per il progetto servono tre cose: un calendario chiaro, un responsabile per ogni attività "
    "e una riunione di verifica ogni due settimane. Uno, due, tre, quattro, cinque, sei, sette, otto, nove, dieci."
)
TESTO_CONSENSO = "La persona sa che sto registrando la sua impronta vocale e ha dato il consenso esplicito"


def mmss(t):
    t = max(0.0, float(t))
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def scrivi_wav(percorso, campioni_int16):
    with wave.open(str(percorso), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.asarray(campioni_int16, dtype=np.int16).tobytes())


def leggi_audio(percorso):
    """Decodifica qualsiasi audio/video in mono 16 kHz int16 con ffmpeg."""
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(percorso), "-ac", "1", "-ar", str(SR),
                            "-f", "s16le", "-"], capture_output=True, creationflags=flags, timeout=900)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg non trovato: rilancia l'installer di Argo.") from None
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("Non riesco a leggere l'audio: " + r.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(r.stdout, dtype=np.int16).copy()


def dir_temporanea():
    d = Path(tempfile.gettempdir()) / "argo_voci"
    d.mkdir(exist_ok=True)
    return d


def nome_file(nome):
    return "".join(c if c.isalnum() else "_" for c in nome)[:40] or "voce"


# ================================================================ 1. registrazione dal microfono
class RegistraVoceDialog(QDialog):
    """Registra 20-60 secondi di una sola voce. Al termine: self.risultato = [(nome, wav)]."""

    def __init__(self, nomi_noti, nome=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Registra una voce'))
        self.resize(620, 520)
        self.risultato = []
        self.flusso = None
        self.campioni = []
        self.livello = 0.0
        lay = QVBoxLayout(self)
        intro = QLabel(tr('Fai parlare <b>solo</b> la persona da registrare, nel silenzio, con il microfono che usi di solito. Servono almeno 20 secondi; 30-60 è meglio. Può leggere il testo qui sotto.'))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        riga = QHBoxLayout()
        riga.addWidget(QLabel(tr('Nome:')))
        self.c_nome = QComboBox()
        self.c_nome.setEditable(True)
        self.c_nome.addItems(nomi_noti)
        self.c_nome.setCurrentText(nome or "")
        self.c_nome.lineEdit().setPlaceholderText(tr('es. Marco Rossi'))
        riga.addWidget(self.c_nome, 1)
        lay.addLayout(riga)
        testo = QPlainTextEdit(TESTO_LETTURA)
        testo.setReadOnly(True)
        f = testo.font()
        f.setPointSize(f.pointSize() + 2)
        testo.setFont(f)
        lay.addWidget(testo, 1)
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(12)
        lay.addWidget(self.barra)
        self.l_tempo = QLabel(tr('Pronto. Premi «Registra».'))
        lay.addWidget(self.l_tempo)
        self.cb_consenso = QCheckBox(TESTO_CONSENSO)
        lay.addWidget(self.cb_consenso)
        bar = QHBoxLayout()
        self.b_reg = QPushButton(tr('● Registra'))
        self.b_reg.setProperty("primario", True)
        self.b_ascolta = QPushButton(tr('▶ Riascolta'))
        self.b_ascolta.setEnabled(False)
        self.b_salva = QPushButton(tr('Crea impronta'))
        self.b_salva.setEnabled(False)
        b_annulla = QPushButton(tr('Annulla'))
        for b in (self.b_reg, self.b_ascolta):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(b_annulla)
        bar.addWidget(self.b_salva)
        lay.addLayout(bar)
        self.b_reg.clicked.connect(self.registra_o_stop)
        self.b_ascolta.clicked.connect(self.riascolta)
        self.b_salva.clicked.connect(self.salva)
        b_annulla.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._aggiorna)

    def _secondi(self):
        return sum(len(c) for c in self.campioni) / SR

    def registra_o_stop(self):
        if self.flusso is None:
            try:
                import sounddevice as sd
                sd.stop()
                self.campioni = []
                self.flusso = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=self._cb)
                self.flusso.start()
            except Exception as e:
                self.flusso = None
                QMessageBox.warning(self, tr('Microfono'), tr('Impossibile usare il microfono: {e}\n\nSul Mac: Impostazioni di Sistema → Privacy e sicurezza → Microfono → abilita Argo AI.', e=e))
                return
            self.b_reg.setText(tr('■ Stop'))
            self.b_ascolta.setEnabled(False)
            self.b_salva.setEnabled(False)
            self.timer.start(100)
        else:
            self._ferma()

    def _cb(self, dati, *args):
        self.campioni.append(dati[:, 0].copy())
        self.livello = float(np.sqrt(np.mean(dati[:, 0] ** 2)))

    def _ferma(self):
        if self.flusso is not None:
            self.flusso.stop()
            self.flusso.close()
            self.flusso = None
        self.timer.stop()
        self.barra.setValue(0)
        self.b_reg.setText(tr('● Registra di nuovo'))
        s = self._secondi()
        ok = s >= MIN_SECONDI
        self.b_ascolta.setEnabled(s > 0)
        self.b_salva.setEnabled(ok)
        if not ok:
            self.l_tempo.setText(tr('Registrati {s:.0f} s: troppo pochi, ne servono almeno {min_secondi} (meglio {consigliati}+).', s=s, min_secondi=MIN_SECONDI, consigliati=CONSIGLIATI))
        elif s < CONSIGLIATI:
            self.l_tempo.setText(tr("Registrati {s:.0f} s: va bene, ma con {consigliati}+ secondi l'impronta è più stabile.", s=s, consigliati=CONSIGLIATI))
        else:
            self.l_tempo.setText(tr('Registrati {s:.0f} s. Ottimo: riascolta se vuoi, poi «Crea impronta».', s=s))

    def _aggiorna(self):
        s = self._secondi()
        db = 20 * np.log10(max(self.livello, 1e-5))  # da -100 a 0 dB
        self.barra.setValue(int(np.clip((db + 60) / 60 * 100, 0, 100)))
        consiglio = "parla pure…" if s < CONSIGLIATI else "va bene, puoi fermare quando vuoi"
        silenzio = "  ·  non sento niente: controlla il microfono" if s > 3 and self.livello < 0.002 else ""
        self.l_tempo.setText(tr('● Registrazione: {s:.0f} s, {consiglio}{silenzio}', s=s, consiglio=consiglio, silenzio=silenzio))
        if s >= 120:
            self._ferma()

    def _audio(self):
        audio = np.concatenate(self.campioni) if self.campioni else np.zeros(0, dtype=np.float32)
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16)

    def riascolta(self):
        try:
            import sounddevice as sd
            sd.play(self._audio(), SR)
        except Exception as e:
            QMessageBox.warning(self, tr('Audio'), tr('Riproduzione non disponibile: {e}', e=e))

    def salva(self):
        nome = self.c_nome.currentText().strip()
        if not core.nome_valido(nome):
            QMessageBox.warning(self, tr('Nome'), tr('Scrivi il nome della persona, senza caratteri speciali.'))
            return
        if not self.cb_consenso.isChecked():
            QMessageBox.warning(self, tr('Consenso'), tr("L'impronta vocale è un dato biometrico: serve il consenso esplicito della persona. Spunta la casella per confermarlo."))
            return
        f = dir_temporanea() / f"registrazione_{nome_file(nome)}_{int(time.time())}.wav"
        scrivi_wav(f, self._audio())
        self.risultato = [(nome, str(f))]
        self.accept()

    def closeEvent(self, e):
        self._ferma_tutto()
        super().closeEvent(e)

    def reject(self):
        self._ferma_tutto()
        super().reject()

    def _ferma_tutto(self):
        if self.flusso is not None:
            self.flusso.stop()
            self.flusso.close()
            self.flusso = None
        self.timer.stop()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass


# ================================================================ 2. forma d'onda con marcature
class FormaOnda(QWidget):
    """Forma d'onda con zoom (rotella), selezione (trascina), posizione (clic) e corsie dei parlanti."""
    cliccato = Signal(float)
    selezionato = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.picchi = np.zeros(0, dtype=np.float32)
        self.durata = 0.0
        self.v0, self.v1 = 0.0, 1.0
        self.pos = 0.0
        self.sel = None
        self.segni = []      # (t0, t1, colore, etichetta)
        self.diar = []       # (t0, t1, colore, etichetta)
        self._premuto = None

    def imposta_audio(self, audio):
        n = len(audio) // BLOCCO
        a = np.abs(audio[:n * BLOCCO].astype(np.float32)).reshape(n, BLOCCO) if n else np.zeros((0, BLOCCO))
        p = a.max(axis=1) if n else np.zeros(0)
        self.picchi = (p / max(float(p.max()) if n else 1.0, 1.0)).astype(np.float32)
        self.durata = len(audio) / SR
        self.v0, self.v1 = 0.0, max(self.durata, 0.1)
        self.sel = None
        self.update()

    # --- coordinate
    def _alto_onda(self):
        return self.height() - (34 if self.diar else 14)

    def x_da_t(self, t):
        return (t - self.v0) / max(self.v1 - self.v0, 1e-6) * self.width()

    def t_da_x(self, x):
        return min(max(self.v0 + x / max(self.width(), 1) * (self.v1 - self.v0), 0.0), self.durata)

    def mostra(self, t):
        """Sposta la finestra di zoom perché t sia visibile."""
        w = self.v1 - self.v0
        if t < self.v0 or t > self.v1:
            self.v0 = min(max(t - w * 0.1, 0.0), max(self.durata - w, 0.0))
            self.v1 = self.v0 + w

    def zoom(self, fattore, centro=None):
        if self.durata <= 0:
            return
        c = (self.v0 + self.v1) / 2 if centro is None else centro
        w = min(max((self.v1 - self.v0) * fattore, 2.0), self.durata)
        self.v0 = min(max(c - (c - self.v0) * w / max(self.v1 - self.v0, 1e-6), 0.0), self.durata - w)
        self.v1 = self.v0 + w
        self.update()

    def scorri(self, frazione):
        w = self.v1 - self.v0
        self.v0 = min(max(self.v0 + w * frazione, 0.0), max(self.durata - w, 0.0))
        self.v1 = self.v0 + w
        self.update()

    # --- disegno
    def paintEvent(self, _):
        p = QPainter(self)
        tc = tema.colori()
        p.fillRect(self.rect(), QColor(tc["pannello"]))
        h_onda = self._alto_onda()
        mezzo = h_onda / 2
        if self.durata > 0 and len(self.picchi):
            for t0, t1, col, _e in self.segni:
                if t1 >= self.v0 and t0 <= self.v1:
                    c = QColor(col)
                    c.setAlpha(60)
                    p.fillRect(QRectF(self.x_da_t(t0), 0, max(self.x_da_t(t1) - self.x_da_t(t0), 1), h_onda), c)
            if self.sel:
                c = QColor("#facc15")
                c.setAlpha(110)
                a, b = sorted(self.sel)
                p.fillRect(QRectF(self.x_da_t(a), 0, max(self.x_da_t(b) - self.x_da_t(a), 1), h_onda), c)
            p.setPen(QPen(QColor(tc["tenue"])))
            w = self.width()
            for x in range(w):
                i0 = int(self.t_da_x(x) * SR / BLOCCO)
                i1 = max(int(self.t_da_x(x + 1) * SR / BLOCCO), i0 + 1)
                seg = self.picchi[i0:i1]
                if len(seg):
                    a = float(seg.max()) * (mezzo - 4)
                    p.drawLine(x, int(mezzo - a), x, int(mezzo + a))
            for t0, t1, col, e in self.segni:
                if t1 >= self.v0 and t0 <= self.v1:
                    x0, x1 = self.x_da_t(t0), self.x_da_t(t1)
                    p.fillRect(QRectF(x0, 0, max(x1 - x0, 2), 6), QColor(col))
                    p.setPen(QColor(col))
                    p.drawText(int(x0) + 3, 19, e)
            if self.diar:
                y = h_onda + 4
                for t0, t1, col, e in self.diar:
                    if t1 >= self.v0 and t0 <= self.v1:
                        r = QRectF(self.x_da_t(t0), y, max(self.x_da_t(t1) - self.x_da_t(t0), 1), 16)
                        p.fillRect(r, QColor(col))
                        if r.width() > 40:
                            p.setPen(QColor("white"))
                            p.drawText(r.adjusted(3, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, e)
            px = self.x_da_t(self.pos)
            p.setPen(QPen(QColor("#ef4444"), 2))
            p.drawLine(int(px), 0, int(px), self.height())
        else:
            p.setPen(QColor(tc["tenue"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Apri un audio per vedere la forma d'onda")
        p.setPen(QColor(tc["tenue"]))
        f = QFont(p.font())
        f.setPointSize(max(f.pointSize() - 2, 7))
        p.setFont(f)
        p.drawText(4, self.height() - 2, mmss(self.v0))
        p.drawText(self.width() - 60, self.height() - 2, mmss(self.v1))

    # --- mouse
    def mousePressEvent(self, e):
        if self.durata <= 0:
            return
        x = e.position().x()
        t = self.t_da_x(x)
        if self.diar and e.position().y() > self._alto_onda():
            for t0, t1, _c, _e in self.diar:
                if t0 <= t <= t1:
                    self.sel = (t0, t1)
                    self.update()
                    self.selezionato.emit(t0, t1)
                    return
        self._premuto = (x, t)

    def mouseMoveEvent(self, e):
        if self._premuto and abs(e.position().x() - self._premuto[0]) > 4:
            self.sel = (self._premuto[1], self.t_da_x(e.position().x()))
            self.update()

    def mouseReleaseEvent(self, e):
        if not self._premuto:
            return
        x0, t0 = self._premuto
        self._premuto = None
        if abs(e.position().x() - x0) <= 4:
            self.cliccato.emit(t0)
        elif self.sel:
            a, b = sorted(self.sel)
            self.sel = (a, b)
            self.selezionato.emit(a, b)

    def wheelEvent(self, e):
        d = e.angleDelta()
        if abs(d.x()) > abs(d.y()) or e.modifiers() & Qt.ShiftModifier:
            self.scorri(-(d.x() or d.y()) / 1200)
        else:
            self.zoom(0.8 if d.y() > 0 else 1.25, self.t_da_x(e.position().x()))


class Lettore:
    """Riproduzione semplice con sounddevice, con posizione stimata dal tempo trascorso."""

    def __init__(self):
        self.audio = None
        self.inizio_t = 0.0
        self.partito = None
        self.fine_t = None

    def in_riproduzione(self):
        return self.partito is not None

    def posizione(self):
        if self.partito is None:
            return self.inizio_t
        return self.inizio_t + (time.monotonic() - self.partito)

    def suona(self, da, a=None):
        import sounddevice as sd
        sd.stop()
        i0 = int(max(da, 0) * SR)
        i1 = int(a * SR) if a else len(self.audio)
        sd.play(self.audio[i0:i1], SR)
        self.inizio_t, self.fine_t, self.partito = da, (a or len(self.audio) / SR), time.monotonic()

    def ferma(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self.partito is not None:
            self.inizio_t = self.posizione()
        self.partito = None

    def sposta(self, t):
        self.inizio_t = t

    def chiudi(self):
        self.ferma()


class LettoreVideo:
    """Riproduzione di audio e video con Qt Multimedia: posizione esatta e immagine sincronizzata."""

    def __init__(self, video_widget, percorso, con_audio=True):
        self.player = QMediaPlayer()
        if con_audio:
            self.uscita = QAudioOutput()
            self.player.setAudioOutput(self.uscita)
        self.player.setVideoOutput(video_widget)
        self.fine_t = None
        self.audio = None
        self._in_attesa = None  # (posizione, suona_dopo) finché il file non è pronto
        self.player.mediaStatusChanged.connect(self._stato)
        self.player.setSource(QUrl.fromLocalFile(str(percorso)))

    def _pronto(self):
        return self.player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                                             QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.EndOfMedia)

    def _stato(self, stato):
        if self._in_attesa and self._pronto():
            pos, play = self._in_attesa
            self._in_attesa = None
            self.player.setPosition(pos)
            if play:
                self.player.play()
            else:
                self.player.pause()  # mostra il fotogramma in quel punto

    def in_riproduzione(self):
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def posizione(self):
        if self._in_attesa:
            return self._in_attesa[0] / 1000.0
        return self.player.position() / 1000.0

    def suona(self, da, a=None):
        self.fine_t = a
        ms = int(max(da, 0) * 1000)
        if not self._pronto():
            self._in_attesa = (ms, True)
            return
        self.player.setPosition(ms)
        self.player.play()

    def ferma(self):
        if self.in_riproduzione():
            self.player.pause()

    def sposta(self, t):
        ms = int(max(t, 0) * 1000)
        if not self._pronto():
            self._in_attesa = (ms, False)
            return
        self.player.setPosition(ms)
        if not self.in_riproduzione():
            self.player.pause()

    def chiudi(self):
        self._in_attesa = None
        self.player.stop()
        self.player.setSource(QUrl())


class MarcaVociDialog(QDialog):
    """Ascolta un audio, marca i tratti di ogni persona e crea le impronte. Al termine: self.risultato = [(nome, wav)]."""

    def __init__(self, nomi_noti, file_audio=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Crea impronte vocali da un audio o da un video'))
        self.resize(1000, 720)
        self.nomi_noti = list(nomi_noti)
        self.audio = None
        self.file = None
        self.segni = []          # dict: nome, t0, t1
        self.diar = {}           # speaker -> [(t0, t1)]
        self.suggeriti = {}      # speaker -> nome suggerito
        self.risultato = []
        self.lettore = Lettore()
        self.colori = {}

        lay = QVBoxLayout(self)
        intro = QLabel(tr("Ascolta l'audio (o guarda il video della call), <b>trascina sulla forma d'onda</b> per selezionare un tratto in cui parla una sola persona e assegnalo. Rotella = zoom, Maiusc+rotella = scorri, clic = vai lì. Se l'audio è già stato trascritto, sotto vedi i parlanti trovati: clic su un tratto per selezionarlo."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        r1 = QHBoxLayout()
        b_apri = QPushButton(tr('Apri audio o video…'))
        self.l_file = QLabel(tr('Nessun audio'))
        r1.addWidget(b_apri)
        r1.addWidget(self.l_file, 1)
        lay.addLayout(r1)

        self.onda = FormaOnda()
        self.video = QVideoWidget() if VIDEO_OK else None
        self.sp = QSplitter(Qt.Vertical)
        if self.video is not None:
            self.video.setMinimumHeight(180)
            self.sp.addWidget(self.video)
            self.video.setVisible(False)
        self.sp.addWidget(self.onda)
        lay.addWidget(self.sp, 3)

        r2 = QHBoxLayout()
        self.b_play = QPushButton(tr('▶ Ascolta'))
        b_indietro = QPushButton("⏪ 5 s")
        b_avanti = QPushButton("5 s ⏩")
        b_sel = QPushButton(tr('▶ Ascolta selezione'))
        b_zp = QPushButton(tr('Zoom +'))
        b_zm = QPushButton(tr('Zoom −'))
        b_tutto = QPushButton(tr('Tutto'))
        self.l_tempo = QLabel("00:00 / 00:00")
        for w in (self.b_play, b_indietro, b_avanti, b_sel, self.l_tempo):
            r2.addWidget(w)
        r2.addStretch()
        for w in (b_zm, b_zp, b_tutto):
            r2.addWidget(w)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel(tr('Persona:')))
        self.c_persona = QComboBox()
        self.c_persona.setEditable(True)
        self.c_persona.addItems(self.nomi_noti)
        self.c_persona.setCurrentText("")
        self.c_persona.lineEdit().setPlaceholderText(tr('nome della persona'))
        self.c_persona.setMinimumWidth(200)
        r3.addWidget(self.c_persona)
        b_ass = QPushButton(tr('✚ Assegna selezione'))
        b_ass.setProperty("primario", True)
        r3.addWidget(b_ass)
        r3.addSpacing(20)
        self.l_diar = QLabel(tr('Parlante rilevato:'))
        self.c_speaker = QComboBox()
        self.b_speaker = QPushButton(tr('Assegna tutti i suoi tratti'))
        for w in (self.l_diar, self.c_speaker, self.b_speaker):
            r3.addWidget(w)
            w.setVisible(False)
        r3.addStretch()
        lay.addLayout(r3)

        self.tab = QTableWidget(0, 4)
        self.tab.setHorizontalHeaderLabels([tr('Persona'), tr('Inizio'), tr('Fine'), tr('Durata')])
        self.tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.verticalHeader().setVisible(False)
        lay.addWidget(self.tab, 1)

        r4 = QHBoxLayout()
        b_rim = QPushButton(tr('Rimuovi segno'))
        self.l_riepilogo = QLabel("")
        self.l_riepilogo.setWordWrap(True)
        r4.addWidget(b_rim)
        r4.addWidget(self.l_riepilogo, 1)
        lay.addLayout(r4)

        self.cb_consenso = QCheckBox(tr('Le persone marcate sanno che registro la loro impronta vocale e hanno dato il consenso esplicito'))
        lay.addWidget(self.cb_consenso)
        r5 = QHBoxLayout()
        r5.addStretch()
        b_ann = QPushButton(tr('Annulla'))
        self.b_crea = QPushButton(tr('Crea impronte'))
        self.b_crea.setProperty("primario", True)
        r5.addWidget(b_ann)
        r5.addWidget(self.b_crea)
        lay.addLayout(r5)

        b_apri.clicked.connect(self.apri)
        self.b_play.clicked.connect(self.play_pausa)
        b_indietro.clicked.connect(lambda: self.vai(self.lettore.posizione() - 5))
        b_avanti.clicked.connect(lambda: self.vai(self.lettore.posizione() + 5))
        b_sel.clicked.connect(self.ascolta_selezione)
        b_zp.clicked.connect(lambda: self.onda.zoom(0.5, self.lettore.posizione()))
        b_zm.clicked.connect(lambda: self.onda.zoom(2.0, self.lettore.posizione()))
        b_tutto.clicked.connect(lambda: (setattr(self.onda, "v0", 0.0), setattr(self.onda, "v1", max(self.onda.durata, 0.1)),
                                         self.onda.update()))
        b_ass.clicked.connect(self.assegna_selezione)
        self.b_speaker.clicked.connect(self.assegna_speaker)
        self.c_speaker.currentIndexChanged.connect(self._suggerisci_nome)
        b_rim.clicked.connect(self.rimuovi)
        self.tab.cellDoubleClicked.connect(lambda r, _c: self._ascolta_segno(r))
        self.onda.cliccato.connect(self.vai)
        self.b_crea.clicked.connect(self.crea)
        b_ann.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        if file_audio:
            QTimer.singleShot(0, lambda: self.carica(file_audio))

    # --- caricamento
    def apri(self):
        filtro = ("Audio o video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm *.m4v *.avi *.wmv)"
                  ";;Tutti i file (*)")
        f, _ = QFileDialog.getOpenFileName(self, tr('Audio o video da marcare'), str(Path.home()), filtro)
        if f:
            self.carica(f)

    def carica(self, f):
        self.lettore.chiudi()
        self.l_file.setText(tr("Leggo l'audio…"))
        self.repaint()
        try:
            audio = leggi_audio(f)
        except Exception as e:
            self.l_file.setText(tr('Nessun audio'))
            QMessageBox.warning(self, tr('Audio'), str(e))
            return
        self.audio, self.file = audio, Path(f)
        e_video = self.video is not None and self.file.suffix.lower() in VIDEO_EXT
        if e_video:
            self.lettore = LettoreVideo(self.video, self.file)
            self.video.setVisible(True)
            self.sp.setSizes([340, 220])
            if self.height() < 860:
                self.resize(self.width(), 860)
        else:
            self.lettore = Lettore()
            if self.video is not None:
                self.video.setVisible(False)
        self.lettore.audio = audio
        self.lettore.sposta(0.0)
        self.onda.imposta_audio(audio)
        self.segni.clear()
        self._carica_diarizzazione()
        self._aggiorna()
        extra = (" · video" if e_video else "") + (f" · {len(self.diar)} parlanti dalla trascrizione" if self.diar else "")
        self.l_file.setText(f"{self.file.name} · {mmss(len(audio) / SR)}{extra}")

    def _carica_diarizzazione(self):
        """Se accanto all'audio c'è il JSON di WhisperX, mostra i parlanti rilevati e suggerisce i nomi."""
        self.diar, self.suggeriti = {}, {}
        j = self.file.with_suffix(".json")
        if j.exists():
            try:
                dati = json.loads(j.read_text(encoding="utf-8"))
                for s in dati.get("segments", []):
                    if s.get("speaker") and s.get("end", 0) > s.get("start", 0):
                        self.diar.setdefault(s["speaker"], []).append((float(s["start"]), float(s["end"])))
                emb = dati.get("speaker_embeddings") or {}
                if emb:
                    mappa, _, _ = core.abbina(emb, core.carica_voci(), core.carica_impostazioni()["soglia"])
                    self.suggeriti = {k: v for k, v in mappa.items() if not v.startswith("Sconosciuto")}
            except Exception:
                self.diar = {}
        self.c_speaker.blockSignals(True)
        self.c_speaker.clear()
        for i, s in enumerate(sorted(self.diar)):
            tot = sum(b - a for a, b in self.diar[s])
            nome = self.suggeriti.get(s)
            self.c_speaker.addItem(f"{s} ({mmss(tot)})" + (f" ≈ {nome}" if nome else ""), s)
        self.c_speaker.blockSignals(False)
        for w in (self.l_diar, self.c_speaker, self.b_speaker):
            w.setVisible(bool(self.diar))
        grigi = ["#475569", "#0f766e", "#7c3aed", "#b45309", "#be123c", "#1d4ed8", "#4d7c0f", "#a21caf"]
        self.onda.diar = [(a, b, grigi[i % len(grigi)], self.suggeriti.get(s, s))
                          for i, s in enumerate(sorted(self.diar)) for a, b in self.diar[s]]
        self._suggerisci_nome()

    def _suggerisci_nome(self):
        s = self.c_speaker.currentData()
        if s and self.suggeriti.get(s) and not self.c_persona.currentText().strip():
            self.c_persona.setCurrentText(self.suggeriti[s])

    # --- riproduzione
    def _audio_pronto(self):
        if self.audio is None:
            QMessageBox.information(self, tr('Audio'), tr('Apri prima un audio.'))
            return False
        return True

    def play_pausa(self):
        if not self._audio_pronto():
            return
        try:
            if self.lettore.in_riproduzione():
                self.lettore.ferma()
            else:
                pos = self.lettore.posizione()
                self.lettore.suona(0.0 if pos >= self.onda.durata - 0.05 else pos)
        except Exception as e:
            QMessageBox.warning(self, tr('Audio'), tr('Riproduzione non disponibile: {e}', e=e))

    def vai(self, t):
        if self.audio is None:
            return
        t = min(max(t, 0.0), self.onda.durata)
        suonava = self.lettore.in_riproduzione()
        self.lettore.ferma()
        self.lettore.sposta(t)
        if suonava:
            try:
                self.lettore.suona(t)
            except Exception:
                pass
        self.onda.mostra(t)
        self._tick()

    def ascolta_selezione(self):
        if not self._audio_pronto():
            return
        if not self.onda.sel:
            QMessageBox.information(self, tr('Selezione'), tr("Trascina sulla forma d'onda per selezionare un tratto."))
            return
        a, b = sorted(self.onda.sel)
        try:
            self.lettore.suona(a, b)
        except Exception as e:
            QMessageBox.warning(self, tr('Audio'), tr('Riproduzione non disponibile: {e}', e=e))

    def _ascolta_segno(self, riga):
        if 0 <= riga < len(self.segni) and self.audio is not None:
            s = self.segni[riga]
            self.onda.sel = (s["t0"], s["t1"])
            self.onda.mostra(s["t0"])
            try:
                self.lettore.suona(s["t0"], s["t1"])
            except Exception:
                pass

    def _tick(self):
        if self.audio is None:
            return
        pos = self.lettore.posizione()
        if self.lettore.in_riproduzione() and pos >= (self.lettore.fine_t or self.onda.durata):
            self.lettore.ferma()
            pos = self.lettore.posizione()
        self.b_play.setText(tr('⏸ Pausa') if self.lettore.in_riproduzione() else tr('▶ Ascolta'))
        self.onda.pos = pos
        if self.lettore.in_riproduzione():
            self.onda.mostra(pos)
        self.onda.update()
        self.l_tempo.setText(f"{mmss(pos)} / {mmss(self.onda.durata)}")

    # --- marcature
    def _colore(self, nome):
        if nome not in self.colori:
            self.colori[nome] = COLORI[len(self.colori) % len(COLORI)]
        return self.colori[nome]

    def _persona(self):
        nome = self.c_persona.currentText().strip()
        if not core.nome_valido(nome):
            QMessageBox.warning(self, tr('Persona'), tr('Scrivi o scegli il nome della persona, senza caratteri speciali.'))
            return None
        if self.c_persona.findText(nome) < 0:
            self.c_persona.addItem(nome)
        return nome

    def assegna_selezione(self):
        if not self._audio_pronto():
            return
        if not self.onda.sel or abs(self.onda.sel[1] - self.onda.sel[0]) < 0.5:
            QMessageBox.information(self, tr('Selezione'), tr("Trascina sulla forma d'onda per selezionare almeno mezzo secondo."))
            return
        nome = self._persona()
        if not nome:
            return
        a, b = sorted(self.onda.sel)
        self._aggiungi(nome, a, b)
        self.onda.sel = None
        self._aggiorna()

    def assegna_speaker(self):
        s = self.c_speaker.currentData()
        if not s:
            return
        nome = self._persona()
        if not nome:
            return
        for a, b in self.diar.get(s, []):
            self._aggiungi(nome, a, b)
        self._aggiorna()

    def _aggiungi(self, nome, a, b):
        for s in self.segni:  # evita doppioni identici
            if s["nome"] == nome and abs(s["t0"] - a) < 0.05 and abs(s["t1"] - b) < 0.05:
                return
        self.segni.append({"nome": nome, "t0": a, "t1": b})
        self.segni.sort(key=lambda s: s["t0"])

    def rimuovi(self):
        righe = sorted({i.row() for i in self.tab.selectedIndexes()}, reverse=True)
        for r in righe:
            del self.segni[r]
        self._aggiorna()

    def durate(self):
        out = {}
        for s in self.segni:
            out[s["nome"]] = out.get(s["nome"], 0.0) + (s["t1"] - s["t0"])
        return out

    def _aggiorna(self):
        self.tab.setRowCount(len(self.segni))
        for r, s in enumerate(self.segni):
            it = QTableWidgetItem(s["nome"])
            it.setForeground(QColor(self._colore(s["nome"])))
            self.tab.setItem(r, 0, it)
            self.tab.setItem(r, 1, QTableWidgetItem(mmss(s["t0"])))
            self.tab.setItem(r, 2, QTableWidgetItem(mmss(s["t1"])))
            self.tab.setItem(r, 3, QTableWidgetItem(f"{s['t1'] - s['t0']:.1f} s"))
        self.onda.segni = [(s["t0"], s["t1"], self._colore(s["nome"]), s["nome"]) for s in self.segni]
        self.onda.update()
        parti = []
        for nome, d in self.durate().items():
            stato = "✅" if d >= CONSIGLIATI else ("🟡" if d >= MIN_SECONDI else "🔴")
            parti.append(f"{stato} {nome}: {d:.0f} s")
        self.l_riepilogo.setText(("  ·  ".join(parti) + f"   (servono almeno {MIN_SECONDI} s, meglio {CONSIGLIATI}+)")
                                 if parti else tr('Nessun tratto marcato.'))

    # --- creazione
    def crea(self):
        durate = self.durate()
        if not durate:
            QMessageBox.information(self, tr('Niente da creare'), tr('Marca almeno un tratto per una persona.'))
            return
        corte = [n for n, d in durate.items() if d < MIN_SECONDI]
        if corte:
            QMessageBox.warning(self, tr('Tratti troppo corti'),
                                "Per queste persone servono almeno " f"{MIN_SECONDI} secondi: " + ", ".join(corte))
            return
        if not self.cb_consenso.isChecked():
            QMessageBox.warning(self, tr('Consenso'), tr('Le impronte vocali sono dati biometrici: serve il consenso esplicito delle persone. Spunta la casella per confermarlo.'))
            return
        self.lettore.chiudi()
        out = []
        pausa = np.zeros(int(0.3 * SR), dtype=np.int16)
        for nome in durate:
            pezzi = []
            for s in self.segni:
                if s["nome"] == nome:
                    pezzi += [self.audio[int(s["t0"] * SR):int(s["t1"] * SR)], pausa]
            f = dir_temporanea() / f"marcatura_{nome_file(nome)}_{int(time.time())}.wav"
            scrivi_wav(f, np.concatenate(pezzi))
            out.append((nome, str(f)))
        self.risultato = out
        self.accept()

    def reject(self):
        self.lettore.chiudi()
        self.timer.stop()
        super().reject()

    def closeEvent(self, e):
        self.lettore.chiudi()
        self.timer.stop()
        super().closeEvent(e)


class EsportaIphoneDialog(QDialog):
    """Sceglie quali voci portare su Argo per iPhone e fa confermare il consenso. Al termine: self.scelte."""

    def __init__(self, voci, precedenti=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Voci per Argo per iPhone'))
        self.setMinimumWidth(460)
        self.scelte = []
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Scegli le persone che l'iPhone deve riconoscere negli incontri. Porta solo quelle che ti servono davvero: il telefono viaggia con te."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.lista = QListWidget()
        for n in voci:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            spunta = n in precedenti if precedenti else len(voci) == 1
            it.setCheckState(Qt.Checked if spunta else Qt.Unchecked)
            self.lista.addItem(it)
        lay.addWidget(self.lista, 1)
        self.cb_consenso = QCheckBox(tr('Le persone scelte sanno che la loro impronta vocale sarà usata anche sul mio iPhone e hanno dato il consenso esplicito'))
        self.cb_consenso.setStyleSheet("QCheckBox { spacing: 8px; }")
        lay.addWidget(self.cb_consenso)
        nota = QLabel(tr("Sull'iPhone le impronte restano cifrate dal sistema e non finiscono mai nei pacchetti esportati. Una nuova esportazione sostituisce quella precedente."))
        nota.setWordWrap(True)
        nota.setProperty("ruolo", "tenue")
        lay.addWidget(nota)
        bottoni = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bottoni.button(QDialogButtonBox.Ok).setText(tr('Esporta…'))
        bottoni.accepted.connect(self._conferma)
        bottoni.rejected.connect(self.reject)
        lay.addWidget(bottoni)

    def _conferma(self):
        scelte = [self.lista.item(i).text() for i in range(self.lista.count())
                  if self.lista.item(i).checkState() == Qt.Checked]
        if not scelte:
            QMessageBox.information(self, tr('Nessuna voce'), tr('Spunta almeno una persona.'))
            return
        if not self.cb_consenso.isChecked():
            QMessageBox.warning(self, tr('Consenso'), tr('Le impronte vocali sono dati biometrici: conferma il consenso delle persone scelte.'))
            return
        self.scelte = scelte
        self.accept()
