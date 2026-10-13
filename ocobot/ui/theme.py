"""OCOBot dark theme — Palette D15, full RTL, Tajawal font.

Single visual identity (dark only). Exposes:
- ``PALETTE``: exact lowercase hex tokens (Palette D15).
- ``contrast_ratio(hex1, hex2)``: WCAG relative-luminance contrast ratio.
- ``apply_theme(app)``: applies RTL layout, dark QPalette, global QSS and font.
"""

from ._qt import Qt, QFont, QPalette, QColor

# Palette D15 — exact lowercase hex, no light-mode mixing.
PALETTE = {
    "BG": "#031021",
    "SIDEBAR": "#020d1c",
    "CARD": "#061529",
    "CARD_ALT": "#081d32",
    "BORDER": "#0d2a43",
    "TEXT": "#f0f7fb",
    "TEXT_SOFT": "#dce9f2",
    "MUTED": "#6f8ba2",
    "BLUE": "#0876e8",
    "TEAL": "#073b42",
    "GREEN": "#19c58b",
    "RED": "#ff4b68",
    "AMBER": "#f08f1b",
}


def _hex_to_rgb(value):
    """Convert a '#rrggbb' string to an (r, g, b) tuple of 0-255 ints."""
    h = value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(value):
    """WCAG relative luminance of a hex color (channel linearization)."""
    def _lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(value)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(hex1, hex2):
    """WCAG contrast ratio (Lmax + 0.05) / (Lmin + 0.05)."""
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    lmax, lmin = max(l1, l2), min(l1, l2)
    return (lmax + 0.05) / (lmin + 0.05)


def _build_qss():
    """Global stylesheet built from Palette D15 tokens (dark identity)."""
    p = PALETTE
    return f"""
    QWidget {{
        background-color: {p['BG']};
        color: {p['TEXT']};
        selection-background-color: {p['BLUE']};
        selection-color: {p['TEXT']};
    }}
    QMainWindow {{ background-color: {p['BG']}; }}
    QLabel {{ color: {p['TEXT']}; background-color: transparent; }}
    QPushButton {{
        background-color: {p['BLUE']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        padding: 6px 12px;
    }}
    QPushButton:disabled {{ color: {p['MUTED']}; }}
    QFrame, QGroupBox {{
        background-color: {p['CARD']};
        border: 1px solid {p['BORDER']};
    }}
    """


BASE_FONT_POINT_SIZE = 10


def apply_theme(app):
    """Apply full RTL, the dark Palette-D15 QPalette, QSS and Tajawal font."""
    p = PALETTE

    # Full RTL layout.
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    # Dark QPalette from Palette D15.
    palette = QPalette()
    bg = QColor(p["BG"])
    card = QColor(p["CARD"])
    text = QColor(p["TEXT"])
    blue = QColor(p["BLUE"])

    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.Base, bg)
    palette.setColor(QPalette.ColorRole.AlternateBase, card)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Button, blue)
    palette.setColor(QPalette.ColorRole.ToolTipBase, card)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, blue)
    palette.setColor(QPalette.ColorRole.HighlightedText, text)
    app.setPalette(palette)

    # Global QSS.
    app.setStyleSheet(_build_qss())

    # Application font.
    app.setFont(QFont("Tajawal", BASE_FONT_POINT_SIZE))

    return app


def set_base_font_scale(app, scale):
    """أعد تطبيق خط التطبيق الأساسي مقيسًا بمعامل التكبير مع حدود [0.8, 2.5]؛ يعيد المحتوى للتدفّق داخل QScrollArea."""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.8, min(2.5, scale))
    size = max(1, round(BASE_FONT_POINT_SIZE * scale))
    app.setFont(QFont("Tajawal", size))
    return scale
