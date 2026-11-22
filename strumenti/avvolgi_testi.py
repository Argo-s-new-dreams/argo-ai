#!/usr/bin/env python3
"""avvolgi_testi.py - passa i testi dell'interfaccia di un file da "testo" a tr("testo").

Uso: python3 strumenti/avvolgi_testi.py app/<file>.py [...]

Avvolge solo i testi passati ai widget e alle finestre di Qt (QLabel, setText, setToolTip, QMessageBox,
addItem, showMessage…) e alla pagina di Argo (_pagina). Le f-string diventano tr("… {nome} …", nome=…).
Aggiunge «from lingua import tr» se manca. Da rileggere a mano dopo: è un aiuto, non un compilatore.
"""
import ast
import re
import sys
from pathlib import Path

# nome della funzione o del metodo -> posizioni degli argomenti con testo (None = tutti i testi)
CHIAMATE = {
    "QLabel": [0], "QPushButton": [0], "QCheckBox": [0], "QGroupBox": [0], "QRadioButton": [0],
    "QToolButton": [], "QAction": [0, 1], "QListWidgetItem": [0], "QMenu": [0], "QTreeWidgetItem": None,
    "setText": [0], "setToolTip": [0], "setWindowTitle": [0], "setPlaceholderText": [0], "setTitle": [0],
    "setStatusTip": [0], "setLabelText": [0], "setInformativeText": [0], "setWhatsThis": [0],
    "addItem": [0], "addTab": [1], "insertTab": [2], "setTabText": [1], "addRow": [0],
    "addAction": [0], "addMenu": [0], "showMessage": [0], "setHeaderLabels": None,
    "setHorizontalHeaderLabels": None, "setButtonText": [1], "addButton": [0],
    "information": [1, 2], "warning": [1, 2], "critical": [1, 2], "question": [1, 2], "about": [1, 2],
    "getText": [1, 2], "getItem": [1, 2], "getInt": [1, 2], "getOpenFileName": [1], "getSaveFileName": [1],
    "getOpenFileNames": [1], "getExistingDirectory": [1], "QProgressDialog": [0, 1],
    "_pagina": [1, 2], "QMessageBox": [1, 2], "setDefaultText": [0], "setSuffix": [0], "setPrefix": [0],
}
PAROLE = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def testo_utile(s: str) -> bool:
    s = s.strip()
    return bool(PAROLE.search(s)) and not s.startswith(("http://", "https://", "#", "{")) and "*." not in s


def nome_campo(espr: ast.AST, usati: set) -> str:
    if isinstance(espr, ast.Name):
        base = espr.id
    elif isinstance(espr, ast.Attribute):
        base = espr.attr
    elif isinstance(espr, ast.Call) and isinstance(espr.func, (ast.Name, ast.Attribute)):
        base = espr.func.id if isinstance(espr.func, ast.Name) else espr.func.attr
    elif isinstance(espr, ast.Subscript) and isinstance(espr.slice, ast.Constant) and isinstance(espr.slice.value, str):
        base = espr.slice.value
    else:
        base = "valore"
    base = re.sub(r"\W", "_", base).strip("_").lower() or "valore"
    if base in ("tr", "self"):
        base = "valore"
    nome, n = base, 2
    while nome in usati:
        nome, n = f"{base}{n}", n + 1
    usati.add(nome)
    return nome


def riscrivi(nodo: ast.AST, sorgente: str):
    """Testo del nuovo codice per il nodo stringa, o None se non va toccato."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        if not testo_utile(nodo.value):
            return None
        return f"tr({nodo.value!r})"
    if isinstance(nodo, ast.JoinedStr):
        parti, campi, usati = [], [], set()
        for v in nodo.values:
            if isinstance(v, ast.Constant):
                parti.append(v.value.replace("{", "{{").replace("}", "}}"))
            elif isinstance(v, ast.FormattedValue):
                codice = ast.get_source_segment(sorgente, v.value)
                if codice is None:
                    return None
                nome = nome_campo(v.value, usati)
                conv = {-1: "", 115: "!s", 114: "!r", 97: "!a"}[v.conversion]
                spec = ""
                if v.format_spec is not None:
                    if not all(isinstance(x, ast.Constant) for x in v.format_spec.values):
                        return None
                    spec = ":" + "".join(x.value for x in v.format_spec.values)
                parti.append("{" + nome + conv + spec + "}")
                campi.append(f"{nome}={codice}")
            else:
                return None
        testo = "".join(parti)
        if not testo_utile(re.sub(r"\{[^}]*\}", "", testo)):
            return None
        return f"tr({testo!r}" + "".join(", " + c for c in campi) + ")"
    return None


def gia_avvolto(genitori, nodo) -> bool:
    g = genitori.get(id(nodo))
    return isinstance(g, ast.Call) and isinstance(g.func, ast.Name) and g.func.id == "tr"


def lavora(percorso: Path) -> int:
    sorgente = percorso.read_text(encoding="utf-8")
    albero = ast.parse(sorgente)
    genitori = {}
    for padre in ast.walk(albero):
        for figlio in ast.iter_child_nodes(padre):
            genitori[id(figlio)] = padre
    cambi = []

    def candidato(arg):
        if gia_avvolto(genitori, arg):
            return
        nuovo = riscrivi(arg, sorgente)
        if nuovo:
            cambi.append((arg, nuovo))

    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        nome = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if nome not in CHIAMATE:
            continue
        posizioni = CHIAMATE[nome]
        for i, arg in enumerate(nodo.args):
            if posizioni is None or i in posizioni:
                if isinstance(arg, (ast.List, ast.Tuple)) and posizioni is None:
                    for el in arg.elts:
                        candidato(el)
                elif isinstance(arg, ast.IfExp):
                    candidato(arg.body)
                    candidato(arg.orelse)
                else:
                    candidato(arg)
        for kw in nodo.keywords:
            if kw.arg in ("text", "title", "toolTip", "placeholderText", "titolo", "sottotitolo", "caption"):
                candidato(kw.value)

    if not cambi:
        return 0
    righe = sorgente.splitlines(keepends=True)
    inizi = [0]
    for r in righe:
        inizi.append(inizi[-1] + len(r))

    def pos(riga, col):
        return inizi[riga - 1] + len(righe[riga - 1].encode("utf-8")[:col].decode("utf-8", "ignore"))

    nuovo = sorgente
    for nodo, testo in sorted(cambi, key=lambda c: (c[0].lineno, c[0].col_offset), reverse=True):
        a, b = pos(nodo.lineno, nodo.col_offset), pos(nodo.end_lineno, nodo.end_col_offset)
        nuovo = nuovo[:a] + testo + nuovo[b:]
    if "from lingua import tr" not in nuovo:
        m = re.search(r"^(import |from )", nuovo, re.M)
        nuovo = nuovo[:m.start()] + "from lingua import tr\n" + nuovo[m.start():]
    ast.parse(nuovo)
    percorso.write_text(nuovo, encoding="utf-8")
    return len(cambi)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, lavora(Path(p)))
