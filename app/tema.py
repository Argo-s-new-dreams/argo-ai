"""tema.py - aspetto di Argo: tema scuro / chiaro, icone e menu laterale (stile «Studio»)."""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QButtonGroup, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

# Palette dal Brand Book di Argo's New Dreams («Dove il fantastico è il quotidiano»): carta calda, antracite delle
# sfere, terracotta e ocra delle orbite. «scuro» = Notte, «chiaro» = Carta (le chiavi restano per le impostazioni).
ACCENTO = "#E58074"
TEMI = {
    "scuro": {
        "bg": "#1C2124", "pannello": "#22282B", "pannello2": "#2A3134", "nav": "#171B1D", "bordo": "#30383C",
        "bordo2": "#3D464A", "testo": "#F1E8DC", "testo2": "#E2D6C6", "tenue": "#A89B8D", "debole": "#7C7268",
        "accento": "#E58074", "su_accento": "#1C2124", "accento_bg": "#3A2C28", "ok": "#9CC9A6", "warn": "#EEC29B",
        "err": "#F19A8E", "sel": "#3A2C28", "ocra": "#EEC29B", "orbita": "#3A4246",
        "parlanti": ["#E58074", "#EEC29B", "#8FB3C4", "#A9C3A0", "#C7A2C0", "#D9B88F", "#F0A8A0", "#9FC6BE"],
    },
    "chiaro": {
        "bg": "#F6F0E6", "pannello": "#FFFDF8", "pannello2": "#F1E6D8", "nav": "#EFE5D6", "bordo": "#E2D5C4",
        "bordo2": "#D3C2AE", "testo": "#1F2427", "testo2": "#2C3337", "tenue": "#6B6158", "debole": "#8A8178",
        "accento": "#B0503B", "su_accento": "#FFFFFF", "accento_bg": "#F3DCD3", "ok": "#3F7D5A", "warn": "#A0661C",
        "err": "#B3392B", "sel": "#F3DCD3", "ocra": "#D9A06E", "orbita": "#D9CBB8",
        "parlanti": ["#B0503B", "#A0661C", "#3F6F86", "#4E7A4A", "#8A4E80", "#8C6A3E", "#C0624F", "#2F7A70"],
    },
}
CARTA_MAIL = {"bg": "#FFFDF8", "testo": "#1F2427", "bordo": "#E2D5C4", "link": "#B0503B"}
_attuale = {"nome": "scuro"}


def risolvi(nome):
    if nome in TEMI:
        return nome
    try:  # "sistema"
        sch = QGuiApplication.styleHints().colorScheme()
        return "chiaro" if sch == Qt.ColorScheme.Light else "scuro"
    except Exception:
        return "scuro"


def colori():
    return TEMI[_attuale["nome"]]


