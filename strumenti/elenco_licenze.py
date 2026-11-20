"""elenco_licenze.py - elenco delle librerie Python installate con versione e licenza dichiarata.

Lanciato con il Python dell'ambiente di Argo, scrive una tabella Markdown (stdout o file):

    python strumenti/elenco_licenze.py docs/LICENZE-LIBRERIE.md

La licenza è quella dichiarata nei metadati del pacchetto (License-Expression, License o classificatori):
è un inventario, non un parere legale. La GitHub Action «Prova di avvio» lo produce su macOS e Windows.
"""
import platform
import sys
from importlib import metadata


def licenza(dist):
    m = dist.metadata
    espr = (m.get("License-Expression") or "").strip()
    if espr:
        return espr
    classificatori = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    testo = (m.get("License") or "").strip()
    if testo and len(testo) <= 60 and "\n" not in testo:
        return testo
    if classificatori:
        return ", ".join(dict.fromkeys(classificatori))
    if testo:
        return testo.splitlines()[0][:60] + "…"
    return "non dichiarata"


def sito(dist):
    m = dist.metadata
    for voce in m.get_all("Project-URL") or []:
        nome, _, url = voce.partition(",")
        if nome.strip().lower() in ("homepage", "source", "repository", "source code", "home"):
            return url.strip()
    return (m.get("Home-page") or "").strip()


def main():
    righe = {}
    for d in metadata.distributions():
        nome = (d.metadata.get("Name") or "").strip()
        if nome:
            righe[nome.lower()] = (nome, d.version, licenza(d), sito(d))
    testo = [f"# Librerie Python di Argo e loro licenze",
             "",
             f"*Generato da `strumenti/elenco_licenze.py` su {platform.system()} {platform.machine()}, "
             f"Python {platform.python_version()}, dall'ambiente installato con `app/requisiti.lock`. "
             "Licenza come dichiarata nei metadati del pacchetto: inventario, non parere legale.*",
             "",
             "| Libreria | Versione | Licenza dichiarata | Sito |",
             "| --- | --- | --- | --- |"]
    for _, (nome, ver, lic, url) in sorted(righe.items()):
        lic = lic.replace("|", "/")
        testo.append(f"| {nome} | {ver} | {lic} | {url} |")
    testo.append("")
    uscita = "\n".join(testo)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            f.write(uscita)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(uscita)


if __name__ == "__main__":
    main()
