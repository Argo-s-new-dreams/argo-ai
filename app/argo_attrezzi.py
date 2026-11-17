"""argo_attrezzi.py - gli attrezzi di Argo · Cassetta degli attrezzi AI: verbale, documenti riservati, dettatura, traduzione.

Il modello linguistico gira in Ollama sul computer; la trascrizione con faster-whisper, sempre in locale.
"""
import csv
import json
import re
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QMenu, QToolButton,
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

import esporta_word as word
import llm_locale as llm
import tema
import voci_core as core

ESEMPI = Path(__file__).resolve().parent / "esempi"
INDICE_META = core.APP_HOME / "documenti_indice.json"
INDICE_VETT = core.APP_HOME / "documenti_indice.npy"
GLOSSARIO = core.APP_HOME / "glossario.csv"
GLOSSARIO_BASE = [
    ("intelligenza artificiale generativa", "generative AI", "generative KI"),
    ("agente", "agent", "Agent"),
    ("riunione", "meeting", "Besprechung"),
    ("verbale", "minutes", "Protokoll"),
    ("trascrizione", "transcription", "Transkription"),
    ("offerta", "quote", "Angebot"),
    ("accordo di riservatezza", "non-disclosure agreement", "Geheimhaltungsvereinbarung"),
]
LINGUE_TRAD = [("en", "Inglese"), ("de", "Tedesco"), ("it", "Italiano")]
COL_LINGUA = {"it": 0, "en": 1, "de": 2}


def imp():
    return core.carica_impostazioni()


PREFERITI_CHAT = ("gemma3", "qwen3", "llama3", "mistral", "phi")
PREFERITI_EMBED = ("bge-m3", "nomic-embed", "mxbai-embed")


def scegli_preferito(nomi, preferiti):
    """Primo modello che corrisponde all'ordine di preferenza, altrimenti il primo dell'elenco."""
    for pref in preferiti:
        for n in nomi:
            if n.lower().startswith(pref):
                return n
    return nomi[0] if nomi else ""


def completa_modelli(s, chat, emb):
    """Se manca la scelta (o il modello non c'è più) ma Ollama ne ha uno, lo sceglie da solo.
    Ritorna l'elenco dei modelli scelti automaticamente."""
    scelti = []
    if chat and s.get("modello_chat") not in chat:
        s["modello_chat"] = scegli_preferito(chat, PREFERITI_CHAT)
        scelti.append(f"testi: {s['modello_chat']}")
    if emb and s.get("modello_embed") not in emb:
        s["modello_embed"] = scegli_preferito(emb, PREFERITI_EMBED)
        scelti.append(f"documenti: {s['modello_embed']}")
    if scelti:
        core.salva_impostazioni(s)
    return scelti


def pronto_llm(parent, serve_embed=False):
    """Controlla che Ollama risponda e che ci siano i modelli; se manca solo la scelta, la fa da solo."""
    s = imp()
    url = s.get("ollama_url") or llm.DEFAULT_URL
    try:
        chat, emb = llm.elenco_modelli(url)
    except llm.ErroreLLM:
        QMessageBox.warning(parent, "Ollama non è acceso",
                            f"Argo non riesce a parlare con Ollama ({url}).\n\n"
                            "Avvia Ollama (sul Mac: l'icona del lama nella barra dei menu) e riprova.\n"
                            "Se non è installato, scaricalo da ollama.com.")
        return False
    if not chat:
        QMessageBox.warning(parent, "Nessun modello scaricato",
                            "Ollama è acceso ma non ha modelli per i testi.\n\n"
                            "Scaricane uno dal Terminale, per esempio:\n    ollama pull gemma3:12b\n\n"
                            "oppure da Impostazioni → Modello linguistico locale → Scarica un modello.")
        return False
    if serve_embed and not emb:
        QMessageBox.warning(parent, "Manca il modello per i documenti",
                            "Per cercare nei documenti serve un modello di embedding.\n\n"
                            "Scaricalo dal Terminale:\n    ollama pull bge-m3\n\n"
                            "oppure da Impostazioni → Modello linguistico locale → Scarica un modello.")
        return False
    scelti = completa_modelli(s, chat, emb)
    if scelti:
        QMessageBox.information(parent, "Modello scelto in automatico",
                                "Uso " + " e ".join(scelti) + ".\nPuoi cambiarlo in Impostazioni → Modello linguistico locale.")
        segnale_modelli.cambiato.emit()
    return True


# =============================================================== lavoro in background
class Lavoro(QThread):
    """Esegue una funzione lunga fuori dall'interfaccia. fn(lav) può chiamare lav.token(), lav.stato(), lav.fermato()."""
    sig_token = Signal(str)
    sig_stato = Signal(str)
    sig_fine = Signal(object)
    sig_errore = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._stop = False

    def token(self, t):
        self.sig_token.emit(t)

    def stato(self, t):
        self.sig_stato.emit(t)

    def fermato(self):
        return self._stop

    def ferma(self):
        self._stop = True

    def run(self):
        try:
            self.sig_fine.emit(self.fn(self))
        except Exception as e:
            self.sig_errore.emit(str(e))


def visibile(testo):
    """Toglie il 'ragionamento' <think>…</think> (anche se non ancora chiuso) dal testo da mostrare."""
    testo = re.sub(r"<think>.*?</think>\s*", "", testo, flags=re.S)
    return testo.split("<think>")[0]


