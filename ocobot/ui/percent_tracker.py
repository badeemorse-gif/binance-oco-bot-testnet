# -*- coding: utf-8 -*-
"""عنصر تتبّع النِّسب اللحظية (PercentTracker) — G1.45 / chunk_1 (عرض فقط).

أربعة صناديق: سعر حيّ · سعر سابق · نسبة التغيّر · نسبة التتبّع.
قواعد اللون الموحّدة: أخضر صعود (>0) · أحمر هبوط (<0) · محايد (0/غير متاح).
صيغة النِّسب: ``0.00000%`` (خمس خانات عشرية مع إشارة). لا شبكة ولا منطق تداول —
عرض صِرف يُغذَّى من الخارج عبر ``update_prices``.

منطق التنسيق/الاتجاه/اللون دوالٌّ خالصة (قابلة للاختبار بلا QApplication)؛ الودجت
طبقة رفيعة فوقها على نمط ``guardian_indicator`` (RTL + i18n + retranslate_i18n).
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from . import i18n
from ._qt import Qt, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from .theme import PALETTE

# مفاتيح الاتجاه (محايدة عن Qt).
UP = "up"
DOWN = "down"
FLAT = "flat"

_PCT_Q = Decimal("0.00001")  # خمس خانات عشرية.
_DASH = "—"

# نصوص العناوين العربية verbatim (تُترجَم عبر i18n في وضع الإنجليزية).
_CAPTIONS = ("سعر حيّ", "سعر سابق", "نسبة التغيّر", "نسبة التتبّع")


def _to_dec(value) -> Optional[Decimal]:
    """تحويل آمن إلى Decimal (None/'' تبقى None؛ التالف -> None)."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def pct_change(current, previous) -> Optional[Decimal]:
    """نسبة التغيّر % من ``previous`` إلى ``current``.

    ``None`` إذا تعذّر الحساب (غياب قيمة أو مرجع صفري).
    """
    c = _to_dec(current)
    p = _to_dec(previous)
    if c is None or p is None or p == 0:
        return None
    return (c - p) / p * Decimal(100)


def direction_key(pct) -> str:
    """UP/DOWN/FLAT من قيمة نسبة (``None`` أو 0 ⇒ FLAT)."""
    v = _to_dec(pct)
    if v is None or v == 0:
        return FLAT
    return UP if v > 0 else DOWN


def format_pct(pct) -> str:
    """صيغة ``0.00000%`` مع إشارة؛ ``None`` ⇒ ``0.00000%`` (محايد متاح افتراضيًّا)."""
    v = _to_dec(pct)
    if v is None:
        return "0.00000%"
    q = v.quantize(_PCT_Q)
    sign = "+" if q > 0 else ""  # السالب يحمل '-' أصلًا؛ الصفر بلا إشارة.
    return "%s%s%%" % (sign, q)


def format_price(price) -> str:
    """سعر مقروء بنقطة ثابتة (بلا ترميز علمي)؛ ``None`` ⇒ شرطة."""
    v = _to_dec(price)
    if v is None:
        return _DASH
    s = format(v, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def color_for(pct) -> str:
    """لون نصّ النسبة من ``PALETTE`` حسب الاتجاه (أخضر/أحمر/محايد)."""
    k = direction_key(pct)
    if k == UP:
        return PALETTE.get("GREEN", "#19c58b")
    if k == DOWN:
        return PALETTE.get("RED", "#ff4b68")
    return PALETTE.get("MUTED", "#6f8ba2")


class PercentTracker(QWidget):
    """صفّ أربعة صناديق عرض-فقط (سعر حيّ/سابق/نسبة تغيّر/نسبة تتبّع).

    يُغذَّى من الخارج عبر ``update_prices(live, previous, tracking_previous)``؛
    لا يقرأ شبكةً ولا حالةً — طبقة عرض محضة (حارس ``test_ui_no_direct_network``).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
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
            root.addLayout(box)
            self._caption_labels.append((cap, clab))
            self._value_labels.append(vlab)
        self._live = self._prev = self._track_prev = None
        self._apply_captions()
        self.update_prices(None, None, None)

    def _apply_captions(self) -> None:
        for cap, lab in self._caption_labels:
            lab.setText(i18n.translate_for_current(cap))

    def update_prices(self, live, previous, tracking_previous=None) -> None:
        """يحدّث الصناديق الأربعة (عرض فقط)."""
        self._live, self._prev, self._track_prev = live, previous, tracking_previous
        change = pct_change(live, previous)
        track = pct_change(live, tracking_previous)
        text_col = PALETTE.get("TEXT", "#f0f7fb")
        cells = (
            (format_price(live), text_col, "400"),
            (format_price(previous), text_col, "400"),
            (format_pct(change), color_for(change), "700"),
            (format_pct(track), color_for(track), "700"),
        )
        for lab, (val, col, weight) in zip(self._value_labels, cells):
            lab.setText(val)
            lab.setStyleSheet("color:%s;font-size:14px;font-weight:%s;" % (col, weight))

    def retranslate_i18n(self) -> None:
        """إعادة ترجمة العناوين عند تبديل اللغة (القيم أرقام لا تُترجَم)."""
        self._apply_captions()

    # ---- مساعدات قراءة للاختبار/التفتيش ----
    def value_texts(self):
        return [l.text() for l in self._value_labels]

    def caption_texts(self):
        return [l.text() for _, l in self._caption_labels]
