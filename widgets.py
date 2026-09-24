"""Small reusable UI building blocks."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)


def repolish(widget: QWidget) -> None:
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def button(text: str, *, variant: str | None = None, tint: str | None = None, size: str | None = None,
           tip: str = "", slot=None, min_w: int | None = None) -> QPushButton:
    """variant = solid coloured button, tint = soft coloured button."""
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        b.setProperty("variant", variant)
    if tint:
        b.setProperty("tint", tint)
    if size:
        b.setProperty("size", size)
    if tip:
        b.setToolTip(tip)
    if slot:
        b.clicked.connect(slot)
    if min_w:
        b.setMinimumWidth(min_w)
    return b


def label(text: str = "", role: str | None = None, wrap: bool = False, **props) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    for k, v in props.items():
        lb.setProperty(k, v)
    if wrap:
        lb.setWordWrap(True)
    return lb


class Card(QFrame):
    """Rounded surface with an optional coloured title bar."""

    def __init__(self, title: str = "", accent: str = "blue", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(18, 14, 18, 16)
        self.outer.setSpacing(10)
        if title:
            head = QHBoxLayout()
            head.setSpacing(10)
            bar = QFrame()
            bar.setProperty("accentbar", accent)
            bar.setFixedSize(4, 20)
            head.addWidget(bar)
            t = label(title, role="cardTitle", accent=accent)
            head.addWidget(t)
            head.addStretch()
            self.head = head
            self.outer.addLayout(head)
            if subtitle:
                self.outer.addWidget(label(subtitle, role="hint", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.outer.addLayout(self.body)

    def add(self, w):
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)
        return w


class StatTile(QFrame):
    def __init__(self, title: str, accent: str, icon: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("tile", accent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(0)
        self.value = label("0", role="tileValue")
        self.caption = label(f"{icon}  {title}".strip(), role="tileLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, v) -> None:
        self.value.setText(str(v))


class ChoiceRow(QWidget):
    """Segmented, mutually exclusive coloured buttons."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str, str]], parent=None):
        # options: (value, text, accent)
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for value, text, accent in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("choice", accent)
            b.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
            self.group.addButton(b)
            self.buttons[value] = b
            lay.addWidget(b)

    def value(self) -> str:
        for v, b in self.buttons.items():
            if b.isChecked():
                return v
        return next(iter(self.buttons))

    def set_value(self, value: str, emit: bool = False) -> None:
        b = self.buttons.get(value) or next(iter(self.buttons.values()))
        b.setChecked(True)
        if emit:
            self.changed.emit(value)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: rgba(128,128,128,60);")
    return f


