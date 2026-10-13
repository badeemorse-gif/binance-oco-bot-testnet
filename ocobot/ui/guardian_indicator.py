"""عنصر مؤشّر الحارس في الواجهة (Guardian Indicator) — G1.31 / chunk_2.

عنصر **عرض فقط**: يترجم ``GuardianStatus`` إلى شارة حالة (مطفأ/نائم/رصد عُري/تدخّل)
+ سطر آخر إجراء. لا شبكة ولا منطق ولا I/O — يستقبل الحالة عبر ``update_status``.
يحترم حارس ``tests/test_ui_no_direct_network`` (لا أيّ نداء شبكي في طبقة الواجهة).
"""
from ._qt import Qt, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from . import i18n
from ocobot.domain.guardian_status import GuardianMode, GuardianStatus, GuardianUiState

# نصوص عربية verbatim للعرض.
_STATE_TEXT = {
    GuardianUiState.DISABLED: "الحارس: مطفأ",
    GuardianUiState.SLEEPING: "الحارس: نائم (يراقب)",
    GuardianUiState.WATCHING: "الحارس: رصد عُري…",
    GuardianUiState.INTERVENED: "الحارس: تدخّل ✓",
}
_MODE_TEXT = {
    GuardianMode.OFF: "مطفأ",
    GuardianMode.OBSERVE: "مراقبة",
    GuardianMode.LIVE: "تدخّل",
}


# G1.44 / chunk_4: نصوص عربية verbatim لمؤشّر حارس هبوط BTC (موازٍ، عرض فقط).
_BTC_STATE_TEXT = {
    GuardianUiState.DISABLED: "حارس BTC: مطفأ",
    GuardianUiState.SLEEPING: "حارس BTC: نائم (يراقب)",
    GuardianUiState.WATCHING: "حارس BTC: رصد هبوط…",
    GuardianUiState.INTERVENED: "حارس BTC: تدخّل ✓",
}


class GuardianIndicator(QWidget):
    """شارة حالة الحارس + سطر آخر إجراء (عرض فقط، يُحدَّث عبر update_status).

    G1.44 / chunk_4: ``state_text_map`` اختياري يسمح بإعادة استعمال العنصر نفسه
    لمؤشّر حارس هبوط BTC بنصوص حالة مختلفة (موازٍ) دون تكرار الكود.
    """

    def __init__(self, parent=None, state_text_map=None):
        super().__init__(parent)
        self._state_text_map = state_text_map or _STATE_TEXT
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        self._state_label = QLabel()
        self._mode_label = QLabel()
        row.addWidget(self._state_label)
        row.addWidget(self._mode_label)
        row.addStretch(1)
        root.addLayout(row)
        self._last_action_label = QLabel()
        root.addWidget(self._last_action_label)
        self._apply(GuardianStatus())

    def update_status(self, status: GuardianStatus) -> None:
        """يُحدِّث الشارة من لقطة ``GuardianStatus`` (عرض فقط)."""
        self._apply(status)

    def _apply(self, status: GuardianStatus) -> None:
        self._status = status
        self._state_label.setText(
            i18n.translate_for_current(self._state_text_map.get(status.state, "الحارس: —"))
        )
        self._mode_label.setText(
            i18n.translate_for_current("الوضع: ")
            + i18n.translate_for_current(_MODE_TEXT.get(status.mode, "—"))
        )
        la = status.last_action
        if la is None:
            self._last_action_label.setText("")
            return
        parts = [i18n.translate_for_current("آخر إجراء: ") + i18n.translate_for_current(la.action)]
        if la.reason:
            parts.append(i18n.translate_for_current(la.reason))
        if la.qty:
            parts.append(i18n.translate_for_current("كمية ") + la.qty)
        if la.price:
            parts.append(i18n.translate_for_current("سعر ") + la.price)
        if la.ts:
            parts.append(la.ts)
        self._last_action_label.setText(" · ".join(parts))

    def retranslate_i18n(self) -> None:
        """يعيد رسم الشارة من آخر حالة مخزّنة باللغة الفعّالة (عند تبديل اللغة)."""
        self._apply(self._status)

    # مساعدات قراءة (للاختبار/التفتيش).
    def state_text(self) -> str:
        return self._state_label.text()

    def mode_text(self) -> str:
        return self._mode_label.text()

    def last_action_text(self) -> str:
        return self._last_action_label.text()


class BtcFollowIndicator(GuardianIndicator):
    """G1.44 / chunk_4: مؤشّر حارس هبوط BTC — نفس العنصر بنصوص حالة BTC."""

    def __init__(self, parent=None):
        super().__init__(parent, state_text_map=_BTC_STATE_TEXT)