def chat_llm(lav, messaggi, temperatura=0.3, mostra=True):
    s = imp()
    stato = {"tutto": "", "mostrato": 0}

    def on_token(t):
        stato["tutto"] += t
        vis = visibile(stato["tutto"])
        if len(vis) > stato["mostrato"]:
            lav.token(vis[stato["mostrato"]:])
            stato["mostrato"] = len(vis)

    return llm.chat(messaggi, s["modello_chat"], s["ollama_url"], temperatura,
                    on_token=on_token if mostra else None, stop=lav.fermato, contesto=8192)


# =============================================================== trascrizione rapida (faster-whisper)
_WHISPER = {}


def trascrivi_file(percorso, lingua="it", lav=None):
    """Trascrizione semplice senza parlanti, per dettatura e traduzione."""
    from faster_whisper import WhisperModel

    nome = imp().get("modello_dettatura") or "large-v3-turbo"
    if nome not in _WHISPER:
        if lav:
            lav.stato(f"Carico il modello di trascrizione {nome} (la prima volta può scaricarlo)…")
        _WHISPER.clear()
        _WHISPER[nome] = WhisperModel(nome, device="cpu", compute_type="int8")
    if lav:
        lav.stato("Trascrivo…")
    segmenti, _ = _WHISPER[nome].transcribe(str(percorso), language=lingua or None, vad_filter=True)
    return " ".join(s.text.strip() for s in segmenti).strip()


# =============================================================== base comune per le schede
class SchedaBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lavoro = None
        self.stato = QLabel("")
        self.stato.setWordWrap(True)

    def avvia(self, fn, uscita=None, fine=None, pulsante=None):
        if self.lavoro:
            return
        if uscita is not None:
            uscita.clear()
        self.lavoro = Lavoro(fn, self)
        if uscita is not None:
            self.lavoro.sig_token.connect(lambda t: (uscita.moveCursor(QTextCursor.End), uscita.insertPlainText(t)))
        self.lavoro.sig_stato.connect(self.stato.setText)
        self.t0 = time.time()

        def _fine(r):
            self.lavoro = None
            if pulsante:
                pulsante.setText(self._testo_pulsante)
            self.stato.setText(f"Fatto in {time.time() - self.t0:.0f} s, tutto in locale.")
            if fine:
                fine(r)

        def _err(e):
            self.lavoro = None
            if pulsante:
                pulsante.setText(self._testo_pulsante)
            self.stato.setText("Errore: " + e)

        self.lavoro.sig_fine.connect(_fine)
        self.lavoro.sig_errore.connect(_err)
        if pulsante:
            self._testo_pulsante = pulsante.text()
            pulsante.setText("■ Ferma")
        self.lavoro.start()

    def ferma_o(self, avvio):
        if self.lavoro:
            self.lavoro.ferma()
            self.stato.setText("Interruzione…")
        else:
            avvio()


def area(sola_lettura=False, segnaposto="", filigrana=False):
    """Area di testo dello Stile Argo. Con filigrana=True, finché è vuota mostra il logo in filigrana e il
    segnaposto (che dice cosa fare); la filigrana sparisce da sola al primo testo."""
    w = QPlainTextEdit()
    w.setReadOnly(sola_lettura)
    w.setPlaceholderText(segnaposto)
    if filigrana:
        stato = {"vuota": None}

        def aggiorna():
            vuota = not w.toPlainText()
            if vuota != stato["vuota"]:
                stato["vuota"] = vuota
                tema.imposta_filigrana(w, vuota)

        w.textChanged.connect(aggiorna)
        aggiorna()
    return w


def menu_salva(voci):
    """Un solo pulsante «Salva ▾» con i formati (Stile Argo: al massimo 5 pulsanti visibili per barra).
    voci: [(etichetta, funzione)]."""
    b = QToolButton()
    b.setText("Salva ▾")
    b.setPopupMode(QToolButton.InstantPopup)
    m = QMenu(b)
    for etichetta, fn in voci:
        m.addAction(etichetta, fn)
    b.setMenu(m)
    return b


def copia(testo):
    QGuiApplication.clipboard().setText(testo)


def salva_word(parent, testo, base, titolo=None, sottotitolo=None, nota_ai=True, stato=None):
    """Chiede dove salvare, crea il .docx e lo apre in Word."""
    testo = (testo or "").strip()
    if not testo:
        QMessageBox.information(parent, "Niente da salvare", "Non c'è ancora un testo da esportare.")
        return None
    f, _ = QFileDialog.getSaveFileName(parent, "Salva in Word", str(base), "Documento Word (*.docx)")
    if not f:
        return None
    try:
        out = word.salva_docx(testo, f, titolo, sottotitolo, nota_ai)
    except Exception as e:
        QMessageBox.warning(parent, "Word", f"Non riesco a salvare il documento: {e}")
        return None
    if stato is not None:
        stato.setText(f"Salvato in Word: {out}")
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
    return out


def oggi():
    return time.strftime("%d/%m/%Y")


