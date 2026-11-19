"""esporta_word.py - trasforma i testi di Argo (Markdown semplice o trascrizioni) in documenti Word (.docx).

Gestisce: titoli (#, ##, ###), elenchi puntati e numerati, tabelle Markdown, **grassetto**, *corsivo*,
`codice`, righe di trascrizione "[00:00:12] Nome: testo" e la riga "Oggetto:" delle mail.
Usa solo python-docx: tutto resta su questo computer.
"""
import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

BLU = RGBColor(0x1F, 0x4E, 0x79)
GRIGIO = RGBColor(0x80, 0x80, 0x80)
NOTA_TRASCRIZIONE = ("Trascrizione automatica realizzata con Argo · Cassetta degli attrezzi AI, in locale. "
                     "Nomi dei parlanti e testo possono contenere errori.")
NOTA_AI = ("Testo generato con Argo · Cassetta degli attrezzi AI, con un modello linguistico locale. "
           "Rileggilo e verificane i contenuti prima di inviarlo.")

NOTA_AI_CLOUD = ("Testo generato con Argo · Cassetta degli attrezzi AI; per alcuni attrezzi con un modello "
                 "linguistico nel cloud (Impostazioni › Modelli cloud). Rileggilo e verificane i contenuti prima di inviarlo.")


def _qualche_cloud():
    """Vero se almeno un attrezzo usa un modello cloud: allora non si può scrivere «locale»."""
    try:
        import cloud
        return any(cloud.e_cloud(a) for a in cloud.NOMI_ATTREZZI)
    except Exception:
        return False


