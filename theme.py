"""Colour palettes and the Qt stylesheet for dark / light themes."""
from __future__ import annotations

ACCENTS = {
    # name: (main, hover/lighter, darker)
    "violet": ("#8b5cf6", "#a78bfa", "#6d28d9"),
    "blue":   ("#3b82f6", "#60a5fa", "#1d4ed8"),
    "cyan":   ("#06b6d4", "#22d3ee", "#0e7490"),
    "teal":   ("#14b8a6", "#2dd4bf", "#0f766e"),
    "green":  ("#10b981", "#34d399", "#047857"),
    "amber":  ("#f59e0b", "#fbbf24", "#b45309"),
    "orange": ("#f97316", "#fb923c", "#c2410c"),
    "pink":   ("#ec4899", "#f472b6", "#be185d"),
    "red":    ("#ef4444", "#f87171", "#b91c1c"),
}

PALETTES = {
    "dark": {
        "bg": "#0f1320", "surface": "#171c2c", "surface2": "#1e2438", "input": "#0c101b",
        "border": "#2b3350", "border2": "#3a4466", "text": "#e8ecf8", "muted": "#94a0c0",
        "faint": "#66718f", "sel": "#3b4a8a", "ghost": "#262d45", "ghost_hover": "#313a58",
        "tint_alpha": 56,
    },
    "light": {
        "bg": "#eef1f8", "surface": "#ffffff", "surface2": "#f5f7fc", "input": "#ffffff",
        "border": "#d7dcea", "border2": "#c0c8dc", "text": "#1a2033", "muted": "#5b6580",
        "faint": "#8a93aa", "sel": "#c7d2fe", "ghost": "#e8ecf6", "ghost_hover": "#dbe1f0",
        "tint_alpha": 34,
    },
}

STATUS_COLORS = {
    "dark": {"ok": "#34d399", "error": "#f87171", "warn": "#fbbf24", "info": "#93c5fd",
             "running": "#22d3ee", "skipped": "#fbbf24", "stopped": "#94a0c0", "pending": "#94a0c0"},
    "light": {"ok": "#059669", "error": "#dc2626", "warn": "#b45309", "info": "#1d4ed8",
              "running": "#0e7490", "skipped": "#b45309", "stopped": "#5b6580", "pending": "#5b6580"},
}

PROVIDER_ACCENT = {"Inworld": "teal", "MiniMax": "pink"}

# Log colours are mid-tones so old lines stay readable after a theme switch.
LOG_COLORS = {"ok": "#10b981", "error": "#ef4444", "warn": "#f59e0b", "info": "#3b82f6", "time": "#8a93aa"}