# =============================================================== 1. Riunione -> verbale
MODELLI_VERBALE = {
    "Verbale della riunione": (
        "Redigi il verbale in Markdown con queste sezioni: ## Partecipanti, ## Argomenti trattati, "
        "## Decisioni, ## Azioni (tabella | Azione | Responsabile | Scadenza |), ## Punti aperti."),
    "Mail di sintesi al cliente": (
        "Scrivi una mail professionale e cordiale al cliente che riassume la riunione: ringraziamento, "
        "punti principali, decisioni, prossimi passi con responsabili e date. Massimo 250 parole."),
    "Solo elenco delle azioni": (
        "Produci solo una tabella Markdown | Azione | Responsabile | Scadenza | con tutte le azioni concordate."),
}
SISTEMA_VERBALE = (
    "Sei un assistente che redige verbali di riunione in italiano. Usa SOLO le informazioni presenti nella "
    "trascrizione. Se un dato manca (responsabile, data) scrivi 'non indicato'. Non inventare nomi, numeri o date. "
    "Le righe della trascrizione hanno il formato [ora] Nome: testo.")


class SchedaVerbale(SchedaBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sorgente = None
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        b_apri = QPushButton("Apri trascrizione…")
        b_es = QPushButton("Usa l'esempio")
        self.c_tipo = QComboBox()
        self.c_tipo.addItems(list(MODELLI_VERBALE))
        self.b_gen = QPushButton("▶ Genera")
        self.b_gen.setProperty("primario", True)
        b_cop = QPushButton("Copia")
        b_salva = menu_salva([("Documento Word (.docx)", self.salva_word), ("Testo Markdown (.md)", self.salva)])
        # Stile Argo · Organizzazione: azione principale prima a sinistra, poi i suoi parametri e gli ingressi;
        # a destra ciò che si fa col risultato.
        for w in (self.b_gen, QLabel("Formato:"), self.c_tipo, b_apri, b_es):
            bar.addWidget(w)
        bar.addStretch()
        for w in (b_cop, b_salva):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.ingresso = area(segnaposto="Incolla qui una trascrizione, oppure aprila da file (*_nomi.txt).")
        self.uscita = area(True, "Il verbale comparirà qui, parola per parola.\n\nPer cominciare: apri una "
                                 "trascrizione (o prova con l'esempio), scegli il formato e premi «Genera».",
                           filigrana=True)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self.ingresso)
        sp.addWidget(self.uscita)
        lay.addWidget(sp, 1)
        lay.addWidget(self.stato)
        b_apri.clicked.connect(self.apri)
        b_es.clicked.connect(lambda: self.carica(ESEMPI / "riunione_esempio_nomi.txt"))
        self.b_gen.clicked.connect(lambda: self.ferma_o(self.genera))
        b_cop.clicked.connect(lambda: copia(self.uscita.toPlainText()))

    def apri(self):
        f, _ = QFileDialog.getOpenFileName(self, "Trascrizione", str(Path.home()), "Testo (*.txt *.md)")
        if f:
            self.carica(f)

    def carica(self, f):
        p = Path(f)
        if p.exists():
            self.sorgente = p
            self.ingresso.setPlainText(p.read_text(encoding="utf-8", errors="replace"))
            self.stato.setText(f"Caricato: {p.name}")

    def genera(self):
        testo = self.ingresso.toPlainText().strip()
        if not testo or not pronto_llm(self):
            return
        istruzione = MODELLI_VERBALE[self.c_tipo.currentText()]

        def fn(lav):
            blocchi = llm.spezza(testo, 9000)
            if len(blocchi) == 1:
                lav.stato("Scrivo…")
                return chat_llm(lav, [{"role": "system", "content": SISTEMA_VERBALE},
                                      {"role": "user", "content": f"{istruzione}\n\nTRASCRIZIONE:\n{testo}"}])
            appunti = []
            for i, b in enumerate(blocchi, 1):
                if lav.fermato():
                    return ""
                lav.stato(f"Riunione lunga: leggo la parte {i} di {len(blocchi)}…")
                appunti.append(chat_llm(lav, [
                    {"role": "system", "content": SISTEMA_VERBALE},
                    {"role": "user", "content": "Estrai in punti elenco: partecipanti, argomenti, decisioni, azioni "
                                                f"(con responsabile e scadenza se dette), punti aperti.\n\nPARTE {i}:\n{b}"}],
                    mostra=False))
            lav.stato("Unisco le parti e scrivo il risultato…")
            return chat_llm(lav, [{"role": "system", "content": SISTEMA_VERBALE},
                                  {"role": "user", "content": f"{istruzione}\n\nAPPUNTI DALLE PARTI DELLA RIUNIONE:\n"
                                                              + "\n\n".join(appunti)}])

        self.avvia(fn, self.uscita, pulsante=self.b_gen)

    def salva(self):
        testo = self.uscita.toPlainText().strip()
        if not testo:
            return
        base = self.sorgente.with_name(self.sorgente.stem.replace("_nomi", "") + "_verbale.md") if self.sorgente \
            else Path.home() / "verbale.md"
        f, _ = QFileDialog.getSaveFileName(self, "Salva verbale", str(base), "Markdown (*.md)")
        if f:
            Path(f).write_text(testo + "\n", encoding="utf-8")
            self.stato.setText(f"Salvato: {f}")


    def salva_word(self):
        tipo = self.c_tipo.currentText()
        titoli = {"Verbale della riunione": "Verbale della riunione",
                  "Mail di sintesi al cliente": "Sintesi della riunione",
                  "Solo elenco delle azioni": "Azioni concordate"}
        nome = (self.sorgente.stem.replace("_nomi", "") if self.sorgente else "riunione")
        cartella = self.sorgente.parent if self.sorgente else Path.home()
        suffisso = {"Verbale della riunione": "_verbale", "Mail di sintesi al cliente": "_sintesi",
                    "Solo elenco delle azioni": "_azioni"}.get(tipo, "_verbale")
        sotto = f"{nome} · {oggi()}"
        salva_word(self, self.uscita.toPlainText(), cartella / f"{nome}{suffisso}.docx",
                   titoli.get(tipo, "Verbale"), sotto, stato=self.stato)


