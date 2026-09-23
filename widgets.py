"""Small reusable UI building blocks."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
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
