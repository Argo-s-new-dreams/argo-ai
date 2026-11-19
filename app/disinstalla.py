"""disinstalla.py - disinstallare Argo senza scaricare niente.

    registra_windows()  Windows: Argo compare in Impostazioni > App > App installate (con «Disinstalla»)
                        e nel menu Start c'è «Disinstalla Argo». Solo per l'utente (HKCU): niente
                        diritti di amministratore. La chiama l'installer e, a ogni avvio, Argo stesso
                        (così vale anche per chi si aggiorna dall'app). Non fa nulla se è già a posto.
    avvia()             pulsante «Disinstalla Argo…» delle Impostazioni: copia il disinstallatore in una
                        cartella temporanea e lo apre in una finestra di Terminale/PowerShell, così può
                        cancellare anche la cartella di Argo.

Gli script veri sono in app/disinstallatore/ (arrivano anche con gli aggiornamenti dall'app).
Uso da riga di comando (lo usa l'installer Windows): python disinstalla.py registra
Solo libreria standard.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QUI = Path(__file__).resolve().parent
SCRIPT_WINDOWS = QUI / "disinstallatore" / "disinstalla_windows.ps1"
SCRIPT_MAC = QUI / "disinstallatore" / "disinstalla_mac.sh"
CHIAVE = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgoAI"
SENZA_FINESTRA = 0x08000000
NUOVA_CONSOLE = 0x00000010


def versione():
    try:
        m = re.search(r'^VERSIONE = "([^"]+)"', (QUI / "trascrittore.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def comando_windows():
    return f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{SCRIPT_WINDOWS}"'


def _collegamento_start():
    programmi = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programmi / "Disinstalla Argo.lnk"


def registra_windows():
    """Voce tra le app installate e «Disinstalla Argo» nel menu Start. Ritorna True se ha cambiato qualcosa."""
    if os.name != "nt" or not SCRIPT_WINDOWS.exists():
        return False
    import winreg
    v = versione()
    lnk = _collegamento_start()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHIAVE) as k:
            a_posto = (winreg.QueryValueEx(k, "DisplayVersion")[0] == v
                       and winreg.QueryValueEx(k, "UninstallString")[0] == comando_windows())
    except OSError:
        a_posto = False
    if a_posto and lnk.exists():
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHIAVE) as k:
        for nome, valore in (("DisplayName", "Argo AI"),
                             ("DisplayVersion", v),
                             ("Publisher", "Argos New Dreams"),
                             ("DisplayIcon", str(QUI / "icon.ico")),
                             ("InstallLocation", str(QUI.parent)),
                             ("UninstallString", comando_windows()),
                             ("URLInfoAbout", "https://github.com/Argo-s-new-dreams/argo-ai"),
                             ("HelpLink", "mailto:supporto@argo-net.it")):
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valore)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    if not lnk.exists():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        ps = ("$ws = New-Object -ComObject WScript.Shell; "
              f"$l = $ws.CreateShortcut('{lnk}'); "
              "$l.TargetPath = 'powershell.exe'; "
              f"$l.Arguments = '-NoProfile -ExecutionPolicy Bypass -File \"{SCRIPT_WINDOWS}\"'; "
              f"$l.IconLocation = '{QUI / 'icon.ico'}'; "
              "$l.Description = 'Disinstalla Argo - Cassetta degli attrezzi AI'; $l.Save()")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, creationflags=SENZA_FINESTRA, timeout=30)
    return True


def avvia():
    """Apre il disinstallatore (copiato in una cartella temporanea). Ritorna True se è partito."""
    if os.name == "nt":
        if not SCRIPT_WINDOWS.exists():
            return False
        copia = Path(tempfile.gettempdir()) / "argo-disinstalla.ps1"
        shutil.copy2(SCRIPT_WINDOWS, copia)
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(copia),
                          "-DaTemp"], creationflags=NUOVA_CONSOLE, close_fds=True)
        return True
    if sys.platform == "darwin":
        if not SCRIPT_MAC.exists():
            return False
        copia = Path(tempfile.mkdtemp(prefix="argo-disinstalla-")) / "Disinstalla Argo.command"
        shutil.copy2(SCRIPT_MAC, copia)
        copia.chmod(0o755)
        subprocess.Popen(["/usr/bin/open", "-a", "Terminal", str(copia)])
        return True
    return False


if __name__ == "__main__":
    if sys.argv[1:] == ["registra"]:
        print("Registrazione tra le app installate:", "aggiornata" if registra_windows() else "già a posto")