# =============================================================== 2. Documenti riservati
def estrai_testo(percorso):
    """Ritorna lista di (pagina, testo)."""
    p = Path(percorso)
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return [(i + 1, (pg.extract_text() or "")) for i, pg in enumerate(PdfReader(str(p)).pages)]
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        testo = "\n".join(par.text for par in d.paragraphs)
        for t in d.tables:
            for r in t.rows:
                testo += "\n" + " | ".join(c.text for c in r.cells)
        return [(1, testo)]
    return [(1, p.read_text(encoding="utf-8", errors="replace"))]


class SchedaDocumenti(SchedaBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.meta, self.vett = self.carica_indice()
        lay = QVBoxLayout(self)
        sp = QSplitter(Qt.Horizontal)
        sx = QWidget()
        lsx = QVBoxLayout(sx)
        lsx.setContentsMargins(0, 0, 0, 0)
        lsx.addWidget(QLabel("Documenti indicizzati"))
        self.lista = QListWidget()
        lsx.addWidget(self.lista)
        r = QHBoxLayout()
        b_agg = QPushButton("➕ Aggiungi…")
        b_es = QPushButton("Esempio")
        b_svuota = QPushButton("Svuota indice")
        b_svuota.setToolTip("Toglie tutti i documenti dall'indice; i file originali non vengono toccati")
        self.b_svuota = b_svuota
        for b in (b_agg, b_es):
            r.addWidget(b)
        r.addStretch()  # Stile Argo: l'azione che cancella sta in disparte e solo quando c'è qualcosa
        r.addWidget(b_svuota)
        lsx.addLayout(r)
        dx = QWidget()
        ldx = QVBoxLayout(dx)
        ldx.setContentsMargins(0, 0, 0, 0)
        rq = QHBoxLayout()
        self.domanda = QLineEdit()
        self.domanda.setPlaceholderText("Es.: Qual è la durata dell'obbligo di riservatezza? Ci sono penali?")
        self.b_chiedi = QPushButton("Chiedi")
        self.b_chiedi.setProperty("primario", True)
        rq.addWidget(self.domanda)
        rq.addWidget(self.b_chiedi)
        ldx.addLayout(rq)
        self.risposta = area(True, "La risposta comparirà qui, con le fonti.\n\nPer cominciare: aggiungi i "
                                   "documenti a sinistra (o l'esempio), poi scrivi la domanda.", filigrana=True)
        ldx.addWidget(self.risposta, 3)
        rf = QHBoxLayout()
        rf.addWidget(QLabel("Fonti usate per la risposta"))
        rf.addStretch()
        b_word_doc = QPushButton("Salva Word")
        b_word_doc.clicked.connect(self.salva_word)
        rf.addWidget(b_word_doc)
        ldx.addLayout(rf)
        self.ultima = None  # (domanda, estratti)
        self.fonti = QTextBrowser()
        self.fonti.setOpenExternalLinks(False)
        ldx.addWidget(self.fonti, 1)
        sp.addWidget(sx)
        sp.addWidget(dx)
        sp.setSizes([280, 700])
        lay.addWidget(sp, 1)
        lay.addWidget(self.stato)
        b_agg.clicked.connect(self.aggiungi)
        b_es.clicked.connect(lambda: self.indicizza([str(p) for p in sorted(ESEMPI.glob("doc_esempio_*"))]))
        b_svuota.clicked.connect(self.svuota)
        self.b_chiedi.clicked.connect(lambda: self.ferma_o(self.chiedi))
        self.domanda.returnPressed.connect(lambda: self.ferma_o(self.chiedi))
        self.aggiorna_lista()

    # --- indice
    @staticmethod
    def carica_indice():
        try:
            meta = json.loads(INDICE_META.read_text(encoding="utf-8"))
            vett = np.load(INDICE_VETT)
            if len(meta.get("pezzi", [])) == len(vett):
                return meta, vett
        except Exception:
            pass
        return {"modello": "", "pezzi": []}, np.zeros((0, 1), dtype=np.float32)

    def salva_indice(self):
        core.APP_HOME.mkdir(parents=True, exist_ok=True)
        INDICE_META.write_text(json.dumps(self.meta, ensure_ascii=False), encoding="utf-8")
        np.save(INDICE_VETT, self.vett)

    def aggiorna_lista(self):
        self.lista.clear()
        conteggio = {}
        for p in self.meta["pezzi"]:
            conteggio[p["file"]] = conteggio.get(p["file"], 0) + 1
        for f, n in conteggio.items():
            self.lista.addItem(f"{Path(f).name}  ({n} estratti)")
        if hasattr(self, "b_svuota"):
            self.b_svuota.setVisible(bool(conteggio))

    def svuota(self):
        if QMessageBox.question(self, "Svuota", "Eliminare l'indice dei documenti? I file originali non vengono toccati.") \
                == QMessageBox.Yes:
            self.meta, self.vett = {"modello": "", "pezzi": []}, np.zeros((0, 1), dtype=np.float32)
            self.salva_indice()
            self.aggiorna_lista()

    def aggiungi(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Documenti", str(Path.home()),
                                                "Documenti (*.pdf *.docx *.txt *.md)")
        if files:
            self.indicizza(files)

    def indicizza(self, files):
        if not files or not pronto_llm(self, serve_embed=True):
            return
        s = imp()
        if self.meta["pezzi"] and self.meta.get("modello") != s["modello_embed"]:
            QMessageBox.information(self, "Indice ricreato",
                                    "Il modello di embedding è cambiato: svuoto l'indice e lo ricostruisco con i nuovi documenti.")
            self.meta, self.vett = {"modello": "", "pezzi": []}, np.zeros((0, 1), dtype=np.float32)

        def fn(lav):
            nuovi = []
            gia = {p["file"] for p in self.meta["pezzi"]}
            for f in files:
                if f in gia:
                    continue
                lav.stato(f"Leggo {Path(f).name}…")
                for pagina, testo in estrai_testo(f):
                    for blocco in llm.spezza(testo, 1200, 150):
                        if blocco.strip():
                            nuovi.append({"file": f, "pagina": pagina, "testo": blocco.strip()})
            if not nuovi:
                return 0
            lav.stato(f"Calcolo gli embedding di {len(nuovi)} estratti con {s['modello_embed']}…")
            v = llm.embed([n["testo"] for n in nuovi], s["modello_embed"], s["ollama_url"])
            self.vett = v if len(self.vett) == 0 else np.vstack([self.vett, v])
            self.meta["pezzi"].extend(nuovi)
            self.meta["modello"] = s["modello_embed"]
            self.salva_indice()
            return len(nuovi)

        self.avvia(fn, fine=lambda n: (self.aggiorna_lista(), self.stato.setText(f"Indicizzati {n} nuovi estratti.")))

    def chiedi(self):
        q = self.domanda.text().strip()
        if not q or not pronto_llm(self, serve_embed=True):
            return
        if not self.meta["pezzi"]:
            QMessageBox.information(self, "Nessun documento", "Aggiungi prima almeno un documento (o usa l'esempio).")
            return
        s = imp()
        self.fonti.clear()

        def fn(lav):
            lav.stato("Cerco i passaggi pertinenti…")
            vq = llm.embed([q], s["modello_embed"], s["ollama_url"])[0]
            top = llm.piu_simili(vq, self.vett, k=5)
            estratti = []
            for n, (i, sim) in enumerate(top, 1):
                p = self.meta["pezzi"][i]
                estratti.append((n, p, sim))
            contesto = "\n\n".join(f"[{n}] ({Path(p['file']).name}, pag. {p['pagina']})\n{p['testo']}"
                                   for n, p, _ in estratti)
            lav.stato("Scrivo la risposta…")
            risposta = chat_llm(lav, [
                {"role": "system", "content": "Rispondi in italiano usando SOLO gli estratti forniti. Cita le fonti "
                 "con [1], [2]… Se gli estratti non contengono la risposta, scrivi chiaramente che il documento non lo dice."},
                {"role": "user", "content": f"ESTRATTI:\n{contesto}\n\nDOMANDA: {q}"}], temperatura=0.1)
            return risposta, estratti

        def fine(r):
            if not r:
                return
            _, estratti = r
            self.ultima = (q, estratti)
            html = "".join(f"<p><b>[{n}]</b> {Path(p['file']).name}, pag. {p['pagina']} "
                           f"<span style='color:gray'>(somiglianza {sim:.2f})</span><br>"
                           f"<i>{p['testo'][:280].replace('<', '&lt;')}…</i></p>" for n, p, sim in estratti)
            self.fonti.setHtml(html)

        self.avvia(fn, self.risposta, fine, self.b_chiedi)


    def salva_word(self):
        risposta = self.risposta.toPlainText().strip()
        if not risposta or not self.ultima:
            QMessageBox.information(self, "Niente da salvare", "Fai prima una domanda sui documenti.")
            return
        q, estratti = self.ultima
        fonti = "\n".join(f"- **[{n}]** {Path(p['file']).name}, pag. {p['pagina']}: "
                          f"*{p['testo'][:240].strip().replace(chr(10), ' ')}…*" for n, p, _ in estratti)
        testo = f"## Domanda\n\n{q}\n\n## Risposta\n\n{risposta}\n\n## Fonti\n\n{fonti}\n"
        salva_word(self, testo, Path.home() / "risposta_documenti.docx", "Domanda sui documenti riservati",
                   oggi(), stato=self.stato)


# =============================================================== 3. Dettatura e mail
STILI_DETTATURA = {
    "Mail professionale": "Trasforma la dettatura in una mail professionale in italiano, con oggetto, saluti e firma generica. "
                          "Mantieni tutti i contenuti, togli ripetizioni ed esitazioni.",
    "Mail informale": "Trasforma la dettatura in una mail cordiale e informale in italiano, con oggetto. Mantieni i contenuti.",
    "Appunto ordinato": "Trasforma la dettatura in un appunto ordinato con titoli brevi ed elenchi puntati.",
    "Messaggio breve (Teams/WhatsApp)": "Trasforma la dettatura in un messaggio breve e chiaro, massimo 3 frasi.",
    "Solo trascrizione": None,
}


class SchedaDettatura(SchedaBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.flusso = None
        self.campioni = []
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.b_reg = QPushButton("● Registra")
        self.b_reg.setProperty("primario", True)
        b_file = QPushButton("Da file audio…")
        self.c_stile = QComboBox()
        self.c_stile.addItems(list(STILI_DETTATURA))
        b_rif = QPushButton("Riscrivi")
        b_cop = QPushButton("Copia")
        b_word = QPushButton("Salva Word")
        b_word.clicked.connect(lambda: salva_word(self, self.uscita.toPlainText(), Path.home() / "dettatura.docx",
                                                  None, oggi(), stato=self.stato))
        for w in (self.b_reg, QLabel("Formato:"), self.c_stile, b_file):
            bar.addWidget(w)
        bar.addStretch()
        for w in (b_rif, b_cop, b_word):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.grezzo = area(segnaposto="Qui compare la trascrizione grezza (modificabile).")
        self.uscita = area(True, "Qui compare il testo riscritto nel formato scelto.\n\nPer cominciare: premi "
                                 "«Registra» e parla, oppure scegli un file audio.", filigrana=True)
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.grezzo)
        sp.addWidget(self.uscita)
        lay.addWidget(sp, 1)
        lay.addWidget(self.stato)
        self.b_reg.clicked.connect(self.registra_o_stop)
        b_file.clicked.connect(self.da_file)
        b_rif.clicked.connect(lambda: self.ferma_o(self.riscrivi))
        b_cop.clicked.connect(lambda: copia(self.uscita.toPlainText()))

    def registra_o_stop(self):
        if self.flusso is None:
            try:
                import sounddevice as sd
            except Exception as e:
                QMessageBox.warning(self, "Microfono", f"Registrazione non disponibile: {e}\nUsa «Da file audio…».")
                return
            self.campioni = []
            try:
                self.flusso = sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                             callback=lambda d, *a: self.campioni.append(d.copy()))
                self.flusso.start()
            except Exception as e:
                self.flusso = None
                QMessageBox.warning(self, "Microfono", f"Impossibile usare il microfono: {e}\n"
                                    "Controlla Impostazioni di Sistema → Privacy e sicurezza → Microfono.")
                return
            self.b_reg.setText("■ Stop")
            self.stato.setText("Registrazione in corso… parla pure.")
        else:
            self.flusso.stop()
            self.flusso.close()
            self.flusso = None
            self.b_reg.setText("● Registra")
            if not self.campioni:
                self.stato.setText("Nessun audio registrato.")
                return
            audio = np.concatenate(self.campioni)[:, 0]
            f = Path(tempfile.gettempdir()) / "argo_dettatura.wav"
            with wave.open(str(f), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
            self.elabora(f)

    def da_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Audio o video", str(Path.home()),
                                           "Audio o video (*.wav *.m4a *.mp3 *.aac *.flac *.ogg *.opus *.mp4 *.mov *.mkv *.webm *.m4v)")
        if f:
            self.elabora(Path(f))

    def elabora(self, f):
        stile = STILI_DETTATURA[self.c_stile.currentText()]
        if stile and not pronto_llm(self):
            return

        def fn(lav):
            testo = trascrivi_file(f, "it", lav)
            lav.token("")
            return testo

        def fine(testo):
            self.grezzo.setPlainText(testo)
            if stile:
                self.riscrivi()

        self.avvia(fn, fine=fine)

    def riscrivi(self):
        testo = self.grezzo.toPlainText().strip()
        stile = STILI_DETTATURA[self.c_stile.currentText()]
        if not testo:
            return
        if not stile:
            self.uscita.setPlainText(testo)
            return
        if not pronto_llm(self):
            return
        self.avvia(lambda lav: chat_llm(lav, [
            {"role": "system", "content": "Sei un assistente di scrittura. Non aggiungere fatti che non sono nella dettatura."},
            {"role": "user", "content": f"{stile}\n\nDETTATURA:\n{testo}"}], temperatura=0.4), self.uscita)


