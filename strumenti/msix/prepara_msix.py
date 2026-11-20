"""prepara_msix.py - completa la cartella del pacchetto MSIX: manifesto, icone e collegamento alla cartella app.

    python strumenti/msix/prepara_msix.py <cartella_pacchetto>

Legge l'identità del prodotto dalle variabili d'ambiente (in GitHub: variabili del repository),
con i valori di Partner Center › Gestione prodotti › Identità del prodotto:
    MSIX_NOME           Package/Identity/Name           (es. 12345ArgosNewDreams.ArgoAI)
    MSIX_EDITORE        Package/Identity/Publisher      (es. CN=1A2B3C4D-....)
    MSIX_NOME_EDITORE   Package/Properties/PublisherDisplayName (es. Luca Borio)
Senza variabili usa valori di prova, buoni solo per installare il pacchetto sul proprio PC.
"""
import os
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parent))
import identita  # noqa: E402

PROVA = {"MSIX_NOME": "ArgosNewDreams.ArgoAI.Prova",
         "MSIX_EDITORE": "CN=Argos New Dreams Prova",
         "MSIX_NOME_EDITORE": "Luca Borio"}

ICONE = {  # file: (larghezza, altezza)
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square44x44Logo.targetsize-44_altform-unplated.png": (44, 44),
    "Square44x44Logo.targetsize-256_altform-unplated.png": (256, 256),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
}


def versione_msix(v):
    """20261119.1720 → 2026.1119.1720.0 (lo Store vuole l'ultimo numero a 0, ognuno ≤ 65535)."""
    data, ora = v.split(".")
    return f"{int(data[:4])}.{int(data[4:])}.{int(ora)}.0"


def manifesto(cartella):
    valori = {k: os.environ.get(k) or PROVA[k] for k in PROVA}
    testo = (QUI / "AppxManifest.modello.xml").read_text(encoding="utf-8")
    for chiave, nome in (("NOME", "MSIX_NOME"), ("EDITORE", "MSIX_EDITORE"), ("NOME_EDITORE", "MSIX_NOME_EDITORE")):
        testo = testo.replace("{{" + chiave + "}}", valori[nome])
    testo = testo.replace("{{VERSIONE}}", versione_msix(identita.versione()))
    assert "{{" not in testo, "segnaposto non sostituito nel manifesto"
    (cartella / "AppxManifest.xml").write_text(testo, encoding="utf-8")
    di_prova = any(not os.environ.get(k) for k in PROVA)
    return valori, di_prova


def icone(cartella):
    from PIL import Image
    sorgente = Image.open(identita.APP / "icon.png").convert("RGBA")
    assets = cartella / "Assets"
    assets.mkdir(exist_ok=True)
    for nome, (w, h) in ICONE.items():
        lato = min(w, h)
        logo = sorgente.resize((lato, lato), Image.LANCZOS)
        tela = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        tela.paste(logo, ((w - lato) // 2, (h - lato) // 2), logo)
        tela.save(assets / nome)


def collega_app(cartella):
    """Un file .pth in site-packages: Python del pacchetto trova app\\ qualunque sia la cartella di lavoro."""
    site = cartella / "python" / "Lib" / "site-packages"
    if not site.is_dir():
        raise SystemExit(f"ERRORE: {site} non esiste: prima va installato Python con le librerie")
    (site / "argo_app.pth").write_text("../../../app\n", encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    cartella = Path(sys.argv[1]).resolve()
    valori, di_prova = manifesto(cartella)
    icone(cartella)
    collega_app(cartella)
    print(f"Manifesto: {valori['MSIX_NOME']} {versione_msix(identita.versione())}"
          + ("  (identità DI PROVA: non adatta allo Store)" if di_prova else ""))


if __name__ == "__main__":
    main()