RE_INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`)")
RE_TRASCR = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]{1,60}):\s*(.*)$")
RE_NUM = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
RE_PUNTO = re.compile(r"^(\s*)[-*•]\s+(.*)$")
RE_TITOLO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
RE_SEPARATORE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _testo_formattato(par, testo, grassetto=False):
    """Aggiunge testo al paragrafo interpretando grassetto, corsivo e codice."""
    for pezzo in RE_INLINE.split(testo):
        if not pezzo:
            continue
        run = None
        if (pezzo.startswith("**") and pezzo.endswith("**")) or (pezzo.startswith("__") and pezzo.endswith("__")):
            run = par.add_run(pezzo[2:-2])
            run.bold = True
        elif pezzo.startswith("`") and pezzo.endswith("`"):
            run = par.add_run(pezzo[1:-1])
            run.font.name = "Consolas"
        elif len(pezzo) > 2 and pezzo[0] in "*_" and pezzo[-1] == pezzo[0]:
            run = par.add_run(pezzo[1:-1])
            run.italic = True
        else:
            run = par.add_run(pezzo)
        if grassetto:
            run.bold = True


def _celle(riga):
    riga = riga.strip()
    if riga.startswith("|"):
        riga = riga[1:]
    if riga.endswith("|"):
        riga = riga[:-1]
    return [c.strip() for c in riga.split("|")]


def _bordi_tabella(tabella):
    tbl_pr = tabella._tbl.tblPr
    bordi = OxmlElement("w:tblBorders")
    for lato in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{lato}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "A6A6A6")
        bordi.append(el)
    tbl_pr.append(bordi)


def _aggiungi_tabella(doc, righe):
    righe = [_celle(r) for r in righe if not RE_SEPARATORE.match(r)]
    if not righe:
        return
    n_col = max(len(r) for r in righe)
    tab = doc.add_table(rows=len(righe), cols=n_col)
    tab.alignment = WD_TABLE_ALIGNMENT.CENTER
    _bordi_tabella(tab)
    for i, r in enumerate(righe):
        for j in range(n_col):
            cella = tab.cell(i, j)
            cella.text = ""
            _testo_formattato(cella.paragraphs[0], r[j] if j < len(r) else "", grassetto=(i == 0))
            if i == 0:
                sfondo = OxmlElement("w:shd")
                sfondo.set(qn("w:val"), "clear")
                sfondo.set(qn("w:fill"), "DEEAF6")
                cella._tc.get_or_add_tcPr().append(sfondo)
    doc.add_paragraph()


def _stili(doc):
    norm = doc.styles["Normal"]
    norm.font.name = "Calibri"
    norm.font.size = Pt(11)
    for nome, dim in (("Title", 22), ("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 12)):
        st = doc.styles[nome]
        st.font.name = "Calibri"
        st.font.size = Pt(dim)
        st.font.color.rgb = BLU


def markdown_in_docx(doc, testo):
    """Scrive nel documento il testo, interpretando il Markdown semplice prodotto dagli attrezzi."""
    righe = testo.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(righe):
        riga = righe[i].rstrip()
        if not riga.strip():
            i += 1
            continue
        if riga.lstrip().startswith("|"):
            blocco = []
            while i < len(righe) and righe[i].lstrip().startswith("|"):
                blocco.append(righe[i])
                i += 1
            _aggiungi_tabella(doc, blocco)
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", riga):
            i += 1
            continue
        m = RE_TITOLO.match(riga)
        if m:
            doc.add_heading(m.group(2).strip("* "), level=min(len(m.group(1)), 3))
            i += 1
            continue
        m = RE_TRASCR.match(riga)
        if m:
            par = doc.add_paragraph()
            ora = par.add_run(f"[{m.group(1)}] ")
            ora.font.color.rgb = GRIGIO
            nome = par.add_run(m.group(2) + ": ")
            nome.bold = True
            nome.font.color.rgb = BLU
            _testo_formattato(par, m.group(3))
            i += 1
            continue
        m = RE_PUNTO.match(riga)
        if m:
            stile = "List Bullet 2" if len(m.group(1).expandtabs(4)) >= 2 else "List Bullet"
            _testo_formattato(doc.add_paragraph(style=stile), m.group(2))
            i += 1
            continue
        m = RE_NUM.match(riga)
        if m:
            _testo_formattato(doc.add_paragraph(style="List Number"), m.group(2))
            i += 1
            continue
        if re.match(r"^\s*(\*\*)?oggetto(\*\*)?\s*:", riga, re.I):
            par = doc.add_paragraph()
            _testo_formattato(par, riga.replace("**", ""), grassetto=True)
            i += 1
            continue
        # paragrafo normale: unisce le righe consecutive "di testo"
        par = doc.add_paragraph()
        _testo_formattato(par, riga.strip())
        i += 1
        while i < len(righe) and righe[i].strip() and not (
                righe[i].lstrip().startswith(("|", "#")) or RE_PUNTO.match(righe[i]) or RE_NUM.match(righe[i])
                or RE_TRASCR.match(righe[i])):
            par.add_run().add_break()
            _testo_formattato(par, righe[i].strip())
            i += 1


def salva_docx(testo, percorso, titolo=None, sottotitolo=None, nota_ai=True):
    """Crea un .docx dal testo. Se il testo inizia già con un titolo '# ...' non ne aggiunge un altro."""
    doc = Document()
    _stili(doc)
    for sez in doc.sections:
        piede = sez.footer.paragraphs[0]
        r = piede.add_run(f"Argo · {'AI' if _qualche_cloud() else 'AI locale'} · {datetime.now():%d/%m/%Y %H:%M}")
        r.font.size = Pt(8)
        r.font.color.rgb = GRIGIO
    if titolo and not testo.lstrip().startswith("# "):
        doc.add_heading(titolo, level=0)
    if sottotitolo:
        p = doc.add_paragraph()
        r = p.add_run(sottotitolo)
        r.italic = True
        r.font.color.rgb = GRIGIO
    markdown_in_docx(doc, testo)
    if nota_ai:
        p = doc.add_paragraph()
        r = p.add_run(nota_ai if isinstance(nota_ai, str) else (NOTA_AI_CLOUD if _qualche_cloud() else NOTA_AI))
        r.italic = True
        r.font.size = Pt(8)
        r.font.color.rgb = GRIGIO
    percorso = Path(percorso)
    if percorso.suffix.lower() != ".docx":
        percorso = percorso.with_suffix(".docx")
    doc.save(str(percorso))
    return percorso