class ResponsiveRow(QWidget):
    """Lays children side by side when there is room, otherwise stacks them.
    The owner calls update_for(available_width) on resize (a scroll area never
    shrinks its content below the minimum width, so the row cannot decide from
    its own width)."""

    def __init__(self, threshold: int, spacing: int = 12, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QBoxLayout

        self._QBoxLayout = QBoxLayout
        self.threshold = threshold
        self.lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(spacing)
        self.items: list[tuple[QWidget, int, int | None]] = []
        self.horizontal = True

    def add(self, w: QWidget, stretch: int = 0, fixed_width: int | None = None) -> QWidget:
        self.items.append((w, stretch, fixed_width))
        self.lay.addWidget(w, stretch)
        if fixed_width:
            w.setFixedWidth(fixed_width)
        return w

    def update_for(self, width: int) -> None:
        horizontal = width >= self.threshold
        if horizontal == self.horizontal:
            return
        self.horizontal = horizontal
        self.lay.setDirection(self._QBoxLayout.Direction.LeftToRight if horizontal
                              else self._QBoxLayout.Direction.TopToBottom)
        for w, stretch, fixed in self.items:
            if fixed:
                if horizontal:
                    w.setFixedWidth(fixed)
                else:
                    w.setMinimumWidth(0)
                    w.setMaximumWidth(16777215)
            self.lay.setStretchFactor(w, stretch if horizontal else 0)


# ---------------------------------------------------------------- usage charts (drawn with QPainter)
CHART_PALETTES = {
    "dark": {"text": "#e8ecf8", "muted": "#94a0c0", "grid": "#2b3350", "hole": "#171c2c"},
    "light": {"text": "#1b2335", "muted": "#5b6784", "grid": "#dfe4f0", "hole": "#ffffff"},
}
TOTAL_COLOR = "#2ec4cc"


def _short(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(int(n))


def _nice_max(v: float) -> float:
    if v <= 0:
        return 10
    mag = 10 ** (len(str(int(v))) - 1)
    for f in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if f * mag >= v:
            return f * mag
    return 10 * mag


class UsageBarChart(QWidget):
    """Stacked bars per time bucket: solid = read in the app, hatched = synced from Inworld."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pal = CHART_PALETTES["dark"]
        self.data: dict | None = None
        self.by_model = True
        self.colors: dict[str, str] = {}
        self._bars: list[tuple[QRectF, int]] = []

    def set_theme(self, mode: str) -> None:
        self.pal = CHART_PALETTES.get(mode, CHART_PALETTES["dark"])
        self.update()

    def set_data(self, data: dict, colors: dict[str, str], by_model: bool = True) -> None:
        self.data, self.colors, self.by_model = data, colors, by_model
        self.update()

    def _stack(self, i: int) -> list[tuple[str, int, bool]]:
        d = self.data or {}
        out = []
        for m in d.get("models", []):
            a = d.get("app", {}).get(m, [0] * (i + 1))[i] if m in d.get("app", {}) else 0
            sy = d.get("sync", {}).get(m, [0] * (i + 1))[i] if m in d.get("sync", {}) else 0
            if a:
                out.append((m, a, False))
            if sy:
                out.append((m, sy, True))
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.data or {"labels": []}
        n = len(d.get("labels", []))
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        left, right, top, bottom = fm.horizontalAdvance("00.0K") + 12, 8, 10, fm.height() + 10
        plot = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        totals = [sum(v for _m, v, _s in self._stack(i)) for i in range(n)]
        vmax = _nice_max(max(totals) if totals else 0)
        muted = QColor(self.pal["muted"])
        for k in range(5):
            y = plot.bottom() - plot.height() * k / 4
            p.setPen(QPen(QColor(self.pal["grid"]), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - fm.height() / 2, left - 6, fm.height()),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), _short(vmax * k / 4))
        self._bars = []
        if not n:
            p.end()
            return
        slot = plot.width() / n
        bw = max(2.0, min(34.0, slot * 0.62))
        for i in range(n):
            x = plot.left() + slot * i + (slot - bw) / 2
            y = plot.bottom()
            for m, v, synced in self._stack(i):
                h = plot.height() * v / vmax
                r = QRectF(x, y - h, bw, h)
                c = QColor(self.colors.get(m, TOTAL_COLOR) if self.by_model else TOTAL_COLOR)
                if synced:
                    c.setAlpha(120)
                p.fillRect(r, c)
                if synced and h > 3:
                    hatch = QColor(c)
                    hatch.setAlpha(230)
                    p.fillRect(r, QBrush(hatch, Qt.BrushStyle.BDiagPattern))
                y -= h
            self._bars.append((QRectF(plot.left() + slot * i, plot.top(), slot, plot.height()), i))
        # x labels: at most ~7, always the last one
        step = max(1, round(n / 7))
        p.setPen(muted)
        for i in range(n):
            if i % step and i != n - 1:
                continue
            if i != n - 1 and n - 1 - i < step * 0.6:
                continue
            cx = plot.left() + slot * (i + 0.5)
            txt = d["labels"][i]
            w = fm.horizontalAdvance(txt) + 4
            p.drawText(QRectF(cx - w / 2, plot.bottom() + 4, w, fm.height()),
                       int(Qt.AlignmentFlag.AlignCenter), txt)
        p.end()

    def mouseMoveEvent(self, e):
        pos = e.position()
        for r, i in self._bars:
            if r.contains(pos):
                parts = [f"<b>{self.data['labels'][i]}</b>"]
                total = 0
                for m, v, synced in self._stack(i):
                    total += v
                    parts.append(f"{m}{' (đồng bộ từ Inworld)' if synced else ''}: {v:,}".replace(",", "."))
                parts.append(f"Tổng: {total:,} ký tự".replace(",", "."))
                QToolTip.showText(e.globalPosition().toPoint(), "<br>".join(parts), self)
                return
        QToolTip.hideText()


class UsageDonut(QWidget):
    """Share of characters per model, total in the middle (like Inworld's donut)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(190, 190)
        self.pal = CHART_PALETTES["dark"]
        self.parts: list[tuple[str, int, str]] = []

    def set_theme(self, mode: str) -> None:
        self.pal = CHART_PALETTES.get(mode, CHART_PALETTES["dark"])
        self.update()

    def set_parts(self, parts: list[tuple[str, int, str]]) -> None:
        self.parts = [x for x in parts if x[1] > 0]
        self.setToolTip("<br>".join(f"{m}: {v:,} ký tự".replace(",", ".") for m, v, _c in self.parts))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 16
        ring = max(14.0, side * 0.16)
        r = QRectF((self.width() - side) / 2 + ring / 2, (self.height() - side) / 2 + ring / 2,
                   side - ring, side - ring)
        total = sum(v for _m, v, _c in self.parts)
        if not total:
            p.setPen(QPen(QColor(self.pal["grid"]), ring))
            p.drawEllipse(r)
        else:
            start = 90 * 16
            for _m, v, c in self.parts:
                span = -int(round(360 * 16 * v / total))
                pen = QPen(QColor(c), ring)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                p.drawArc(r, start, span)
                start += span
        f = QFont(self.font())
        p.setPen(QColor(self.pal["muted"]))
        p.setFont(f)
        fm = p.fontMetrics()
        c = r.center()
        p.drawText(QRectF(c.x() - 60, c.y() - fm.height() - 2, 120, fm.height()),
                   int(Qt.AlignmentFlag.AlignCenter), "Tổng")
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.5)
        p.setFont(f)
        p.setPen(QColor(self.pal["text"]))
        p.drawText(QRectF(c.x() - 70, c.y(), 140, p.fontMetrics().height()),
                   int(Qt.AlignmentFlag.AlignCenter), _short(total))
        p.end()
