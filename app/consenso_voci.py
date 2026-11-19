"""consenso_voci.py - attivazione del riconoscimento delle voci e consenso delle persone, voce per voce.

Le impronte vocali usate per riconoscere una persona possono essere dati biometrici (art. 9 GDPR). Argo:
- tiene il riconoscimento spento finché l'utente non lo attiva (e l'IT può vietarlo con i criteri);
- usa una voce solo se è registrato il consenso della persona, con la data (voci/<Nome>/consenso.json).
"""
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)

import diagnostica
import voci_core as core

SPIEGAZIONE = ("Argo riconosce una persona confrontando la sua voce con un'impronta salvata su questo computer. "
               "Le impronte vocali che servono a riconoscere qualcuno possono essere <b>dati biometrici</b> "
               "(art. 9 GDPR): servono il <b>consenso</b> della persona e un motivo chiaro. Le impronte restano qui, "
               "non vanno in nessun cloud, e puoi eliminarle quando vuoi.")


class _ElencoNomi(QDialog):
    def __init__(self, titolo, testo, nomi, conferma, ack=None, parent=None, minimo=1):
        super().__init__(parent)
        self.setWindowTitle(titolo)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        t = QLabel(testo)
        t.setWordWrap(True)
        lay.addWidget(t)
        self.ack = None
        if ack:
            self.ack = QCheckBox(ack)
            lay.addWidget(self.ack)
        self.caselle = []
        if nomi:
            area = QScrollArea()
            area.setWidgetResizable(True)
            dentro = QWidget()
            dl = QVBoxLayout(dentro)
            for n in nomi:
                c = QCheckBox(conferma.format(nome=n))
                c.nome = n
                dl.addWidget(c)
                self.caselle.append(c)
            dl.addStretch(1)
            area.setWidget(dentro)
            lay.addWidget(area, 1)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        self.minimo = minimo
        for c in self.caselle + ([self.ack] if self.ack else []):
            c.toggled.connect(self._abilita)
        self._abilita()

    def _abilita(self):
        ok = (self.ack is None or self.ack.isChecked()) and \
            sum(c.isChecked() for c in self.caselle) >= min(self.minimo, len(self.caselle))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(ok)

    def confermati(self):
        return [c.nome for c in self.caselle if c.isChecked()]


def attiva(parent=None):
    """Attiva il riconoscimento. Per le voci già salvate senza consenso chiede di confermarlo una per una:
    quelle non confermate restano salvate ma non vengono usate. Ritorna True se ora è attivo."""
    if core.riconoscimento_vietato():
        QMessageBox.information(parent, "Riconoscimento delle voci",
                                "Il riconoscimento delle voci è disattivato dall'IT con i criteri aziendali.")
        return False
    if core.riconoscimento_attivo():
        return True
    senza = core.senza_consenso()
    testo = SPIEGAZIONE + "<br><br>Attivalo solo se ti serve davvero e solo per persone che hanno acconsentito."
    if senza:
        testo += ("<br><br>Hai già queste voci salvate. Spunta quelle per cui la persona ha dato il consenso: "
                  "le altre restano salvate ma <b>non vengono usate</b> finché non lo confermi (pagina Voci).")
    d = _ElencoNomi("Attivare il riconoscimento delle voci?", testo, senza, "{nome} ha acconsentito a essere "
                    "riconosciuto da Argo", ack="Ho capito: riconoscerò solo persone che hanno dato il consenso",
                    parent=parent, minimo=0)
    d.bb.button(QDialogButtonBox.Ok).setText("Attiva")
    if d.exec() != QDialog.Accepted:
        return False
    for n in d.confermati():
        core.registra_consenso(n, "confermato all'attivazione del riconoscimento")
    core.imposta_riconoscimento(True)
    diagnostica.log.info("riconoscimento delle voci attivato · voci confermate %d su %d senza consenso",
                         len(d.confermati()), len(senza))
    return True


def disattiva():
    core.imposta_riconoscimento(False)
    diagnostica.log.info("riconoscimento delle voci disattivato")


def chiedi(nomi, parent=None, come="dato prima di salvare l'impronta"):
    """Consenso per le voci nuove (o senza consenso) prima di salvarne l'impronta. Ritorna i nomi utilizzabili."""
    if not core.riconoscimento_attivo() and not attiva(parent):
        return []
    nomi = list(dict.fromkeys(nomi))
    da_chiedere = [n for n in nomi if core.consenso(n) is None]
    if not da_chiedere:
        return nomi
    d = _ElencoNomi("Consenso delle persone",
                    "Prima di salvare un'impronta vocale serve il consenso della persona a essere riconosciuta "
                    "da Argo. Spunta chi l'ha dato: per gli altri l'impronta non viene salvata.",
                    da_chiedere, "{nome} ha acconsentito a essere riconosciuto da Argo", parent=parent)
    if d.exec() != QDialog.Accepted:
        return [n for n in nomi if n not in da_chiedere]
    for n in d.confermati():
        core.registra_consenso(n, come)
    return [n for n in nomi if n not in da_chiedere or n in d.confermati()]
