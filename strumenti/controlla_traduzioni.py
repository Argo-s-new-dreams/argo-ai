#!/usr/bin/env python3
"""controlla_traduzioni.py - quanti testi dell'interfaccia sono tradotti in inglese, spagnolo e tedesco.

Uso:
    python3 strumenti/controlla_traduzioni.py            # riepilogo per lingua
    python3 strumenti/controlla_traduzioni.py --mancanti en   # elenco dei testi da tradurre (JSON)
    python3 strumenti/controlla_traduzioni.py --severo   # esce con errore se manca qualcosa

Legge ogni tr("…") in app/*.py e lo confronta con app/traduzioni/<lingua>.json. Esce sempre con errore se
una traduzione ha segnaposto diversi dall'originale ({nome}, {n}…): il testo tradotto non si potrebbe comporre.
"""
import ast
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
LINGUE = ("en", "es", "de")
SEGNAPOSTO = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)(?:[!:][^}]*)?\}(?!\})")


def chiavi_del_codice() -> dict[str, str]:
    chiavi = {}
    for file in sorted(APP.glob("*.py")):
        for nodo in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "tr"
                    and nodo.args and isinstance(nodo.args[0], ast.Constant) and isinstance(nodo.args[0].value, str)):
                chiavi.setdefault(nodo.args[0].value, f"{file.name}:{nodo.lineno}")
    return chiavi


def catalogo(lingua: str) -> dict[str, str]:
    percorso = APP / "traduzioni" / f"{lingua}.json"
    return json.loads(percorso.read_text(encoding="utf-8")) if percorso.exists() else {}


def main():
    chiavi = chiavi_del_codice()
    if "--mancanti" in sys.argv:
        lingua = sys.argv[sys.argv.index("--mancanti") + 1]
        cat = catalogo(lingua)
        print(json.dumps([k for k in chiavi if not cat.get(k)], ensure_ascii=False, indent=1))
        return 0
    errori, mancano = 0, 0
    for lingua in LINGUE:
        cat = catalogo(lingua)
        tradotte = [k for k in chiavi if cat.get(k)]
        for k in tradotte:
            if sorted(SEGNAPOSTO.findall(k)) != sorted(SEGNAPOSTO.findall(cat[k])):
                errori += 1
                print(f"[{lingua}] segnaposto diversi in {chiavi[k]}: {k!r} → {cat[k]!r}")
        vecchie = [k for k in cat if k not in chiavi]
        mancano += len(chiavi) - len(tradotte)
        print(f"{lingua}: {len(tradotte)}/{len(chiavi)} tradotti"
              + (f", {len(vecchie)} traduzioni di testi non più usati" if vecchie else ""))
    if errori:
        return 1
    return 1 if ("--severo" in sys.argv and mancano) else 0


if __name__ == "__main__":
    sys.exit(main())
