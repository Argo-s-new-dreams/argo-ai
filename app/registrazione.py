"""registrazione.py - pagina Registra: registra riunioni in presenza e call Teams (microfono + audio del computer).

Due modalità:
  Live      trascrive mentre registri e cancella ogni blocco audio appena il suo testo è salvato:
            alla fine resta solo la trascrizione, mai la registrazione intera
  Archivia  salva la registrazione completa in Documenti/Argo/Registrazioni; la trascrivi quando vuoi

L'IT può limitare le modalità con criteri.json → "registrazione": "completa" | "solo_live" | "nessuna".
"""
import json
import math
import sys
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QProcess, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget,
)

import cattura_audio as ca
import criteri
import live_core as live
import voci_core as core

QUI = Path(__file__).resolve().parent

INFORMATIVA = {
    "live": ("Avviso: per redigere il verbale trascrivo questa riunione con Argo, un'applicazione che funziona "
             "solo sul mio computer. L'audio non viene conservato: è cancellato man mano che viene trascritto, "
             "resta solo il testo. Se non siete d'accordo, ditelo ora o scrivetelo in chat e mi fermo."),
    "archivia": ("Avviso: registro questa riunione con Argo, un'applicazione che funziona solo sul mio computer, "
                 "per trascriverla e redigere il verbale. La registrazione resta sul mio computer e la cancello dopo "
                 "il verbale. Se non siete d'accordo, ditelo ora o scrivetelo in chat e mi fermo."),
}


def cartella_registrazioni():
    c = core.carica_impostazioni().get("cartella_registrazioni") or str(Path.home() / "Documents" / "Argo" / "Registrazioni")
    p = Path(c)
    p.mkdir(parents=True, exist_ok=True)
    return p


def modalita_consentite():
    regola = criteri.carica().get("registrazione", "completa")
    return {"completa": ("live", "archivia"), "solo_live": ("live",), "nessuna": ()}.get(regola, ("live", "archivia"))


def percentuale(livello):
    """Livello RMS → 0-100 su scala in dB (da -60 a 0 dBFS)."""
    db = 20 * math.log10(max(livello, 1e-6))
    return int(max(0, min(100, (db + 60) / 60 * 100)))


class Ponte(QObject):
    """Porta gli eventi dal thread audio al thread dell'interfaccia."""
    nuovo_blocco = Signal(str)


