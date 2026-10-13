# -*- coding: utf-8 -*-
"""بطاقة نتيجة الصفقة (DealResultCard) — G1.46 (عرض فقط).

تُعرَض أسفل بطاقة الوسيلة المنفِّذة للخروج، وتُظهر لأحدث صفقة مُغلقة أُسنِدت لتلك
الوسيلة: الدخول (سعر بدء المراقبة = reference_price) · الخروج (exit_price) ·
الجانب (side) · الربح/الخسارة (profit_pct٪ وprofit_usd). عرض صِرف يُغذَّى من
الخارج عبر ``update_result``؛ لا شبكة ولا منطق تداول. مخفيّة حتى تتوفّر نتيجة.

طبقة رفيعة على نمط ``percent_tracker`` (RTL + i18n عبر الشجرة العامّة + PALETTE).
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ._qt import Qt, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from .theme import PALETTE
from .percent_tracker import format_price, format_pct, color_for

_DASH = "—"

# عناوين عربية verbatim (تُترجَم عبر i18n في وضع الإنجليزية عبر شجرة الودجت).
_TITLE = "نتيجة الصفقة"
_CAP_ENTRY = "الدخول"
_CAP_EXIT = "الخروج"
_CAP_SIDE = "الجانب"
_CAP_PNL = "الربح/الخسارة"


def _to_dec(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_usd(value) -> str:
    """ربح/خسارة بالدولار مع إشارة؛ ``None`` ⇒ شرطة."""
    v = _to_dec(value)
    if v is None:
        return _DASH
    s = format_price(v)
    if s == _DASH:
        return _DASH
    return ("+" + s) if v > 0 else s


class DealResultCard(QWidget):
    """بطاقة عرض-فقط لنتيجة آخر صفقة مُسنَدة لوسيلة الخروج.

    تُغذَّى عبر ``update_result(trade)`` حيث ``trade`` كائن يحمل
    ``reference_price``/``exit_price``/``side``/``profit_pct``/``profit_usd``/
    ``profit_available`` (أو ``None`` ⇒ إخفاء البطاقة).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(4)

        self._title = QLabel(_TITLE)
        self._title.setStyleSheet(
            "color:%s;font-size:12px;font-weight:700;" % PALETTE.get("MUTED", "#6f8ba2")
        )
        root.addWidget(self._title)

        grid = QHBoxLayout()
        grid.setSpacing(12)
        self._val_entry = self._cell(grid, _CAP_ENTRY)
        self._val_exit = self._cell(grid, _CAP_EXIT)
        self._val_side = self._cell(grid, _CAP_SIDE)
        self._val_pnl = self._cell(grid, _CAP_PNL)
        root.addLayout(grid)

        self.update_result(None)

    def _cell(self, grid, caption_text):
        box = QVBoxLayout()
        cap = QLabel(caption_text)
        cap.setStyleSheet("color:%s;font-size:11px;" % PALETTE.get("MUTED", "#6f8ba2"))
        val = QLabel(_DASH)
        val.setStyleSheet(
            "color:%s;font-size:13px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb")
        )
        box.addWidget(cap)
        box.addWidget(val)
        grid.addLayout(box)
        return val

    def update_result(self, trade: Optional[Any]) -> None:
        """يملأ القيم ويُظهر البطاقة؛ ``None`` ⇒ إخفاء (لا نتيجة بعد)."""
        if trade is None:
            self._val_entry.setText(_DASH)
            self._val_exit.setText(_DASH)
            self._val_side.setText(_DASH)
            self._val_pnl.setText(_DASH)
            self._val_pnl.setStyleSheet(
                "color:%s;font-size:13px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb")
            )
            self.setVisible(False)
            return

        self._val_entry.setText(format_price(getattr(trade, "reference_price", None)))
        self._val_exit.setText(format_price(getattr(trade, "exit_price", None)))
        side = getattr(trade, "side", None)
        self._val_side.setText(str(side) if side else _DASH)

        profit_available = bool(getattr(trade, "profit_available", False))
        if profit_available:
            pct = getattr(trade, "profit_pct", None)
            usd = getattr(trade, "profit_usd", None)
            self._val_pnl.setText("%s (%s)" % (format_pct(pct), format_usd(usd)))
            self._val_pnl.setStyleSheet(
                "color:%s;font-size:13px;font-weight:700;" % color_for(pct)
            )
        else:
            self._val_pnl.setText(_DASH)
            self._val_pnl.setStyleSheet(
                "color:%s;font-size:13px;font-weight:700;" % PALETTE.get("TEXT", "#f0f7fb")
            )
        self.setVisible(True)