# =============================================================== 4. Traduzione con glossario
class SchedaTraduzione(SchedaBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        b_txt = QPushButton("Apri testo…")
        b_aud = QPushButton("Trascrivi audio…")
        self.c_lingua = QComboBox()
        for k, t in LINGUE_TRAD:
            self.c_lingua.addItem(t, k)
        self.b_trad = QPushButton("▶ Traduci")
        self.b_trad.setProperty("primario", True)
        b_cop = QPushButton("Copia")
        b_word = QPushButton("Salva Word")
        b_word.clicked.connect(lambda: salva_word(
            self, self.uscita.toPlainText(), Path.home() / f"traduzione_{self.c_lingua.currentData()}.docx",
            None, f"Traduzione in {self.c_lingua.currentText().lower()} · {oggi()}", stato=self.stato))
        for w in (self.b_trad, QLabel("in:"), self.c_lingua, b_txt, b_aud):
            bar.addWidget(w)
        bar.addStretch()
        for w in (b_cop, b_word):
            bar.addWidget(w)
        lay.addLayout(bar)
        sp = QSplitter(Qt.Horizontal)
        self.ingresso = area(segnaposto="Incolla qui il testo da tradurre, oppure aprilo da file.")
        self.uscita = area(True, "La traduzione comparirà qui.\n\nI termini del glossario qui sotto vengono "
                                 "imposti al modello.", filigrana=True)
        sp.addWidget(self.ingresso)
        sp.addWidget(self.uscita)
        gl = QGroupBox("Glossario (IT / EN / DE) - modificabile")
        lgl = QVBoxLayout(gl)
        self.tab = QTableWidget(0, 3)
        self.tab.setHorizontalHeaderLabels(["Italiano", "English", "Deutsch"])
        self.tab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        lgl.addWidget(self.tab)
        rg = QHBoxLayout()
        b_add = QPushButton("+ Riga")
        b_del = QPushButton("− Riga")
        b_imp = QPushButton("Importa CSV…")
        b_sav = QPushButton("Salva glossario")
        for b in (b_add, b_del, b_imp, b_sav):
            rg.addWidget(b)
        rg.addStretch()
        lgl.addLayout(rg)
        sp2 = QSplitter(Qt.Vertical)
        sp2.addWidget(sp)
        sp2.addWidget(gl)
        sp2.setSizes([380, 220])
        lay.addWidget(sp2, 1)
        lay.addWidget(self.stato)
        self.carica_glossario()
        b_txt.clicked.connect(self.apri_testo)
        b_aud.clicked.connect(self.trascrivi_audio)
        self.b_trad.clicked.connect(lambda: self.ferma_o(self.traduci))
        b_cop.clicked.connect(lambda: copia(self.uscita.toPlainText()))
        b_add.clicked.connect(lambda: self.tab.insertRow(self.tab.rowCount()))
        b_del.clicked.connect(lambda: self.tab.removeRow(self.tab.currentRow()) if self.tab.currentRow() >= 0 else None)
        b_imp.clicked.connect(self.importa)
        b_sav.clicked.connect(self.salva_glossario)

    def righe(self):
        out = []
        for r in range(self.tab.rowCount()):
            celle = [(self.tab.item(r, c).text().strip() if self.tab.item(r, c) else "") for c in range(3)]
            if any(celle):
                out.append(tuple(celle))
        return out

    def imposta(self, righe):
        self.tab.setRowCount(0)
        for riga in righe:
            r = self.tab.rowCount()
            self.tab.insertRow(r)
            for c in range(3):
                self.tab.setItem(r, c, QTableWidgetItem(riga[c] if c < len(riga) else ""))

    def carica_glossario(self):
        try:
            with open(GLOSSARIO, encoding="utf-8-sig", newline="") as f:
                self.imposta([r for r in csv.reader(f, delimiter=";")][1:])
        except Exception:
            self.imposta(GLOSSARIO_BASE)

    def salva_glossario(self):
        core.APP_HOME.mkdir(parents=True, exist_ok=True)
        with open(GLOSSARIO, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["it", "en", "de"])
            w.writerows(self.righe())
        self.stato.setText(f"Glossario salvato ({len(self.righe())} termini).")

    def importa(self):
        f, _ = QFileDialog.getOpenFileName(self, "Glossario CSV (it;en;de)", str(Path.home()), "CSV (*.csv)")
        if not f:
            return
        with open(f, encoding="utf-8-sig", newline="") as fh:
            campione = fh.read(2048)
            fh.seek(0)
            sep = ";" if campione.count(";") >= campione.count(",") else ","
            righe = list(csv.reader(fh, delimiter=sep))
        if righe and [c.strip().lower() for c in righe[0][:3]] == ["it", "en", "de"]:
            righe = righe[1:]
        self.imposta(righe)
        self.stato.setText(f"Importati {len(righe)} termini (premi «Salva glossario» per tenerli).")

    def apri_testo(self):
        f, _ = QFileDialog.getOpenFileName(self, "Testo", str(Path.home()), "Testo (*.txt *.md)")
        if f:
            self.ingresso.setPlainText(Path(f).read_text(encoding="utf-8", errors="replace"))

    def trascrivi_audio(self):
        f, _ = QFileDialog.getOpenFileName(self, "Audio o video", str(Path.home()),
                                           "Audio o video (*.wav *.m4a *.mp3 *.aac *.flac *.ogg *.opus *.mp4 *.mov *.mkv *.webm *.m4v)")
        if f:
            self.avvia(lambda lav: trascrivi_file(f, None, lav), fine=self.ingresso.setPlainText)

    def termini_usati(self, testo, dest):
        """Coppie (termine trovato nel testo -> termine nella lingua di destinazione)."""
        basso = testo.lower()
        out = []
        for riga in self.righe():
            target = riga[COL_LINGUA[dest]]
            if not target:
                continue
            for c, termine in enumerate(riga):
                if termine and c != COL_LINGUA[dest] and re.search(r"\b" + re.escape(termine.lower()) + r"\b", basso):
                    out.append((termine, target))
                    break
        return out

    def traduci(self):
        testo = self.ingresso.toPlainText().strip()
        if not testo or not pronto_llm(self):
            return
        dest = self.c_lingua.currentData()
        nome_lingua = self.c_lingua.currentText().lower()
        vincoli = self.termini_usati(testo, dest)

        def fn(lav):
            glos = "\n".join(f'- "{a}" → "{b}"' for a, b in vincoli) or "(nessun termine del glossario presente)"
            blocchi = llm.spezza(testo, 4000)
            parti = []
            for i, b in enumerate(blocchi, 1):
                if lav.fermato():
                    break
                lav.stato(f"Traduco la parte {i} di {len(blocchi)}…" if len(blocchi) > 1 else "Traduco…")
                if i > 1:
                    lav.token("\n\n")
                parti.append(chat_llm(lav, [
                    {"role": "system", "content": f"Sei un traduttore professionale. Traduci in {nome_lingua}. "
                     "Usa OBBLIGATORIAMENTE la terminologia del glossario. Mantieni nomi propri, orari e formattazione "
                     "(per esempio le righe [ora] Nome: testo). Restituisci solo la traduzione."},
                    {"role": "user", "content": f"GLOSSARIO OBBLIGATORIO:\n{glos}\n\nTESTO:\n{b}"}], temperatura=0.1))
            return "\n\n".join(parti)

        self.avvia(fn, self.uscita, pulsante=self.b_trad)
        if vincoli:
            self.stato.setText(f"Glossario applicato: {len(vincoli)} termini.")


# =============================================================== impostazioni Ollama
class _SegnaleModelli(QObject):
    cambiato = Signal()


segnale_modelli = _SegnaleModelli()


class PannelloOllama(QGroupBox):
    """Riquadro per la scheda Impostazioni: server Ollama e modelli."""
    cambiato = Signal()

    def __init__(self, parent=None):
        super().__init__("Modello linguistico locale (Ollama) - per gli attrezzi Verbale, Documenti, Dettatura e Traduzione", parent)
        s = imp()
        f = QFormLayout(self)
        self.e_url = QLineEdit(s["ollama_url"])
        self.c_chat = QComboBox()
        self.c_embed = QComboBox()
        self.c_dett = QComboBox()
        for m in ("large-v3-turbo", "medium", "small"):
            self.c_dett.addItem(m)
        self.c_dett.setCurrentText(s.get("modello_dettatura") or "large-v3-turbo")
        r = QHBoxLayout()
        r.addWidget(self.e_url)
        b_ver = QPushButton("Verifica e aggiorna elenco")
        r.addWidget(b_ver)
        f.addRow("Indirizzo Ollama:", r)
        f.addRow("Modello per testi:", self.c_chat)
        f.addRow("Modello per documenti:", self.c_embed)
        f.addRow("Trascrizione rapida:", self.c_dett)
        r2 = QHBoxLayout()
        self.e_pull = QLineEdit()
        self.e_pull.setPlaceholderText("nome modello da scaricare, es. bge-m3")
        b_pull = QPushButton("Scarica")
        r2.addWidget(self.e_pull)
        r2.addWidget(b_pull)
        f.addRow("Scarica un modello:", r2)
        self.l_stato = QLabel("")
        self.l_stato.setWordWrap(True)
        f.addRow("", self.l_stato)
        b_salva = QPushButton("Salva modelli")
        f.addRow("", b_salva)
        b_ver.clicked.connect(self.verifica)
        b_salva.clicked.connect(self.salva)
        b_pull.clicked.connect(self.scarica)
        self.lavoro = None
        segnale_modelli.cambiato.connect(lambda: self.verifica(silenzioso=True))
        self.verifica(silenzioso=True)

    def verifica(self, silenzioso=False):
        url = self.e_url.text().strip()
        try:
            chat, emb = llm.elenco_modelli(url)
        except llm.ErroreLLM as e:
            self.l_stato.setText("❌ " + str(e) + " Installa Ollama da ollama.com e avvialo.")
            return
        s = imp()
        scelti = completa_modelli(s, chat, emb)
        for combo, voci, attuale in ((self.c_chat, chat, s.get("modello_chat")),
                                     (self.c_embed, emb, s.get("modello_embed"))):
            combo.clear()
            combo.addItems(voci)
            if attuale in voci:
                combo.setCurrentText(attuale)
        avviso = "" if llm.e_locale(url) else " ⚠️ L'indirizzo NON è locale: i testi lascerebbero il computer."
        self.l_stato.setText(f"✅ Ollama risponde: {len(chat)} modelli per testi, {len(emb)} per documenti.{avviso}")
        if scelti:
            self.l_stato.setText(self.l_stato.text() + " Scelti in automatico e salvati: " + ", ".join(scelti) + ".")
            self.cambiato.emit()
        if not chat:
            self.l_stato.setText(self.l_stato.text() + " Scarica un modello per i testi, es. «gemma3:12b».")
        if not silenzioso and not emb:
            self.l_stato.setText(self.l_stato.text() + " Per i documenti scarica un modello di embedding, es. «bge-m3».")

    def salva(self):
        s = imp()
        s.update(ollama_url=self.e_url.text().strip() or llm.DEFAULT_URL,
                 modello_chat=self.c_chat.currentText(), modello_embed=self.c_embed.currentText(),
                 modello_dettatura=self.c_dett.currentText())
        core.salva_impostazioni(s)
        self.l_stato.setText("Modelli salvati.")
        self.cambiato.emit()

    def scarica(self):
        nome = self.e_pull.text().strip()
        if not nome or self.lavoro:
            return
        url = self.e_url.text().strip()
        self.lavoro = Lavoro(lambda lav: llm.scarica_modello(nome, url, lav.stato, lav.fermato), self)
        self.lavoro.sig_stato.connect(lambda t: self.l_stato.setText(f"Scarico {nome}: {t}"))
        self.lavoro.sig_fine.connect(lambda _: (setattr(self, "lavoro", None), self.verifica()))
        self.lavoro.sig_errore.connect(lambda e: (setattr(self, "lavoro", None), self.l_stato.setText("❌ " + e)))
        self.lavoro.start()
