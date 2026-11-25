"""crm_incontri.py - finestra «Invia a Dynamics 365» di un incontro: scelta caso per caso.

Per ogni contatto della relazione Argo cerca in Dynamics contatti, lead e account già presenti e propone:
- contatto esistente (stessa email) → si aggancia lì;
- lead aperto esistente → si aggiorna con nota e attività;
- altrimenti → nuovo lead.
L'utente può cambiare destinazione, correggere i dati o saltare il contatto. Poi: nota con la relazione,
foto allegate, azioni come attività. Esito salvato nell'incontro (argo-crm.json) con i link ai record.
"""
from lingua import tr
import json
import mimetypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import argo_attrezzi as attrezzi
import crm_dynamics as crm
import relazione_incontro as rel

FILE_CRM = "argo-crm.json"
CAMPI = [("nome", "Nome"), ("cognome", "Cognome"), ("ruolo", "Ruolo"), ("azienda", "Azienda"),
         ("email", "Email"), ("telefono", "Telefono"), ("cellulare", "Cellulare")]
ICONE = {"contact": "👤 Contatto esistente", "lead": "🎯 Lead esistente", "account": "🏢 Account esistente"}


def esito(cartella):
    try:
        return json.loads((Path(cartella) / FILE_CRM).read_text(encoding="utf-8"))
    except Exception:
        return None


class _BloccoContatto(QGroupBox):
    def __init__(self, contatto, parent=None):
        nome = " ".join(x for x in (contatto.get("nome"), contatto.get("cognome")) if x) or "Contatto"
        super().__init__(nome, parent)
        self.contatto = dict(contatto)
        lay = QVBoxLayout(self)
        riga = QHBoxLayout()
        riga.addWidget(QLabel(tr('Destinazione:')))
        self.destinazione = QComboBox()
        self.destinazione.addItem(tr('⏳ Cerco in Dynamics…'), None)
        self.destinazione.setEnabled(False)
        riga.addWidget(self.destinazione, 1)
        lay.addLayout(riga)
        forma = QFormLayout()
        self.campi = {}
        for chiave, etichetta in CAMPI:
            e = QLineEdit(contatto.get(chiave) or "")
            self.campi[chiave] = e
            forma.addRow(etichetta + ":", e)
        lay.addLayout(forma)
        self.destinazione.currentIndexChanged.connect(self._abilita_campi)

    def proponi(self, trovati):
        """Riempie le destinazioni con i risultati della ricerca e sceglie la più sensata."""
        self.destinazione.clear()
        self.destinazione.addItem(tr('➕ Nuovo lead'), ("nuovo", None))
        for tipo, id_record, descrizione in trovati:
            self.destinazione.addItem(f"{ICONE[tipo]}: {descrizione}", (tipo, id_record))
        self.destinazione.addItem(tr('⏭ Salta questo contatto'), ("salta", None))
        tipi = [d[0] for d in trovati]
        email = (self.contatto.get("email") or "").lower()
        scelta = 0
        # Preferenza: contatto con la stessa email, poi lead aperto con la stessa email; altrimenti nuovo lead
        for preferito in ("contact", "lead"):
            for i, (tipo, _id, descrizione) in enumerate(trovati):
                if tipo == preferito and email and email in descrizione.lower():
                    scelta = i + 1
                    break
            if scelta:
                break
        self.destinazione.setCurrentIndex(scelta)
        self.destinazione.setEnabled(True)
        self._abilita_campi()
        if trovati and not scelta:
            self.setTitle(self.title() + f"  ·  {len(trovati)} possibili corrispondenze da controllare")

    def _abilita_campi(self):
        dati = self.destinazione.currentData()
        nuovo = bool(dati) and dati[0] == "nuovo"
        for e in self.campi.values():
            e.setEnabled(nuovo)

    def valori(self):
        return {k: e.text().strip() for k, e in self.campi.items()} | {"note": self.contatto.get("note", "")}