def qss(c):
    return f"""
* {{ font-family: "Roboto", "Segoe UI", system-ui, sans-serif; font-size: 13px; }}
QMainWindow, QDialog, QWidget#pagina {{ background: {c['bg']}; }}
QWidget {{ color: {c['testo']}; }}
QLabel {{ background: transparent; }}
QLabel[ruolo="titolo"] {{ font-size: 24px; font-weight: 300; letter-spacing: 0.5px; }}
QLabel[ruolo="tenue"] {{ color: {c['tenue']}; }}
QLabel[ruolo="sezione"] {{ color: {c['tenue']}; font-size: 11px; font-weight: 500; letter-spacing: 1.5px; }}
QLabel#marchio {{ color: {c['tenue']}; font-size: 10px; font-weight: 300; letter-spacing: 3px; }}
QTextBrowser#mail {{ background: {CARTA_MAIL['bg']}; color: {CARTA_MAIL['testo']}; border: 1px solid {c['bordo']};
    border-radius: 10px; padding: 10px; selection-background-color: {CARTA_MAIL['link']}; selection-color: #FFFFFF; }}
QWidget#nav {{ background: {c['nav']}; border-right: 1px solid {c['bordo']}; }}
QToolButton[nav="true"] {{ background: transparent; color: {c['tenue']}; border: none; border-radius: 12px;
    padding: 6px 2px; font-size: 10px; }}
QToolButton[nav="true"]:hover {{ background: {c['pannello2']}; color: {c['testo']}; }}
QToolButton[nav="true"]:checked {{ background: {c['accento_bg']}; color: {c['accento']}; }}
QTabWidget::pane {{ border: none; background: {c['bg']}; }}
QGroupBox {{ background: {c['pannello']}; border: 1px solid {c['bordo']}; border-radius: 12px; margin-top: 22px;
    padding: 14px 12px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; top: 2px; color: {c['testo']}; }}
QPushButton, QToolButton {{ background: {c['pannello2']}; color: {c['testo']}; border: 1px solid {c['bordo2']};
    border-radius: 8px; padding: 7px 14px; min-height: 20px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {c['accento']}; }}
QPushButton:pressed {{ background: {c['accento_bg']}; }}
QPushButton:disabled {{ color: {c['debole']}; border-color: {c['bordo']}; }}
QPushButton[primario="true"] {{ background: {c['accento']}; color: {c['su_accento']}; border: none; font-weight: 500;
    border-radius: 16px; padding: 7px 18px; }}
QPushButton[primario="true"]:hover {{ background: {c['accento']}; border: 1px solid {c['testo']}; }}
QPushButton[pillola="true"] {{ border-radius: 14px; padding: 5px 14px; color: {c['tenue']}; }}
QPushButton[pillola="true"]:checked {{ background: {c['accento_bg']}; color: {c['accento']}; border-color: {c['accento']}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c['pannello2']}; color: {c['testo']}; border: 1px solid {c['bordo2']}; border-radius: 8px;
    padding: 6px 8px; selection-background-color: {c['accento']}; selection-color: {c['su_accento']}; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {c['pannello']}; border-color: {c['bordo']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accento']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; border: none; background: transparent; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid {c['tenue']}; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {c['tenue']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {c['tenue']}; }}
QComboBox QAbstractItemView {{ background: {c['pannello2']}; color: {c['testo']}; selection-background-color: {c['accento_bg']};
    selection-color: {c['accento']}; border: 1px solid {c['bordo2']}; }}
QTableWidget, QTableView, QListWidget {{ background: {c['pannello']}; alternate-background-color: {c['pannello2']};
    border: 1px solid {c['bordo']}; border-radius: 10px; gridline-color: {c['bordo']};
    selection-background-color: {c['sel']}; selection-color: {c['testo']}; }}
QHeaderView::section {{ background: {c['pannello2']}; color: {c['tenue']}; border: none; border-bottom: 1px solid {c['bordo']};
    padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['pannello2']}; border: none; }}
QProgressBar {{ background: {c['bordo']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accento']}; border-radius: 4px; }}
QSplitter::handle {{ background: {c['bordo']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollArea {{ border: none; background: {c['bg']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['bordo2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['bordo2']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {c['nav']}; color: {c['tenue']}; border-top: 1px solid {c['bordo']}; }}
QStatusBar QLabel {{ color: {c['tenue']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1.5px solid {c['bordo2']}; border-radius: 4px; background: {c['pannello2']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accento']}; }}
QCheckBox::indicator:checked {{ background: {c['accento']}; border-color: {c['accento']}; }}
QCheckBox::indicator:disabled {{ border-color: {c['bordo']}; background: transparent; }}
QToolTip {{ background: {c['pannello2']}; color: {c['testo']}; border: 1px solid {c['bordo2']}; padding: 6px; }}
QMenu {{ background: {c['pannello2']}; color: {c['testo']}; border: 1px solid {c['bordo2']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['accento_bg']}; color: {c['accento']}; }}
QFrame[ruolo="scheda"] {{ background: {c['pannello']}; border: 1px solid {c['bordo']}; border-radius: 12px; }}
"""


def carica_font():
    """Roboto, il carattere del Brand Book (Apache 2.0), incluso nell'app: stesso aspetto su Mac e Windows."""
    if _attuale.get("font"):
        return
    for f in sorted((Path(__file__).resolve().parent / "fonti").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))
    _attuale["font"] = True


