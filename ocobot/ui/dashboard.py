"""شاشة لوحة التحكم (Dashboard) — T11a.

تعرض لقطة DashboardSnapshot المبنيّة عبر خدمة build_dashboard (قراءة فقط).
لا قيم ثابتة موهِمة (D14): تبدأ الحقول بـ '—' وتُملأ فقط من لقطة حقيقية.
RTL + ثيم داكن عبر PALETTE (D15).
"""
from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
)
from .theme import PALETTE
from . import i18n

EMPTY = "—"
NO_SELECTION_NOTE = "لم يُختَر أمر"

# مجموعة حقول لوحة التحكم القانونية (التصميم §3.1 A) مربوطة بسمات DashboardSnapshot
DASHBOARD_FIELDS = [
    ("الـ OCO المختار", "selected_oco"),
    ("الرمز", "symbol"),
    ("السعر الحالي", "current_price"),
    ("جني الأرباح الحالي", "current_tp"),
    ("مُشغِّل وقف الخسارة الحالي", "current_sl"),
    ("السعر المرجعي", "reference_price"),
    ("المُشغِّل التالي", "next_trigger"),
    ("حالة المراقبة", "monitoring_state"),
    ("الاتصال", "connection"),
    ("آخر إعادة تموضع", "last_reposition"),
    ("البيئة", "environment"),
]

_STATE_ACCENT = {
    "ACTIVE": "GREEN",
    "IDLE": "MUTED",
    "PAUSED": "AMBER",
    "LATCHED": "BLUE",
    "IN_FLIGHT": "TEAL",
}


class _FieldCard(QFrame):
    """بطاقة حقل واحد: عنوان + قيمة."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardCard")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(
            "QFrame#DashboardCard{background:%s;border:1px solid %s;border-radius:10px;}"
            % (PALETTE["CARD"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.caption = QLabel(label, self)
        self.caption.setObjectName("DashboardCaption")
        self.caption.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
        self.value = QLabel(EMPTY, self)
        self.value.setObjectName("DashboardValue")
        self.value.setStyleSheet(
            "color:%s;font-size:22px;font-weight:600;" % PALETTE["TEXT"]
        )
        lay.addWidget(self.caption)
        lay.addWidget(self.value)

    def set_value(self, text):
        self.value.setText(EMPTY if text is None or text == "" else str(text))


class DashboardScreen(QWidget):
    """شاشة القراءة للوحة التحكم، موصولة بمخرجات build_dashboard."""

    def __init__(self, parent=None, runner=None, build_fn=None):
        super().__init__(parent)
        self.screen_key = "01_dashboard"
        self.setObjectName("Screen_01_dashboard")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._runner = runner
        self._build_fn = build_fn
        self._cards = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        self.heading = QLabel("لوحة التحكم", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        self.note = QLabel(NO_SELECTION_NOTE, self)
        self.note.setObjectName("DashboardNote")
        self.note.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        root.addWidget(self.note)

        row = None
        for i, (label, attr) in enumerate(DASHBOARD_FIELDS):
            if i % 3 == 0:
                row = QHBoxLayout()
                row.setSpacing(14)
                root.addLayout(row)
            card = _FieldCard(label, self)
            self._cards[attr] = card
            row.addWidget(card)
        remainder = len(DASHBOARD_FIELDS) % 3
        if remainder and row is not None:
            for _ in range(3 - remainder):
                row.addStretch(1)
        root.addStretch(1)

    def update_snapshot(self, snapshot):
        """تحديث الحقول من DashboardSnapshot (قراءة فقط)."""
        if snapshot is None:
            self.clear()
            return
        has_selection = getattr(snapshot, "selected_oco", EMPTY) not in (EMPTY, "", None)
        self.note.setText("" if has_selection else i18n.translate_for_current(NO_SELECTION_NOTE))
        for attr, card in self._cards.items():
            card.set_value(getattr(snapshot, attr, EMPTY))
        state = str(getattr(snapshot, "monitoring_state", "IDLE") or "IDLE")
        accent = PALETTE.get(_STATE_ACCENT.get(state.upper(), "TEXT"), PALETTE["TEXT"])
        self._cards["monitoring_state"].value.setStyleSheet(
            "color:%s;font-size:22px;font-weight:600;" % accent
        )

    def clear(self):
        self.note.setText(i18n.translate_for_current(NO_SELECTION_NOTE))
        for card in self._cards.values():
            card.set_value(EMPTY)

    def refresh(self, build_fn=None):
        """جلب لقطة عبر build_fn (ترجع DashboardSnapshot) وعرضها.

        مع runner يُنفَّذ على خيط منفصل (T10c)؛ بلا runner يُنفَّذ متزامنًا (اختبارات).
        """
        fn = build_fn or self._build_fn
        if fn is None:
            return None
        if self._runner is not None:
            return self._runner.submit(fn, on_result=self.update_snapshot)
        self.update_snapshot(fn())
        return None