class DialogoCRM(QDialog):
    def __init__(self, cartella, sessione, parent=None):
        super().__init__(parent)
        self.cartella = Path(cartella)
        self.sessione = sessione
        dati = rel.carica(cartella)
        self.relazione = dati.get("relazione") or {}
        self.setWindowTitle(tr('Invia a Dynamics 365 Sales'))
        self.resize(720, 760)
        lay = QVBoxLayout(self)
        intro = QLabel(tr("<b>{get}</b><br>Ambiente: {ambiente}. Su Dynamics va solo ciò che confermi qui: mai l'audio, mai le impronte vocali.", get=self.relazione.get('titolo', sessione.get('titolo', '')), ambiente=crm.ambiente()))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        contatti = self.relazione.get("contatti") or [{}]
        self.blocchi = [_BloccoContatto(c) for c in contatti]
        contenitore = QWidget()
        cl = QVBoxLayout(contenitore)
        for b in self.blocchi:
            cl.addWidget(b)
        cl.addStretch()
        scorri = QScrollArea()
        scorri.setWidgetResizable(True)
        scorri.setWidget(contenitore)
        lay.addWidget(scorri, 1)

        opzioni = QGroupBox(tr('Cosa allegare a ogni destinazione'))
        ol = QVBoxLayout(opzioni)
        self.cb_nota = QCheckBox(tr('Relazione come nota'))
        self.cb_nota.setChecked(True)
        n_foto = len(self.sessione.get("foto", []))
        self.cb_foto = QCheckBox(tr('Foto come allegati ({n_foto})', n_foto=n_foto))
        self.cb_foto.setChecked(n_foto > 0)
        self.cb_foto.setEnabled(n_foto > 0)
        n_azioni = len(self.relazione.get("azioni") or [])
        self.cb_azioni = QCheckBox(tr('Azioni come attività ({n_azioni}), solo sulla prima destinazione', n_azioni=n_azioni))
        self.cb_azioni.setChecked(n_azioni > 0)
        self.cb_azioni.setEnabled(n_azioni > 0)
        for cb in (self.cb_nota, self.cb_foto, self.cb_azioni):
            ol.addWidget(cb)
        lay.addWidget(opzioni)

        self.l_stato = QLabel(tr('Cerco contatti, lead e account già presenti…'))
        self.l_stato.setWordWrap(True)
        self.l_stato.setProperty("ruolo", "tenue")
        lay.addWidget(self.l_stato)
        riga = QHBoxLayout()
        self.b_invia = QPushButton(tr('☁️ Invia a Dynamics'))
        self.b_invia.setProperty("primario", True)
        self.b_invia.setEnabled(False)
        self.b_invia.clicked.connect(self.invia)
        riga.addWidget(self.b_invia)
        riga.addStretch()
        b_annulla = QPushButton(tr('Annulla'))
        b_annulla.clicked.connect(self.reject)
        riga.addWidget(b_annulla)
        lay.addLayout(riga)
        self.lavoro = None
        self._cerca()

    # -- ricerca dei duplicati
    def _cerca(self):
        contatti = [b.contatto for b in self.blocchi]

        def fn(_lav):
            return [crm.cerca(c) if any(c.get(k) for k in ("email", "cognome", "azienda")) else [] for c in contatti]

        self.lavoro = attrezzi.Lavoro(fn, self)
        self.lavoro.sig_fine.connect(self._trovati)
        self.lavoro.sig_errore.connect(self._errore_ricerca)
        self.lavoro.start()

    def _trovati(self, risultati):
        for b, trovati in zip(self.blocchi, risultati):
            b.proponi(trovati)
        n = sum(len(t) for t in risultati)
        self.l_stato.setText(("Trovati record simili: controlla le destinazioni proposte." if n
                              else "Nessun duplicato trovato: verranno creati nuovi lead.")
                             + " Correggi i dati se serve, poi «Invia a Dynamics».")
        self.b_invia.setEnabled(True)
        self.lavoro = None

    def _errore_ricerca(self, errore):
        self.lavoro = None
        for b in self.blocchi:
            b.proponi([])
        self.b_invia.setEnabled(True)
        self.l_stato.setText(tr('⚠️ Ricerca dei duplicati non riuscita: {errore} Puoi comunque creare nuovi lead, ma controlla prima in Dynamics.', errore=errore))

    # -- invio
    def _foto(self):
        for f in self.sessione.get("foto", []):
            p = self.cartella / f.get("file", "")
            if p.exists():
                yield p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg"

    def invia(self):
        scelte = []
        for b in self.blocchi:
            tipo, id_record = b.destinazione.currentData() or ("salta", None)
            if tipo != "salta":
                scelte.append((tipo, id_record, b.valori()))
        if not scelte:
            QMessageBox.information(self, tr('Niente da inviare'), tr('Tutti i contatti sono impostati su «Salta».'))
            return
        testo = rel.senza_immagini((self.cartella / rel.FILE_TESTO).read_text(encoding="utf-8")) if (self.cartella / rel.FILE_TESTO).exists() else ""
        titolo = self.relazione.get("titolo") or self.sessione.get("titolo", "Incontro")
        tipo_incontro = self.relazione.get("tipo", "")
        azioni = (self.relazione.get("azioni") or []) if self.cb_azioni.isChecked() else []
        con_nota, con_foto = self.cb_nota.isChecked(), self.cb_foto.isChecked()
        foto = list(self._foto()) if con_foto else []

        def fn(lav):
            record = []
            for n, (tipo, id_record, valori) in enumerate(scelte):
                if tipo == "nuovo":
                    lav.stato(f"Creo il lead di {valori.get('nome', '')} {valori.get('cognome', '')}…")
                    id_record = crm.crea_lead(valori, self.relazione, tipo_incontro)
                    tipo = "lead"
                nome = " ".join(x for x in (valori.get("nome"), valori.get("cognome")) if x)
                if con_nota and testo:
                    lav.stato("Aggiungo la relazione come nota…")
                    crm.crea_nota(tipo, id_record, f"Relazione incontro · {titolo}", testo)
                for i, allegato in enumerate(foto, 1):
                    lav.stato(f"Allego la foto {i} di {len(foto)}…")
                    crm.crea_nota(tipo, id_record, f"Foto {i} · {titolo}", "Foto scattata durante l'incontro", allegato)
                if n == 0:
                    for i, azione in enumerate(azioni, 1):
                        lav.stato(f"Creo l'attività {i} di {len(azioni)}…")
                        crm.crea_attivita(tipo, id_record, azione)
                record.append({"tipo": tipo, "id": id_record, "nome": nome or valori.get("azienda", ""),
                               "link": crm.link(tipo, id_record)})
            return record

        self.b_invia.setEnabled(False)
        self.lavoro = attrezzi.Lavoro(fn, self)
        self.lavoro.sig_stato.connect(self.l_stato.setText)
        self.lavoro.sig_fine.connect(self._inviato)
        self.lavoro.sig_errore.connect(self._errore_invio)
        self.lavoro.start()

    def _inviato(self, record):
        self.lavoro = None
        precedente = esito(self.cartella) or {}
        storico = precedente.get("storico", [])
        if precedente.get("record"):
            storico.append({"inviato": precedente.get("inviato"), "record": precedente["record"]})
        (self.cartella / FILE_CRM).write_text(json.dumps({
            "inviato": datetime.now().strftime("%Y-%m-%d %H:%M"), "ambiente": crm.ambiente(),
            "record": record, "storico": storico}, ensure_ascii=False, indent=2), encoding="utf-8")
        elenco = "<br>".join(f"• <a href='{r['link']}'>{r['nome'] or r['tipo']}</a> ({r['tipo']})" for r in record)
        box = QMessageBox(self)
        box.setWindowTitle(tr('Inviato a Dynamics 365'))
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setText(tr('Fatto. Record aggiornati:<br>{elenco}', elenco=elenco))
        box.exec()
        self.accept()

    def _errore_invio(self, errore):
        self.lavoro = None
        self.b_invia.setEnabled(True)
        self.l_stato.setText(f"⚠️ {errore}")
        QMessageBox.warning(self, tr('Invio non riuscito'), tr('{errore}\n\nI record già creati restano in Dynamics: controllali prima di riprovare.', errore=errore))
