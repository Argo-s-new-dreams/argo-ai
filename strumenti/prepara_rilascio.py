"""prepara_rilascio.py - prepara i file di una release Pro di Argo (usato dalla GitHub Action «Rilascio Pro»).

    python strumenti/prepara_rilascio.py v20261116.1015 dist note.md

Crea in dist/:
    argo-app-<versione>.zip      la cartella app/ (senza cache), con percorsi «app/…»
    argo-manifest.json           versione, nome e SHA-256 del pacchetto, commit, data
    argo-manifest.json.sig       firma Ed25519 del manifesto (se c'è il segreto ARGO_FIRMA_PRIVATA)
e in note.md le note di rilascio prese dal CHANGELOG.

Si ferma con un errore se il tag non corrisponde a VERSIONE in app/trascrittore.py, se manca
app/requisiti.lock, o se l'app contiene la chiave pubblica ma il segreto per firmare non è disponibile
(una release non firmata verrebbe rifiutata da tutte le installazioni Pro).
"""
import base64
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
APP = RADICE / "app"
ESCLUSI = {"__pycache__", ".DS_Store"}
DATA_FISSA = (2026, 1, 1, 0, 0, 0)  # date uguali dentro lo ZIP: stesso codice, stesso SHA-256


def errore(msg):
    print(f"ERRORE: {msg}", file=sys.stderr)
    sys.exit(1)


def versione_app():
    m = re.search(r'^VERSIONE\s*=\s*"(\d{8}\.\d{4})"', (APP / "trascrittore.py").read_text(encoding="utf-8"), re.M)
    if not m:
        errore("VERSIONE non trovata in app/trascrittore.py")
    return m.group(1)


def note_dal_changelog(versione):
    righe, dentro = [], False
    for riga in (RADICE / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if riga.startswith("## "):
            if dentro:
                break
            dentro = riga.startswith(f"## {versione}")
            if dentro:
                righe.append(riga)
            continue
        if dentro:
            righe.append(riga)
    return "\n".join(righe).strip() or f"## {versione}\n(nessuna nota nel CHANGELOG)"


def crea_zip(destinazione):
    file = sorted(p for p in APP.rglob("*") if p.is_file() and not (ESCLUSI & set(p.relative_to(APP).parts)))
    with zipfile.ZipFile(destinazione, "w", zipfile.ZIP_DEFLATED) as z:
        for p in file:
            info = zipfile.ZipInfo(f"app/{p.relative_to(APP).as_posix()}", DATA_FISSA)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    return len(file)


def firma(dati, privata_b64):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    chiave = Ed25519PrivateKey.from_private_bytes(base64.b64decode(privata_b64.strip()))
    return base64.b64encode(chiave.sign(dati)).decode("ascii")


def main():
    if len(sys.argv) != 4:
        errore("uso: prepara_rilascio.py <tag> <cartella_uscita> <file_note>")
    tag, uscita, file_note = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    versione = versione_app()
    if tag.lstrip("v") != versione:
        errore(f"il tag {tag} non corrisponde alla versione dell'app ({versione}): aggiorna VERSIONE o il tag")
    if not (APP / "requisiti.lock").exists():
        errore("manca app/requisiti.lock: le release Pro installano solo librerie a versione fissa")

    privata = os.environ.get("ARGO_FIRMA_PRIVATA", "").strip()
    pubblica_presente = (APP / "chiave_aggiornamenti.pub").exists()
    if pubblica_presente and not privata:
        errore("l'app contiene chiave_aggiornamenti.pub ma il segreto ARGO_FIRMA_PRIVATA non è impostato")

    uscita.mkdir(parents=True, exist_ok=True)
    nome_zip = f"argo-app-{versione}.zip"
    n = crea_zip(uscita / nome_zip)
    dati_zip = (uscita / nome_zip).read_bytes()
    manifesto = {
        "prodotto": "Argo · Cassetta degli attrezzi AI",
        "canale": "pro",
        "versione": versione,
        "pacchetto": nome_zip,
        "sha256": hashlib.sha256(dati_zip).hexdigest(),
        "dimensione": len(dati_zip),
        "file": n,
        "commit": os.environ.get("GITHUB_SHA", ""),
        "creato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    dati_man = json.dumps(manifesto, indent=2, ensure_ascii=False).encode("utf-8")
    (uscita / "argo-manifest.json").write_bytes(dati_man)
    if privata:
        (uscita / "argo-manifest.json.sig").write_text(firma(dati_man, privata) + "\n", encoding="ascii")
        print("Manifesto firmato (Ed25519).")
    else:
        print("ATTENZIONE: release non firmata (manca ARGO_FIRMA_PRIVATA): solo verifica SHA-256.")
    file_note.write_text(note_dal_changelog(versione) + "\n", encoding="utf-8")
    print(f"Pronto: {nome_zip} ({n} file, SHA-256 {manifesto['sha256']})")


if __name__ == "__main__":
    main()
