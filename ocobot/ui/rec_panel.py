# -*- coding: utf-8 -*-
"""لوحة «ترشيح النِّسب التكيّفي» — عرض فقط (G1.56 · c6).

تعرض اقتراح recommender (tp/sl/trigger/gap + النظام + الرايات) وزرّ «ملء مرّة
واحدة» يملأ النسب في نموذج الأمر عبر callback مُحقَّن. كذلك مُحدِّد «وضع المتتبّع»
(مُطفأ/مراقبة/حيّ) الذي يُوصَّل في c7 بوحدة التحكّم rec_tracker.

لا شبكة ولا IO ولا منطق تداول هنا — طبقة عرض محضة (حارس test_ui_no_direct_network)؛
الاقتراح يُحسب خارجيًا (الرَنَر ⇒ klines ⇒ recommender) ويُمرَّر عبر
update_recommendation. منطق التنسيق دوالّ خالصة قابلة للاختبار بلا QApplication.
"""
from typing import Optional

from . import i18n
from ._qt import (Qt, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                  QVBoxLayout, QWidget)
from .theme import PALETTE

# أوضاع المتتبّع (محايدة؛ تُستهلك في c7).
MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_LIVE = "live"
# (نصّ عربي مصدر, مفتاح) — الافتراضي «مراقبة».
_MODE_ITEMS = (("مُطفأ", MODE_OFF), ("مراقبة فقط", MODE_OBSERVE), ("حيّ", MODE_LIVE))

_TITLE = "ترشيح النِّسب التكيّفي"
_FILL_BTN = "ملء مرّة واحدة"
_MODE_CAPTION = "وضع المتتبّع"
_DASH = "—"

# (مفتاح الحقل, العنوان العربي المصدر)
_FIELDS = (
    ("tp", "جني الأرباح %"),
    ("sl", "وقف الخسارة %"),
    ("trigger", "مُشغّل التموضع %"),
    ("gap", "فجوة (ticks)"),
    ("regime", "النظام"),
)


def format_rec_fields(rec) -> dict:
    """يحوّل Recommendation (أو None) إلى نصوص عرض خالصة (قابلة للاختبار)."""
    from ocobot.domain.models import fmt
    if rec is None:
        return {k: _DASH for k, _ in _FIELDS} | {"flags": ""}
    return {
        "tp": "%s%%" % fmt(rec.tp_pct),
        "sl": "%s%%" % fmt(rec.sl_pct),
        "trigger": "%s%%" % fmt(rec.trigger_pct),
        "gap": str(rec.gap_ticks),
        "regime": str((rec.rationale or {}).get("regimeLabel", _DASH)),
        "flags": ", ".join(rec.flags or []),
    }


class RecommendationPanel(QWidget):
    """لوحة عرض-فقط لاقتراح النِّسب + «ملء مرّة واحدة» + مُحدِّد وضع المتتبّع."""

    def __init__(self, parent=None, on_fill_once=None, on_mode_change=None):
        super().__init__(parent)
        self._on_fill_once = on_fill_once
        self._on_mode_change = on_mode_change
        self._rec = None
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._title = QLabel()
        self._title.setStyleSheet(
            "color:%s;font-size:13px;font-weight:800;" % PALETTE.get("TEXT", "#f0f7fb"))
        root.addWidget(self._title)

        grid = QGridLayout()
        self._caption_labels = []  # (ar_source, QLabel)
        self._value_labels = {}
        for col, (key, cap) in enumerate(_FIELDS):
            clab = QLabel()
            vlab = QLabel()
            clab.setStyleSheet("color:%s;font-size:11px;" % PALETTE.get("MUTED", "#6f8ba2"))
            vlab.setStyleSheet("color:%s;font-size:14px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb"))
            grid.addWidget(clab, 0, col)
            grid.addWidget(vlab, 1, col)
            self._caption_labels.append((cap, clab))
            self._value_labels[key] = vlab
        root.addLayout(grid)

        self._flags_label = QLabel()
        self._flags_label.setStyleSheet("color:%s;font-size:10px;" % PALETTE.get("MUTED", "#6f8ba2"))
        self._flags_label.setWordWrap(True)
        root.addWidget(self._flags_label)

        bar = QHBoxLayout()
        self._mode_caption = QLabel()
        self._mode_caption.setStyleSheet("color:%s;font-size:11px;" % PALETTE.get("MUTED", "#6f8ba2"))
        self._mode_combo = QComboBox()
        for ar_src, key in _MODE_ITEMS:
            self._mode_combo.addItem(ar_src, key)
        self._mode_combo.setCurrentIndex(1)  # الافتراضي: مراقبة
        self._mode_combo.currentIndexChanged.connect(self._on_mode_idx_changed)

        self._fill_btn = QPushButton()
        self._fill_btn.setEnabled(False)
        self._fill_btn.clicked.connect(self._on_fill_clicked)

        bar.addWidget(self._mode_caption)
        bar.addWidget(self._mode_combo)
        bar.addStretch(1)
        bar.addWidget(self._fill_btn)
        root.addLayout(bar)

        self._apply_i18n()
        self.update_recommendation(None)

    # ---- i18n ----
    def _apply_i18n(self) -> None:
        self._title.setText(i18n.translate_for_current(_TITLE))
        self._fill_btn.setText(i18n.translate_for_current(_FILL_BTN))
        self._mode_caption.setText(i18n.translate_for_current(_MODE_CAPTION))
        for cap, lab in self._caption_labels:
            lab.setText(i18n.translate_for_current(cap))
        for i, (ar_src, _key) in enumerate(_MODE_ITEMS):
            self._mode_combo.setItemText(i, i18n.translate_for_current(ar_src))

    def retranslate_i18n(self) -> None:
        self._apply_i18n()

    # ---- data ----
    def update_recommendation(self, rec) -> None:
        self._rec = rec
        fields = format_rec_fields(rec)
        for key, lab in self._value_labels.items():
            lab.setText(fields[key])
        self._flags_label.setText(fields["flags"])
        self._fill_btn.setEnabled(rec is not None)

    def current_recommendation(self):
        return self._rec

    # ---- mode ----
    def mode(self) -> str:
        return self._mode_combo.currentData()

    def set_mode(self, key: str) -> None:
        for i, (_ar, k) in enumerate(_MODE_ITEMS):
            if k == key:
                self._mode_combo.setCurrentIndex(i)
                return

    def _on_mode_idx_changed(self, _idx) -> None:
        if callable(self._on_mode_change):
            self._on_mode_change(self.mode())

    def _on_fill_clicked(self) -> None:
        if self._rec is not None and callable(self._on_fill_once):
            self._on_fill_once(self._rec)

    # ---- مساعدات اختبار/تفتيش ----
    def value_texts(self) -> dict:
        return {k: v.text() for k, v in self._value_labels.items()}

    def caption_texts(self):
        return [lab.text() for _cap, lab in self._caption_labels]
