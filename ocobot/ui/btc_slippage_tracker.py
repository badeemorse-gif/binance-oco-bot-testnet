# -*- coding: utf-8 -*-
"""لوحة تتبّع انزلاق BTC بنافذة متحرّكة (BtcSlippageTracker) — G1.50 (عرض فقط).

عرض صِرف يُغذَّى من الخارج: سعر BTC الحيّ · ذروة النافذة · انزلاق النافذة % · طور الحارس.
الانزلاق محسوب بنافذة متحرّكة (ذروة النافذة مقابل الحيّ) بإعادة استخدام
domain.btc_follow._window_drop ليطابق ما يُسلّح حارس هبوط BTC — لا نافذة مرساة عند البدء.
لا شبكة ولا منطق تداول/تنفيذ ولا hot_path (حارس test_ui_no_direct_network).
"""
from decimal import Decimal

from . import i18n
from ._qt import Qt, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from .theme import PALETTE
from .percent_tracker import format_pct, format_price, color_for
from ocobot.domain.btc_follow import _window_drop

_DASH = "—"
_HEADING = "تتبّع انزلاق BTC (نافذة متحرّكة)"
_CAPTIONS = ("سعر BTC الحيّ", "ذروة النافذة", "انزلاق النافذة %", "طور الحارس")
_PHASE_AR = {"IDLE": "خامل", "ARMED": "مُسلّح"}


def window_slippage(samples, now, window_seconds):
    """انزلاق النافذة المتحرّكة (دالة خالصة): dict{drop_pct,peak,current} أو None.

    يعيد استخدام _window_drop (ذروة النافذة مقابل آخر عيّنة فيها). fail-safe ⇒ None.
    """
    try:
        r = _window_drop(samples, float(now), float(window_seconds))
    except Exception:
        return None
    if r is None:
        return None
    drop, peak, current = r
    return {"drop_pct": drop, "peak": peak, "current": current}


class BtcSlippageTracker(QWidget):
    """صفّ عرض-فقط: سعر حيّ · ذروة · انزلاق % · طور الحارس. يُغذَّى عبر update_slippage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._heading = QLabel()
        self._heading.setStyleSheet("color:%s;font-size:12px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb"))
        root.addWidget(self._heading)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._caption_labels = []
        self._value_labels = []
        for cap in _CAPTIONS:
            box = QVBoxLayout()
            clab = QLabel()
            vlab = QLabel()
            clab.setStyleSheet("color:%s;font-size:11px;" % PALETTE.get("MUTED", "#6f8ba2"))
            vlab.setStyleSheet("color:%s;font-size:14px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb"))
            box.addWidget(clab)
            box.addWidget(vlab)
            row.addLayout(box)
            self._caption_labels.append((cap, clab))
            self._value_labels.append(vlab)
        root.addLayout(row)
        self._cur = self._peak = self._drop = None
        self._phase = None
        self._apply_captions()
        self.update_slippage(None, None, None, None)

    def _apply_captions(self):
        self._heading.setText(i18n.translate_for_current(_HEADING))
        for cap, lab in self._caption_labels:
            lab.setText(i18n.translate_for_current(cap))

    def retranslate_i18n(self):
        self._apply_captions()
        self._render()

    def update_slippage(self, current, peak, drop_pct, phase):
        self._cur, self._peak, self._drop, self._phase = current, peak, drop_pct, phase
        self._render()

    def _render(self):
        vals = self._value_labels
        vals[0].setText(format_price(self._cur))
        vals[1].setText(format_price(self._peak))
        if self._drop is None:
            vals[2].setText(_DASH)
            vals[2].setStyleSheet("color:%s;font-size:14px;font-weight:700;" % PALETTE.get("MUTED", "#6f8ba2"))
        else:
            try:
                neg = -Decimal(str(self._drop))
            except Exception:
                neg = None
            vals[2].setText(format_pct(neg))
            vals[2].setStyleSheet("color:%s;font-size:14px;font-weight:700;" % color_for(neg))
        if self._phase is None:
            vals[3].setText(_DASH)
        else:
            ar = _PHASE_AR.get(str(self._phase), str(self._phase))
            vals[3].setText(i18n.translate_for_current(ar))
