from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

import usage
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
    """Browse the voices on the user's provider account: filter, preview, add to the
    library or use one right away."""

    ALL = "Tất cả"

    def __init__(self, provider: str, secrets: dict, config: dict, existing: set[str], parent=None,
                 kind: str = "Của tôi", preview=None):
        super().__init__(parent)
        self.provider = provider
        self.secrets = secrets
        self.config = config
        self.existing = existing
        self.preview = preview            # callable(voice_dict) or None
        self.use_now: dict | None = None  # set when the user clicks "Dùng ngay"
        self.voices: list[dict] = []
        self.setWindowTitle(f"Giọng trên tài khoản {provider}")
        self.resize(1040, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(label(f"☁  Giọng trên tài khoản {provider}", role="cardTitle", accent="green"))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Tìm theo tên, mô tả, thẻ hoặc Voice ID…")
        self.search.textChanged.connect(self._filter)
        self.kind = QComboBox()
        self.kind.addItems([self.ALL, "Của tôi", "Hệ thống"])
        self.kind.setCurrentText(kind if kind in ("Của tôi", "Hệ thống") else self.ALL)
        self.kind.setToolTip("Của tôi = giọng bạn clone/tạo • Hệ thống = giọng có sẵn của nhà cung cấp")
        self.lang = QComboBox()
        self.lang.addItem("🌐 Mọi ngôn ngữ", "")
        self.gender = QComboBox()
        self.gender.addItem("👤 Mọi giới tính", "")
        for w, width in ((self.kind, 120), (self.lang, 170), (self.gender, 160)):
            w.setMinimumWidth(width)
            w.currentIndexChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        top.addWidget(self.kind)
        top.addWidget(self.lang)
        top.addWidget(self.gender)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tên", "Loại", "Giới tính", "Ngôn ngữ", "Mô tả / thẻ", "Voice ID"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(5, 200)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _: self._use_now())
        self.table.itemSelectionChanged.connect(self._sel_changed)
        lay.addWidget(self.table, 1)
        self.status = label("⏳ Đang tải danh sách giọng…", role="hint")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(label("Mẹo: giữ Ctrl để chọn nhiều • nháy đúp = dùng ngay.", role="hint"))
        row.addStretch()
        self.preview_btn = button("▶  Nghe thử", tint="cyan", slot=self._preview,
                                  tip="Đọc một câu mẫu bằng giọng đang chọn (tính phí vài chục ký tự)")
        self.preview_btn.setVisible(preview is not None)
        row.addWidget(self.preview_btn)
        row.addWidget(button("Đóng", slot=self.reject))
        self.ok_btn = button("➕  Thêm vào thư viện", tint="green", slot=self.accept)
        self.use_btn = button("🗣  Dùng ngay", variant="green", slot=self._use_now,
                              tip="Thêm giọng đang chọn vào thư viện và chọn nó để đọc")
        row.addWidget(self.ok_btn)
        row.addWidget(self.use_btn)
        lay.addLayout(row)
        self._sel_changed()

        def job(log, cancelled, progress):
            return build_provider(provider, secrets, config).list_voices()

        self.worker = FuncWorker(job, self)
        self.worker.done.connect(self._loaded)
        self.worker.failed.connect(lambda e: self.status.setText("❌ " + e))
        self.worker.start()

    def _loaded(self, voices):
        self.voices = voices or []
        langs = sorted({v.get("language", "") for v in self.voices if v.get("language")})
        genders = sorted({v.get("gender", "") for v in self.voices if v.get("gender")})
        for combo, values in ((self.lang, langs), (self.gender, genders)):
            combo.blockSignals(True)
            for val in values:
                combo.addItem(val, val)
            combo.blockSignals(False)
        vi = self.lang.findData("vi-VN")
        mine = sum(1 for v in self.voices if v["kind"] == "Của tôi")
        if self.kind.currentText() == "Của tôi" and not mine and self.voices:
            self.kind.setCurrentText(self.ALL)        # nothing cloned yet: show the catalogue
        elif vi >= 0 and self.kind.currentText() != "Của tôi":
            self.lang.setCurrentIndex(vi)
        self._filter()

    def _filter(self):
        q = self.search.text().strip().lower()
        kind = self.kind.currentText()
        lang = self.lang.currentData() or ""
        gender = self.gender.currentData() or ""

        def hay(v):
            return " ".join([v["name"], v["voice_id"], v.get("description", ""), " ".join(v.get("tags") or [])]).lower()

        rows = [v for v in self.voices
                if (kind == self.ALL or v["kind"] == kind)
                and (not lang or v.get("language") == lang)
                and (not gender or v.get("gender") == gender)
                and (not q or q in hay(v))]
        rows.sort(key=lambda v: (v["kind"] != "Của tôi", v["name"].lower()))
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            desc = v.get("description", "")
            tags = ", ".join(v.get("tags") or [])
            info = desc + (f"  [{tags}]" if tags else "")
            vals = [v["name"], v["kind"], v.get("gender", ""), v.get("language", ""), info, v["voice_id"]]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, v)
                if c == 4:
                    it.setToolTip(info)
                if v["voice_id"] in self.existing:
                    it.setToolTip("Đã có trong thư viện")
                    it.setForeground(QColor("#8a93aa"))
                    if c == 0:
                        it.setText(val + "   ✔ đã có")
                self.table.setItem(r, c, it)
        mine = sum(1 for v in self.voices if v["kind"] == "Của tôi")
        self.status.setText(f"Hiển thị {len(rows)} / {len(self.voices)} giọng  •  {mine} giọng của bạn.")
        self._sel_changed()

    def _sel_changed(self):
        n = len(self.selected()) if self.voices else 0
        self.ok_btn.setEnabled(n > 0)
        self.use_btn.setEnabled(n == 1)
        self.preview_btn.setEnabled(n == 1)

    def _preview(self):
        sel = self.selected()
        if len(sel) == 1 and self.preview:
            self.preview(sel[0])

    def _use_now(self):
        sel = self.selected()
        if len(sel) == 1:
            self.use_now = sel[0]
            self.accept()

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