def applica(app, nome="scuro"):
    carica_font()
    n = risolvi(nome)
    _attuale["nome"] = n
    c = TEMI[n]
    app.setStyle("Fusion")
    pal = QPalette()
    for ruolo, chiave in ((QPalette.Window, "bg"), (QPalette.Base, "pannello"), (QPalette.AlternateBase, "pannello2"),
                          (QPalette.Button, "pannello2"), (QPalette.Text, "testo"), (QPalette.WindowText, "testo"),
                          (QPalette.ButtonText, "testo"), (QPalette.ToolTipBase, "pannello2"),
                          (QPalette.ToolTipText, "testo"), (QPalette.PlaceholderText, "debole"),
                          (QPalette.Highlight, "accento"), (QPalette.HighlightedText, "su_accento"),
                          (QPalette.Link, "accento")):
        pal.setColor(ruolo, QColor(c[chiave]))
    app.setPalette(pal)
    app.setStyleSheet(qss(c))
    return n


# ---------------------------------------------------------------- icone (SVG a tratto, colorate al volo)
ICONE = {
    "incarichi": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "agenda": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4M8 14h3M8 17h6"/>',
    "posta": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 6.5l8.5 6.5 8.5-6.5"/>',
    "registra": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.5"/><circle cx="12" cy="12" r="1.5"/>',
    "trascrittore": '<path d="M3 12h2M7 8v8M11 4v16M15 8v8M19 11v2"/>',
    "verbale": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    "documenti": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "dettatura": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "traduzione": '<path d="M4 5h8M8 3v2M6 5c0 4 3 7 6 8M10 5c0 3-2 6-6 8"/><path d="M13 21l4-9 4 9M14.5 18h5"/>',
    "voci": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    "impostazioni": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
}


def icona(nome, colore, lato=22):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{colore}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONE[nome]}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(lato * 2, lato * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, lato * 2, lato * 2))
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


def icona_stato(nome):
    """Icona con colore normale e colore 'selezionato' (accento)."""
    c = colori()
    ic = QIcon()
    ic.addPixmap(icona(nome, c["tenue"]), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icona(nome, c["accento"]), QIcon.Normal, QIcon.On)
    ic.addPixmap(icona(nome, c["accento"]), QIcon.Active, QIcon.On)
    return ic


def marchio(lato):
    """Il marchio di Argo's New Dreams nel menu: il disco con le sfere del logo «Dove il fantastico è il quotidiano»
    (app/marchio.png, ritagliato dal logo originale del Brand Book)."""
    pm = QPixmap(str(Path(__file__).resolve().parent / "marchio.png"))
    if pm.isNull():
        return QPixmap()
    pm = pm.scaled(lato * 2, lato * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(2)
    return pm


class NavLaterale(QWidget):
    """Menu laterale a icone che comanda un QTabWidget (la barra delle schede resta nascosta)."""
    scelto = Signal(int)

    def __init__(self, voci, parent=None):
        super().__init__(parent)
        self.setObjectName("nav")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(84)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(4)
        self.logo = QLabel()
        self.logo.setFixedSize(46, 46)
        self.logo.setPixmap(marchio(46))
        self.logo.setToolTip("Argo · Cassetta degli attrezzi AI\nArgo's New Dreams: dove il fantastico è il quotidiano")
        lay.addWidget(self.logo, alignment=Qt.AlignHCenter)
        scritta = QLabel("ARGO")
        scritta.setObjectName("marchio")
        lay.addWidget(scritta, alignment=Qt.AlignHCenter)
        lay.addSpacing(10)
        self.gruppo = QButtonGroup(self)
        self.gruppo.setExclusive(True)
        self.bottoni = []
        for i, (chiave, etichetta, breve) in enumerate(voci):
            if chiave == "impostazioni":
                lay.addStretch(1)
            b = QToolButton()
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(icona_stato(chiave))
            b.setIconSize(QSize(22, 22))
            b.setText(breve)
            b.setToolTip(etichetta)
            b.setAccessibleName(etichetta)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(56)
            b.setCursor(Qt.PointingHandCursor)
            self.gruppo.addButton(b, i)
            self.bottoni.append((chiave, b))
            lay.addWidget(b)
        self.gruppo.idClicked.connect(self.scelto.emit)

    def seleziona(self, i):
        b = self.gruppo.button(i)
        if b and not b.isChecked():
            b.setChecked(True)

    def ricolora(self):
        self.logo.setPixmap(marchio(46))
        for chiave, b in self.bottoni:
            b.setIcon(icona_stato(chiave))