class DialogoConsenso(QDialog):
    def __init__(self, modo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prima di registrare")
        lay = QVBoxLayout(self)
        t = QLabel("<b>Chi partecipa deve saperlo.</b> Una registrazione fatta con Argo, a differenza di quella "
                   "di Teams, <b>non avvisa</b> gli altri partecipanti. Informali prima di iniziare: "
                   "puoi incollare in chat il testo qui sotto.")
        t.setWordWrap(True)
        lay.addWidget(t)
        self.testo = QPlainTextEdit(INFORMATIVA[modo])
        self.testo.setFixedHeight(110)
        lay.addWidget(self.testo)
        b_copia = QPushButton("Copia l'avviso")
        b_copia.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.testo.toPlainText()))
        lay.addWidget(b_copia)
        self.ok = QCheckBox("Ho informato i partecipanti e nessuno si è opposto")
        lay.addWidget(self.ok)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Avvia")
        bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ok.toggled.connect(bb.button(QDialogButtonBox.Ok).setEnabled)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SchedaRegistra(QWidget):
    def __init__(self, finestra=None, parent=None):
        super().__init__(parent)
        self.finestra = finestra
        self.mixer = None
        self.modo = None
        self.registrando = False
        # Live
        self.tagliatore = None
        self.sessione = None
        self.motore = None
        self.motore_pronto = False
        self.coda = []
        self.in_lavoro = None
        self.chiusura = False  # registrazione ferma, si finisce di trascrivere
        self._buf_out = b""
        self.avviso = ""  # ultimo problema su un blocco, resta visibile accanto allo stato
        # Archivia
        self.wav = None
        self.file_archivio = None
        self._lock_wav = threading.Lock()
        self.risultato = None
        self._controllate_sospese = False
        self.ponte = Ponte()
        self.ponte.nuovo_blocco.connect(self._blocco_pronto)

        lay = QVBoxLayout(self)
        intro = QLabel("Registra riunioni in presenza e call Teams: Argo prende il <b>microfono</b> e "
                       "l'<b>audio del computer</b> (le voci degli altri partecipanti). Tutto resta su questo computer.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.r_live = QRadioButton("Live: trascrive mentre registri e cancella l'audio appena trascritto. "
                                   "Alla fine resta solo il testo.")
        self.r_arch = QRadioButton("Archivia: salva la registrazione completa e la trascrivi dopo, dal Trascrittore.")
        self.gruppo = QButtonGroup(self)
        for r in (self.r_live, self.r_arch):
            self.gruppo.addButton(r)
            lay.addWidget(r)
        consentite = modalita_consentite()
        self.r_live.setEnabled("live" in consentite)
        self.r_arch.setEnabled("archivia" in consentite)
        (self.r_live if "live" in consentite else self.r_arch).setChecked(True)

        self.e_titolo = QLineEdit()
        self.e_titolo.setPlaceholderText("Titolo della riunione (facoltativo)")
        lay.addWidget(self.e_titolo)

        bar = QHBoxLayout()
        self.b_avvia = QPushButton("● Avvia")
        self.b_avvia.setProperty("primario", True)
        self.b_avvia.clicked.connect(self.avvia_o_ferma)
        self.b_scarta = QPushButton("Scarta l'audio rimasto e concludi")
        self.b_scarta.clicked.connect(self.scarta_e_concludi)
        self.b_scarta.hide()
        self.b_riavvia = QPushButton("Riavvia la trascrizione")
        self.b_riavvia.clicked.connect(self._avvia_motore)
        self.b_riavvia.hide()
        self.b_verbale = QPushButton("Apri nel Verbale →")
        self.b_verbale.clicked.connect(self.apri_verbale)
        self.b_coda = QPushButton("Metti in coda nel Trascrittore →")
        self.b_coda.clicked.connect(self.metti_in_coda)
        self.b_cartella = QPushButton("Apri cartella")
        self.b_cartella.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(
            Path(self.risultato).parent if self.risultato else cartella_registrazioni()))))
        for b in (self.b_verbale, self.b_coda):
            b.hide()
        for b in (self.b_avvia, self.b_scarta, self.b_riavvia):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.b_verbale, self.b_coda, self.b_cartella):
            bar.addWidget(b)
        lay.addLayout(bar)

        # ---- sorgenti: dispositivo, volume (anche durante la registrazione), livello
        imp = core.carica_impostazioni()
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        self.l_rec = QLabel("")
        self.l_rec.setProperty("ruolo", "titolo")
        g.addWidget(self.l_rec, 0, 0, 1, 5)
        self.c_mic = QComboBox()
        self.c_sis = QComboBox()
        self.v_mic = QSlider(Qt.Horizontal)
        self.v_sis = QSlider(Qt.Horizontal)
        self.l_vmic = QLabel()
        self.l_vsis = QLabel()
        self.m_mic = QProgressBar()
        self.m_sis = QProgressBar()
        righe = ((self.c_mic, self.v_mic, self.l_vmic, self.m_mic, "Microfono", "registra_volume_mic"),
                 (self.c_sis, self.v_sis, self.l_vsis, self.m_sis, "Audio del computer", "registra_volume_sistema"))
        for i, (combo, vol, etich, metro, nome, chiave) in enumerate(righe, 1):
            combo.setMinimumWidth(260)
            vol.setRange(0, 200)
            vol.setValue(int(imp.get(chiave, 100)))
            vol.setFixedWidth(140)
            vol.setToolTip("Volume di questa sorgente nella registrazione (si può cambiare anche mentre registri)")
            etich.setFixedWidth(42)
            metro.setRange(0, 100)
            metro.setTextVisible(False)
            metro.setFixedHeight(8)
            g.addWidget(QLabel(nome), i, 0)
            g.addWidget(combo, i, 1)
            g.addWidget(vol, i, 2)
            g.addWidget(etich, i, 3)
            g.addWidget(metro, i, 4)
            vol.valueChanged.connect(self._volumi)
        self.b_elenco = QPushButton("↻")
        self.b_elenco.setToolTip("Aggiorna l'elenco dei dispositivi (dopo aver collegato cuffie o microfoni)")
        self.b_elenco.setFixedWidth(36)
        self.b_elenco.clicked.connect(self._riempi_sorgenti)
        g.addWidget(self.b_elenco, 1, 5)
        self.l_sorgenti = QLabel("")
        self.l_sorgenti.setProperty("ruolo", "tenue")
        self.l_sorgenti.setWordWrap(True)
        g.addWidget(self.l_sorgenti, 3, 0, 1, 6)
        g.setColumnStretch(4, 1)
        lay.addLayout(g)
        self._riempi_sorgenti()
        self._volumi()

        self.testo = QPlainTextEdit()
        self.testo.setReadOnly(True)
        self.testo.setPlaceholderText("In modalità Live la trascrizione compare qui, blocco dopo blocco "
                                      "(con 20-45 secondi di ritardo).\n\n"
                                      "Consiglio: nelle call usa le cuffie, così il microfono non riprende anche "
                                      "le voci che escono dagli altoparlanti.")
        lay.addWidget(self.testo, 1)
        self.stato = QLabel("")
        self.stato.setWordWrap(True)
        lay.addWidget(self.stato)
        if not consentite:
            self.b_avvia.setEnabled(False)
            self.stato.setText("La registrazione è disattivata dai criteri aziendali impostati dall'IT.")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._aggiorna)

    # ------------------------------------------------------------ sorgenti
    def _riempi_sorgenti(self):
        imp = core.carica_impostazioni()
        voluto_mic = self.c_mic.currentData() if self.c_mic.count() else imp.get("registra_microfono", "")
        voluto_sis = self.c_sis.currentData() if self.c_sis.count() else imp.get("registra_sistema", "auto")
        if not self.c_sis.count() and imp.get("registra_audio_sistema") is False and voluto_sis == "auto":
            voluto_sis = "nessuna"  # impostazione delle versioni precedenti
        for combo, voci, voluto in ((self.c_mic, ca.elenco_microfoni(), voluto_mic),
                                    (self.c_sis, ca.elenco_sistema(), voluto_sis)):
            combo.blockSignals(True)
            combo.clear()
            for valore, etichetta in voci:
                combo.addItem(etichetta, valore)
            i = combo.findData(voluto)
            if i < 0 and voluto:  # dispositivo salvato ma ora scollegato: resta visibile e segnalato
                combo.addItem(f"{voluto.removeprefix('dev:')} (non collegato)", voluto)
                i = combo.count() - 1
            combo.setCurrentIndex(max(i, 0))
            combo.blockSignals(False)

    def _volumi(self):
        self.l_vmic.setText(f"{self.v_mic.value()}%")
        self.l_vsis.setText(f"{self.v_sis.value()}%")
        if self.mixer:
            self.mixer.g_mic = self.v_mic.value() / 100
            self.mixer.g_sis = self.v_sis.value() / 100

    def _salva_sorgenti(self):
        s = core.carica_impostazioni()
        s.update(registra_microfono=self.c_mic.currentData() or "", registra_sistema=self.c_sis.currentData() or "auto",
                 registra_volume_mic=self.v_mic.value(), registra_volume_sistema=self.v_sis.value())
        s.pop("registra_audio_sistema", None)
        core.salva_impostazioni(s)

    # ------------------------------------------------------------ sessioni rimaste a metà
    def showEvent(self, e):
        super().showEvent(e)
        if not self._controllate_sospese:
            self._controllate_sospese = True
            QTimer.singleShot(0, self.controlla_sospese)

    def controlla_sospese(self):
        if self.registrando or self.sessione:
            return
        for s in live.Sessione.in_sospeso():
            n = len(s.blocchi_in_attesa())
            fatti = len(s.risultati())
            box = QMessageBox(self)
            box.setWindowTitle("Sessione Live non conclusa")
            box.setText(f"La sessione Live «{s.meta['titolo']}» ({s.meta['inizio'][:16].replace('T', ' ')}) "
                        f"non è stata conclusa.\n\nTesto già salvato: {fatti} blocchi. Audio ancora da trascrivere: "
                        f"{n} blocchi.")
            b_fin = box.addButton("Trascrivi il resto e concludi", QMessageBox.AcceptRole) if n else None
            b_txt = box.addButton("Cancella l'audio e salva il testo", QMessageBox.DestructiveRole)
            box.addButton("Decidi dopo", QMessageBox.RejectRole)
            box.exec()
            if b_fin is not None and box.clickedButton() is b_fin:
                self._riprendi(s)
                return  # una alla volta
            if box.clickedButton() is b_txt:
                s.scarta_blocchi()
                self._mostra_fine(s.concludi())

    def _riprendi(self, s):
        self.sessione = s
        self.modo = "live"
        self.chiusura = True
        self.coda = [str(f) for f in s.blocchi_in_attesa()]
        for r in s.risultati():
            for seg in r["segmenti"]:
                self._scrivi_riga(s.parlanti.nome(seg["speaker"]), seg)
        self.b_avvia.setEnabled(False)
        self.b_scarta.show()
        self.timer.start(300)
        self._avvia_motore()

    # ------------------------------------------------------------ avvio e arresto
    def avvia_o_ferma(self):
        if self.registrando:
            self.ferma()
        else:
            self.avvia()

    def avvia(self):
        modo = "live" if self.r_live.isChecked() else "archivia"
        if modo not in modalita_consentite():
            return
        if modo == "live" and not core.leggi_token():
            QMessageBox.warning(self, "Token mancante", "Per la Live serve il token Hugging Face (Impostazioni).")
            return
        if DialogoConsenso(modo, self).exec() != QDialog.Accepted:
            return
        self._salva_sorgenti()
        self.modo = modo
        self.testo.clear()
        self.risultato = None
        for b in (self.b_verbale, self.b_coda):
            b.hide()
        titolo = self.e_titolo.text().strip() or "Riunione"
        try:
            if modo == "live":
                self.sessione = live.Sessione.nuova(titolo, cartella_registrazioni())
                self.tagliatore = live.Tagliatore()
                self.coda, self.in_lavoro, self.chiusura, self.avviso = [], None, False, ""
            else:
                nome = datetime.now().strftime("%Y-%m-%d %H%M ") + "".join(
                    ch if ch.isalnum() or ch in " -_" else " " for ch in titolo).strip()[:60]
                self.file_archivio = cartella_registrazioni() / f"{nome}.wav"
                self.wav = wave.open(str(self.file_archivio), "wb")
                self.wav.setnchannels(1)
                self.wav.setsampwidth(2)
                self.wav.setframerate(ca.SR)
            self.mixer = ca.Mixer(self._audio, sistema=self.c_sis.currentData() or "auto",
                                  microfono=self.c_mic.currentData() or None,
                                  guadagno_mic=self.v_mic.value() / 100, guadagno_sis=self.v_sis.value() / 100)
            self.mixer.avvia()
        except Exception as e:
            self._pulisci_dopo_errore()
            QMessageBox.warning(self, "Registrazione", f"Impossibile registrare: {e}\n\nSul Mac: Impostazioni di "
                                "Sistema → Privacy e sicurezza → Microfono, abilita Argo AI.")
            return
        sorgenti = self.mixer.mic.nome + (f" + {self.mixer.sis.nome}" if self.mixer.sis else "")
        avviso = ""
        if self.c_sis.currentData() != "nessuna" and not self.mixer.sis:
            avviso = (" ⚠️ Audio del computer non disponibile: registro solo il microfono, le voci degli altri "
                      f"partecipanti alla call non saranno incluse. ({self.mixer.avviso_sistema})")
        self.l_sorgenti.setText("Sorgenti: " + sorgenti + avviso)
        self.registrando = True
        self.b_avvia.setText("■ Ferma")
        for w in (self.r_live, self.r_arch, self.c_mic, self.c_sis, self.b_elenco, self.e_titolo):
            w.setEnabled(False)
        self.timer.start(200)
        if modo == "live":
            self._avvia_motore()

    def _audio(self, x):
        """Thread del mixer: ogni 100 ms."""
        if self.modo == "archivia":
            with self._lock_wav:
                if self.wav:
                    self.wav.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        elif self.tagliatore is not None and self.sessione is not None:
            for blocco, voce in self.tagliatore.aggiungi(x):
                self._consegna(blocco, voce)

    def _consegna(self, blocco, voce):
        if voce:
            f = self.sessione.aggiungi_blocco(blocco)
            self.ponte.nuovo_blocco.emit(str(f))
        else:
            self.sessione.avanza(len(blocco) / ca.SR)

    def ferma(self):
        if not self.registrando:
            return
        self.registrando = False
        self._salva_sorgenti()
        self.mixer.ferma()
        self.b_avvia.setText("● Avvia")
        if self.modo == "archivia":
            with self._lock_wav:
                self.wav.close()
                self.wav = None
            self.timer.stop()
            self._sblocca()
            self.risultato = str(self.file_archivio)
            self.l_rec.setText("")
            self.stato.setText(f"Registrazione salvata: {self.file_archivio.name} "
                               f"({live.mmss(self.mixer.secondi)}).")
            self.b_coda.show()
            self.mixer = None
            return
        for blocco, voce in self.tagliatore.svuota():
            self._consegna(blocco, voce)
        self.tagliatore = None
        self.mixer = None
        self.chiusura = True
        self.b_avvia.setEnabled(False)
        self.b_scarta.show()
        self._prossimo()

    def _sblocca(self):
        consentite = modalita_consentite()
        self.r_live.setEnabled("live" in consentite)
        self.r_arch.setEnabled("archivia" in consentite)
        for w in (self.c_mic, self.c_sis, self.b_elenco, self.e_titolo):
            w.setEnabled(True)
        self.b_avvia.setEnabled(bool(consentite))

    def _pulisci_dopo_errore(self):
        if self.mixer:
            self.mixer.ferma()
        self.mixer = None
        if self.wav:
            self.wav.close()
            self.wav = None
            try:
                self.file_archivio.unlink()
            except Exception:
                pass
        if self.sessione:
            self.sessione.elimina()
            self.sessione = None
        self.tagliatore = None

    # ------------------------------------------------------------ motore di trascrizione (processo separato)
    def _avvia_motore(self):
        self.b_riavvia.hide()
        if self.motore and self.motore.state() != QProcess.NotRunning:
            return
        self.motore_pronto = False
        self.in_lavoro = None
        self._buf_out = b""
        self.motore = QProcess(self)
        env = self.motore.processEnvironment()
        for k, v in core.env_processo().items():
            env.insert(k, v)
        self.motore.setProcessEnvironment(env)
        self.motore.setProcessChannelMode(QProcess.MergedChannels)
        self.motore.readyReadStandardOutput.connect(self._leggi_motore)
        self.motore.finished.connect(self._motore_finito)
        self.motore.setWorkingDirectory(str(QUI))
        self.motore.start(sys.executable, ["-u", str(QUI / "live_motore.py")])
        self.stato.setText("Avvio della trascrizione Live…")

    def _leggi_motore(self):
        self._buf_out += bytes(self.motore.readAllStandardOutput())
        *righe, self._buf_out = self._buf_out.split(b"\n")
        for r in righe:
            r = r.decode("utf-8", "replace").strip()
            if not r.startswith("@@ARGO "):
                continue
            try:
                m = json.loads(r[7:])
            except Exception:
                continue
            self._messaggio(m)

    def _messaggio(self, m):
        tipo = m.get("tipo")
        if tipo == "stato":
            self.stato.setText(m.get("msg", ""))
        elif tipo == "pronto":
            self.motore_pronto = True
            self.stato.setText("Trascrizione Live pronta.")
            self._prossimo()
        elif tipo == "risultato" and self.sessione:
            righe = self.sessione.registra_risultato(m["blocco"], m.get("segmenti"), m.get("emb"))
            for nome, seg in righe:
                self._scrivi_riga(nome, seg)
            self.in_lavoro = None
            self._prossimo()
        elif tipo == "errore":
            if m.get("blocco") and m["blocco"] == self.in_lavoro:
                # si passa al blocco successivo; quello fallito viene cancellato alla conclusione
                self.avviso = f" ⚠️ Un blocco non è stato trascritto: {m.get('msg')}"
                self.in_lavoro = None
                self._prossimo()
            else:
                self.stato.setText("Errore: " + m.get("msg", ""))

    def _motore_finito(self, *_):
        self.motore_pronto = False
        if self.sessione and (self.coda or self.in_lavoro):
            if self.in_lavoro:
                self.coda.insert(0, self.in_lavoro)
                self.in_lavoro = None
            self.stato.setText("⚠️ La trascrizione Live si è fermata. I blocchi non ancora trascritti sono al "
                               "sicuro in una cartella privata: premi «Riavvia la trascrizione».")
            self.b_riavvia.show()

    def _blocco_pronto(self, f):
        self.coda.append(f)
        self._prossimo()

    def _prossimo(self):
        if not self.sessione:
            return
        if self.in_lavoro is None and self.coda and self.motore_pronto:
            self.in_lavoro = self.coda.pop(0)
            self.motore.write((json.dumps({"blocco": self.in_lavoro}) + "\n").encode("utf-8"))
        if self.chiusura and not self.coda and self.in_lavoro is None and not self.registrando:
            self._concludi()

    def scarta_e_concludi(self):
        if QMessageBox.question(self, "Concludere?", "L'audio non ancora trascritto verrà cancellato e il suo "
                                "contenuto andrà perso. Il testo già trascritto viene salvato. Procedere?") != QMessageBox.Yes:
            return
        self.coda = []
        self._ferma_motore()
        self.in_lavoro = None
        if self.sessione:
            self.sessione.scarta_blocchi()
        self._concludi()

    def _ferma_motore(self):
        if self.motore and self.motore.state() != QProcess.NotRunning:
            try:
                self.motore.finished.disconnect(self._motore_finito)
            except Exception:
                pass
            self.motore.write(b'{"fine": true}\n')
            if not self.motore.waitForFinished(3000):
                self.motore.kill()
                self.motore.waitForFinished(2000)
        self.motore = None
        self.motore_pronto = False

    def _concludi(self):
        s, self.sessione = self.sessione, None
        self._ferma_motore()
        self.timer.stop()
        self.chiusura = False
        self.b_scarta.hide()
        self.b_riavvia.hide()
        self._sblocca()
        self.l_rec.setText("")
        self._mostra_fine(s.concludi() if s else None)

    def _mostra_fine(self, out):
        if out:
            self.risultato = str(out)
            self.stato.setText(f"✅ Trascrizione salvata: {Path(out).name}. L'audio è stato cancellato.")
            self.b_verbale.show()
        else:
            self.stato.setText("Sessione conclusa: non è stato trascritto alcun parlato. L'audio è stato cancellato.")

    # ------------------------------------------------------------ interfaccia
    def _scrivi_riga(self, nome, seg):
        self.testo.appendPlainText(f"[{live.mmss(seg['start'])}] {nome}: {seg['text']}")

    def _aggiorna(self):
        if self.registrando and self.mixer:
            mic, sis = self.mixer.livelli()
            self.m_mic.setValue(percentuale(mic))
            self.m_sis.setValue(percentuale(sis) if self.mixer.sis else 0)
            self.l_rec.setText(f"● REC  {live.mmss(self.mixer.secondi)}" + ("  · Live" if self.modo == "live" else ""))
        else:
            self.m_mic.setValue(0)
            self.m_sis.setValue(0)
        if self.modo == "live" and self.sessione:
            attesa = len(self.coda) + (1 if self.in_lavoro else 0)
            if self.chiusura:
                self.l_rec.setText("Sto finendo di trascrivere…")
            if self.motore_pronto:
                self.stato.setText(f"Blocchi da trascrivere: {attesa}" + (" (uno in corso)" if self.in_lavoro else "") +
                                   ". L'audio di ogni blocco viene cancellato appena il suo testo è salvato." + self.avviso)

    def apri_verbale(self):
        if self.finestra and self.risultato:
            self.finestra.tab_verbale.carica(self.risultato)
            self.finestra.vai_a(self.finestra.tab_verbale)

    def metti_in_coda(self):
        if self.finestra and self.risultato:
            self.finestra.aggiungi_file([self.risultato])
            self.finestra.tabs.setCurrentWidget(self.finestra.pag_coda)

    # ------------------------------------------------------------ chiusura di Argo
    def occupata(self):
        return self.registrando or bool(self.sessione)

    def chiudi(self):
        """Argo si chiude: si ferma tutto. I blocchi Live non trascritti restano per il recupero al prossimo avvio."""
        if self.registrando:
            self.registrando = False
            if self.mixer:
                self.mixer.ferma()
            if self.modo == "archivia":
                with self._lock_wav:
                    if self.wav:
                        self.wav.close()
                        self.wav = None
            elif self.tagliatore is not None and self.sessione:
                for blocco, voce in self.tagliatore.svuota():
                    self._consegna(blocco, voce)
        self._ferma_motore()