class SyncUsageDialog(QDialog):
    """Type the numbers shown on Inworld's Billing and Usage pages (Inworld has no API for them)."""

    RANGES = [(30, "Last 30 days (30 ngày)"), (7, "Last 7 days (7 ngày)"), (1, "Last 24 hours (24 giờ)")]

    def __init__(self, data: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Đồng bộ với Inworld")
        self.setMinimumWidth(600)
        self.values: tuple[float | None, dict, int] | None = None
        d = usage.normalize(data)
        last = d.get("sync") or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("🔄  Đồng bộ với Inworld", role="cardTitle", accent="violet"))
        lay.addWidget(label(
            "Inworld không cho app đọc trang Billing/Usage, nên bạn chép số ở đó vào đây. App lấy đúng số này "
            "làm mốc rồi tự cộng các lần đọc sau đó.\n"
            "① Billing: số dư (credit balance) ở đầu trang.\n"
            "② Usage › Usage history: chọn khung thời gian và All API keys, chép số “Text-to-Speech … characters” "
            "và số từng model trong bảng. Để trống ô nào thì ô đó giữ như cũ.", role="hint", wrap=True))
        links = QHBoxLayout()
        links.addWidget(button("🔗 Mở Billing", tint="violet",
                               slot=lambda: QDesktopServices.openUrl(QUrl(usage.BILLING_URL))))
        links.addWidget(button("📈 Mở Usage", tint="blue",
                               slot=lambda: QDesktopServices.openUrl(QUrl(usage.USAGE_URL))))
        links.addStretch()
        lay.addLayout(links)

        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.balance = QLineEdit()
        self.balance.setPlaceholderText("vd $22.10 — để trống nếu không muốn đổi")
        if last.get("balance") is not None:
            self.balance.setToolTip(f"Lần trước: {usage.fmt_usd(last['balance'])}")
        self.range = QComboBox()
        for days, text in self.RANGES:
            self.range.addItem(text, days)
        self.range.setCurrentIndex(max(0, self.range.findData(last.get("days") or 30)))
        self.range.setToolTip("Khung thời gian đang chọn trên trang Usage của Inworld")
        self.total = QLineEdit()
        self.total.setPlaceholderText("vd 2,755 (số chính xác ở ô Usage by service)")
        g.addWidget(label("💰 Số dư Billing", role="field"), 0, 0)
        g.addWidget(self.balance, 0, 1)
        g.addWidget(label("🗓 Khung Usage", role="field"), 1, 0)
        g.addWidget(self.range, 1, 1)
        g.addWidget(label("🔤 Tổng ký tự TTS", role="field"), 2, 0)
        g.addWidget(self.total, 2, 1)
        self.model_edits: dict[str, QLineEdit] = {}
        for i, m in enumerate(usage.SYNC_MODELS):
            e = QLineEdit()
            e.setPlaceholderText("vd 2.5K hoặc 270 — trống = 0")
            dot = f"<span style='color:{usage.MODEL_COLORS.get(m, '#888')}'>●</span> {m}"
            lb = label(dot, role="field")
            lb.setTextFormat(Qt.TextFormat.RichText)
            g.addWidget(lb, 3 + i, 0)
            g.addWidget(e, 3 + i, 1)
            self.model_edits[m] = e
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self.preview = label("", role="hint", wrap=True)
        lay.addWidget(self.preview)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Huỷ", slot=self.reject))
        self.ok_btn = button("✅  Đồng bộ", variant="violet", slot=self._accept)
        r.addWidget(self.ok_btn)
        lay.addLayout(r)
        for e in [self.balance, self.total, *self.model_edits.values()]:
            e.textChanged.connect(self._update_preview)
        self._update_preview()

    def _parse(self):
        balance = usage.parse_money(self.balance.text())
        total = usage.parse_count(self.total.text())
        chars = {}
        for m, e in self.model_edits.items():
            n = usage.parse_count(e.text())
            if n is not None:
                chars[m] = n
        if total is not None or chars:
            chars = usage.reconcile(total, {m: chars.get(m, 0) for m in chars} if chars else {})
            if total is not None and sum(chars.values()) != total:
                raise ValueError("Tổng các model lớn hơn tổng ký tự — kiểm tra lại số đã chép.")
        return balance, chars, int(self.range.currentData())

    def _update_preview(self):
        try:
            balance, chars, days = self._parse()
        except ValueError as e:
            msg = str(e) if "Tổng" in str(e) else f"Không đọc được số “{e}”. Ví dụ đúng: 2,755 • 2.5K • $22.10"
            self.preview.setText("⚠ " + msg)
            self.ok_btn.setEnabled(False)
            return
        parts = []
        if balance is not None:
            parts.append(f"💰 số dư {usage.fmt_usd(balance)}")
        if chars:
            parts.append("🔤 " + " • ".join(f"{m}: {usage.fmt_int(n)}" for m, n in chars.items() if n)
                         + f" = {usage.fmt_int(sum(chars.values()))} ký tự ({days} ngày)")
        self.preview.setText("→ Sẽ lưu: " + ("   ".join(parts) if parts else "chưa nhập gì"))
        self.ok_btn.setEnabled(bool(parts))

    def _accept(self):
        try:
            self.values = self._parse()
        except ValueError:
            return
        self.accept()