def make_arrow_icons(folder, mode: str) -> dict:
    """Render small chevron PNGs (Qt QSS cannot draw CSS-style triangles)."""
    from pathlib import Path

    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    color = QColor(PALETTES[mode]["muted"])
    out = {}
    for name, pts in (("down", [(2, 3), (11, 11), (20, 3)]), ("up", [(2, 11), (11, 3), (20, 11)])):
        img = QImage(22, 14, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        pa = QPainter(img)
        pa.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pa.setPen(pen)
        pa.drawPolyline([QPointF(x, y) for x, y in pts])
        pa.end()
        path = folder / f"arrow_{name}_{mode}.png"
        img.save(str(path))
        out[name] = str(path).replace("\\", "/")
    return out


def rgba(hex_color: str, alpha: int) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def build_stylesheet(mode: str, arrows: dict | None = None) -> str:
    p = PALETTES[mode]
    arrows = arrows or {}
    down = arrows.get("down", "")
    up = arrows.get("up", "")
    a = p["tint_alpha"]
    css = f"""
* {{ font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {p['bg']}; }}
QWidget {{ color: {p['text']}; }}
QWidget#Page, QWidget#Central, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['bg']}; }}
QToolTip {{ background: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border2']}; padding: 6px; border-radius: 6px; }}

/* ---------- header ---------- */
QFrame#Header {{
    border-radius: 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7c3aed, stop:0.45 #2563eb, stop:1 #0891b2);
}}
QFrame#Header QLabel {{ background: transparent; color: #ffffff; }}
QLabel#AppTitle {{ font-size: 19pt; font-weight: 800; }}
QLabel#AppSub {{ color: rgba(255,255,255,85%); font-size: 9.5pt; }}
QLabel#Logo {{ font-size: 26pt; }}
QLabel.Chip, QLabel[chip="true"] {{
    background: rgba(255,255,255,18%); border: 1px solid rgba(255,255,255,35%);
    border-radius: 11px; padding: 3px 10px; font-weight: 600; font-size: 9pt;
}}
QPushButton#ThemeBtn {{
    background: rgba(255,255,255,20%); border: 1px solid rgba(255,255,255,45%);
    color: #ffffff; border-radius: 16px; padding: 6px 14px; font-weight: 700;
}}
QPushButton#ThemeBtn:hover {{ background: rgba(255,255,255,32%); }}
QPushButton#UpdateChip {{
    color: #ffffff; border: 1px solid rgba(255,255,255,55%); border-radius: 16px; padding: 6px 14px; font-weight: 800;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f97316, stop:1 #ec4899);
}}
QPushButton#UpdateChip:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fb923c, stop:1 #f472b6); }}

/* ---------- sidebar ---------- */
QFrame#Sidebar {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QLabel#SideCaption {{ color: {p['faint']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; background: transparent; }}
QLabel#Version {{ color: {p['faint']}; font-size: 8.5pt; background: transparent; }}
QPushButton[nav="true"] {{
    text-align: left; padding: 11px 14px; border-radius: 10px; border: 1px solid transparent;
    background: transparent; color: {p['muted']}; font-size: 10.5pt; font-weight: 600;
}}
QPushButton[nav="true"]:hover {{ background: {p['ghost']}; color: {p['text']}; }}

/* ---------- cards ---------- */
QFrame[card="true"] {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox, QFrame[card="true"] QRadioButton {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 17pt; font-weight: 800; background: transparent; }}
QLabel#PageDesc {{ color: {p['muted']}; background: transparent; }}
QLabel[role="cardTitle"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[role="muted"] {{ color: {p['muted']}; }}
QLabel[role="field"] {{ color: {p['muted']}; font-weight: 600; }}
QLabel[role="hint"] {{ color: {p['muted']}; font-size: 9pt; }}

/* ---------- inputs ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: {p['input']}; border: 1px solid {p['border2']}; border-radius: 8px;
    padding: 7px 9px; selection-background-color: {p['sel']}; selection-color: {p['text']};
}}
QTextEdit, QPlainTextEdit {{ padding: 8px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 2px solid {ACCENTS['blue'][0]}; padding: 6px 8px;
}}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {{ color: {p['faint']}; }}
QLineEdit[readOnly="true"] {{ background: {p['surface2']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 11px; height: 7px; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border2']};
    selection-background-color: {p['sel']}; selection-color: {p['text']}; outline: 0; padding: 4px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; margin-top: 3px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; margin-bottom: 3px; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {p['ghost']}; border-radius: 4px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 9px; height: 6px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 9px; height: 6px; }}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {p['border2']}; background: {p['input']}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENTS['green'][0]}; }}
QCheckBox::indicator:checked {{ background: {ACCENTS['green'][0]}; border-color: {ACCENTS['green'][0]}; }}
QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {p['border']}; }}
QSlider::sub-page:horizontal {{ border-radius: 3px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENTS['blue'][0]}, stop:1 {ACCENTS['cyan'][0]}); }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #ffffff; border: 3px solid {ACCENTS['blue'][0]}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p['ghost']}; border: 1px solid {p['border2']}; border-radius: 9px;
    padding: 8px 14px; font-weight: 600; color: {p['text']};
}}
QPushButton:hover {{ background: {p['ghost_hover']}; }}
QPushButton:disabled {{ color: {p['faint']}; background: {p['surface2']}; border-color: {p['border']}; }}
QPushButton[size="big"] {{ padding: 12px 22px; font-size: 11pt; font-weight: 700; border-radius: 11px; }}
QPushButton[size="small"] {{ padding: 5px 10px; font-size: 9pt; border-radius: 7px; }}

/* ---------- table ---------- */
QTableWidget, QTableView, QListWidget {{
    background: {p['input']}; alternate-background-color: {p['surface2']}; border: 1px solid {p['border']};
    border-radius: 10px; gridline-color: {p['border']}; selection-background-color: {p['sel']};
    selection-color: {p['text']}; outline: 0;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background: {p['surface2']}; color: {p['muted']}; border: none; border-bottom: 2px solid {p['border2']};
    padding: 8px 6px; font-weight: 700;
}}
QTableCornerButton::section {{ background: {p['surface2']}; border: none; }}

/* ---------- progress ---------- */
QProgressBar {{
    background: {p['input']}; border: 1px solid {p['border']}; border-radius: 9px;
    text-align: center; min-height: 18px; font-weight: 700; color: {p['text']};
}}
QProgressBar::chunk {{ border-radius: 8px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENTS['violet'][0]}, stop:0.5 {ACCENTS['blue'][0]}, stop:1 {ACCENTS['cyan'][0]}); }}
QProgressBar[accent="green"]::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENTS['teal'][0]}, stop:1 {ACCENTS['green'][1]}); }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border2']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}

/* ---------- log ---------- */
QFrame#LogCard {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QTextEdit#Log {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 10px;
    font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; font-size: 9pt; }}
QStatusBar {{ background: {p['surface']}; color: {p['muted']}; border-top: 1px solid {p['border']}; }}
QStatusBar QLabel {{ background: transparent; color: {p['muted']}; padding: 0 8px; }}
QMessageBox {{ background: {p['surface']}; }}
QMessageBox QLabel {{ background: transparent; }}
QTextBrowser#Guide {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; padding: 18px; }}
"""
    for name, (main, light, dark) in ACCENTS.items():
        css += f"""
QPushButton[variant="{name}"] {{
    color: #ffffff; border: 1px solid {dark};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {light}, stop:1 {main});
}}
QPushButton[variant="{name}"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {light}, stop:1 {light}); }}
QPushButton[variant="{name}"]:pressed {{ background: {dark}; }}
QPushButton[variant="{name}"]:disabled {{ color: rgba(255,255,255,55%); background: {main}; border-color: {main}; }}
QPushButton[tint="{name}"] {{ color: {main if mode == 'dark' else dark}; background: {rgba(main, a)}; border: 1px solid {rgba(main, 136)}; }}
QPushButton[tint="{name}"]:hover {{ background: {rgba(main, 85)}; }}
QPushButton[tint="{name}"]:disabled {{ color: {p['faint']}; background: {p['surface2']}; border-color: {p['border']}; }}
QPushButton[nav="true"][accent="{name}"]:checked {{
    background: {rgba(main, a)}; color: {light if mode == 'dark' else dark}; border: 1px solid {rgba(main, 102)};
    border-left: 4px solid {main};
}}
QPushButton[choice="{name}"] {{ background: {p['surface2']}; border: 2px solid {p['border']}; color: {p['muted']}; padding: 10px; border-radius: 11px; }}
QPushButton[choice="{name}"]:hover {{ border-color: {main}; color: {p['text']}; }}
QPushButton[choice="{name}"]:checked {{ background: {rgba(main, a)}; border: 2px solid {main}; color: {light if mode == 'dark' else dark}; }}
QFrame[accentbar="{name}"] {{ background: {main}; border: none; border-radius: 2px; }}
QLabel[badge="{name}"] {{ color: #ffffff; background: {main}; border-radius: 9px; padding: 2px 9px; font-weight: 700; font-size: 8.5pt; }}
QFrame[tile="{name}"] {{ border-radius: 12px; border: 1px solid {rgba(main, 102)};
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {rgba(main, a)}, stop:1 {rgba(main, 16)}); }}
QFrame[tile="{name}"] QLabel {{ background: transparent; }}
QFrame[tile="{name}"] QLabel[role="tileValue"] {{ color: {light if mode == 'dark' else dark}; font-size: 20pt; font-weight: 800; }}
QFrame[tile="{name}"] QLabel[role="tileLabel"] {{ color: {p['muted']}; font-weight: 600; }}
QLabel[role="cardTitle"][accent="{name}"] {{ color: {light if mode == 'dark' else dark}; }}
"""
    return css
