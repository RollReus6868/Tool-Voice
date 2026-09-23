from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from providers import LANGUAGES, PROVIDERS, build_provider
from widgets import button, label
from workers import FuncWorker


class AddVoiceDialog(QDialog):
    """Add an existing provider voice ID (made elsewhere) to the local library."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thêm Voice ID có sẵn")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label("➕  Thêm Voice ID có sẵn", role="cardTitle", accent="blue"))
        lay.addWidget(label("Dùng khi bạn đã có Voice ID trên tài khoản Inworld/MiniMax "
                            "(tạo trên web hoặc máy khác).", role="hint", wrap=True))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.provider = QComboBox()
        self.provider.addItems(PROVIDERS)
        self.voice_id = QLineEdit()
        self.voice_id.setPlaceholderText("Dán Voice ID vào đây")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Tên dễ nhớ, ví dụ: Giọng nam trầm")
        self.language = QComboBox()
        self.provider.currentTextChanged.connect(self._fill_lang)
        self._fill_lang(self.provider.currentText())
        for r, (t, w) in enumerate([("Nhà cung cấp", self.provider), ("Voice ID", self.voice_id),
                                    ("Tên hiển thị", self.name), ("Ngôn ngữ", self.language)]):
            g.addWidget(label(t, role="field"), r, 0)
            g.addWidget(w, r, 1)
        lay.addLayout(g)
        self.err = label("", role="hint")
        self.err.setStyleSheet("color:#ef4444;")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Hủy", slot=self.reject))
        row.addWidget(button("✔  Thêm vào thư viện", variant="blue", slot=self._ok))
        lay.addLayout(row)

    def _fill_lang(self, provider):
        self.language.clear()
        for lbl, code in LANGUAGES[provider]:
            self.language.addItem(lbl, code)

    def _ok(self):
        if not self.voice_id.text().strip():
            self.err.setText("Hãy nhập Voice ID.")
            return
        self.accept()

    def result_voice(self) -> dict:
        vid = self.voice_id.text().strip()
        return {
            "provider": self.provider.currentText(),
            "provider_voice_id": vid,
            "local_name": self.name.text().strip() or vid,
            "language": self.language.currentData() or "",
        }


class ImportVoicesDialog(QDialog):
    """Fetch the voices on the user's provider account and pick some to import."""

    def __init__(self, provider: str, secrets: dict, config: dict, existing: set[str], parent=None):
        super().__init__(parent)
        self.provider = provider
        self.secrets = secrets
        self.config = config
        self.existing = existing
        self.voices: list[dict] = []
        self.setWindowTitle(f"Lấy giọng từ tài khoản {provider}")
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(label(f"☁  Giọng trên tài khoản {provider}", role="cardTitle", accent="green"))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Tìm theo tên hoặc Voice ID…")
        self.search.textChanged.connect(self._filter)
        self.kind = QComboBox()
        self.kind.addItems(["Tất cả", "Của tôi", "Hệ thống"])
        self.kind.setCurrentText("Của tôi")
        self.kind.currentTextChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        top.addWidget(self.kind)
        lay.addLayout(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tên", "Loại", "Voice ID", "Ngôn ngữ / mô tả"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(3, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.status = label("⏳ Đang tải danh sách giọng…", role="hint")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(label("Mẹo: giữ Ctrl để chọn nhiều giọng.", role="hint"))
        row.addStretch()
        row.addWidget(button("Đóng", slot=self.reject))
        self.ok_btn = button("➕  Thêm giọng đã chọn", variant="green", slot=self.accept)
        self.ok_btn.setEnabled(False)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)

        def job(log, cancelled, progress):
            return build_provider(provider, secrets, config).list_voices()

        self.worker = FuncWorker(job, self)
        self.worker.done.connect(self._loaded)
        self.worker.failed.connect(lambda e: self.status.setText("❌ " + e))
        self.worker.start()

    def _loaded(self, voices):
        self.voices = voices or []
        self.ok_btn.setEnabled(bool(self.voices))
        self._filter()

    def _filter(self):
        q = self.search.text().strip().lower()
        kind = self.kind.currentText()
        rows = [v for v in self.voices
                if (kind == "Tất cả" or v["kind"] == kind)
                and (not q or q in v["name"].lower() or q in v["voice_id"].lower())]
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            vals = [v["name"], v["kind"], v["voice_id"], v.get("language", "")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, v)
                if v["voice_id"] in self.existing:
                    it.setToolTip("Đã có trong thư viện")
                    it.setForeground(QColor("#8a93aa"))
                    if c == 0:
                        it.setText(val + "   ✔ đã có")
                self.table.setItem(r, c, it)
        self.status.setText(f"Hiển thị {len(rows)} / {len(self.voices)} giọng.")

    def selected(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        out = []
        for r in rows:
            it = self.table.item(r, 0)
            if it:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def reject(self):
        if self.worker.isRunning():
            self.worker.wait(3000)
        super().reject()

    def accept(self):
        if self.worker.isRunning():
            self.worker.wait(3000)
        super().accept()
