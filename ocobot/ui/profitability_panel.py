# -*- coding: utf-8 -*-
"""لوحة الربحية الاحترافية (عرض فقط) — G1.54 / chunk_1.

مكوّن عرض صِرف يُغذَّى من الخارج بمُخرجات ``profitability_by_mode`` (G1.53) وقائمة
الصفقات المنتهية (``CompletedTrade``). لا شبكة، لا IO، لا منطق تنفيذ، لا hot_path.

البنية:
  - بطاقة لكل وضع خروج (``exit_source``): حلقة تقدّم لمعدّل الربح (win-rate) +
    متوسط العائد٪ + الصافي$ + التوقّع/صفقة + متوسط الانزلاق + عدد الصفقات.
  - ترتيب الأوضاع حسب التوقّع (leaderboard).
  - منحنى الربح/الخسارة التراكمي (QPainter) على كل الصفقات زمنيًّا.
  - شريط توزيع رابح/خاسر.
النقر على بطاقة وضع يُصدِر ``modeSelected(mode)`` للـdrill-down؛ زرّ «كل الأوضاع»
يُصدِر ``modeSelected("")`` لإلغاء الفلترة.

منطق التنسيق/الترتيب/السلسلة التراكمية/الهندسة دوالٌّ **خالصة** قابلة للاختبار بلا
``QApplication`` (نمط ``percent_tracker``)؛ الودجات طبقة رفيعة فوقها. RTL + ألوان
``PercentTracker`` (أخضر صعود/أحمر هبوط) + i18n (retranslate_i18n).
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from . import i18n
from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QFrame,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    Signal,
)
from .theme import PALETTE

# بدائل الرسم (معزولة هنا؛ لا تُحمَّل عبر الـshim) — binding-agnostic.
try:  # pragma: no cover - يعتمد على الـbinding المثبّت
    from PySide6.QtGui import QPainter, QPen, QColor
    from PySide6.QtCore import QRectF, QPointF
except Exception:  # pragma: no cover
    try:
        from PyQt6.QtGui import QPainter, QPen, QColor
        from PyQt6.QtCore import QRectF, QPointF
    except Exception:
        QPainter = QPen = QColor = QRectF = QPointF = None


# ---------------------------------------------------------------------------
# ثوابت العرض
# ---------------------------------------------------------------------------
MODE_ORDER_DEFAULT = (
    "MONITORING", "PRICE_BRACKET", "BTC_FOLLOW", "POSITION_SAFETY_NET", "MANUAL_EXIT",
)
# تسميات عربية للأوضاع (تُترجَم عبر i18n §1.5). الأوضاع غير المعروفة تُعرض كما هي.
MODE_LABELS_AR = {
    "MONITORING": "المراقبة الديناميكية",
    "PRICE_BRACKET": "قوس السعر",
    "BTC_FOLLOW": "تتبّع BTC",
    "POSITION_SAFETY_NET": "شبكة أمان المركز",
    "MANUAL_EXIT": "خروج يدوي",
}

ALL_MODES = "كل الأوضاع"
EMPTY_PROFIT = "لا بيانات ربحية بعد."
CAP_WIN_RATE = "معدّل الربح"
CAP_AVG_RETURN = "متوسط العائد"
CAP_NET = "الصافي"
CAP_EXPECTANCY = "التوقّع/صفقة"
CAP_SLIPPAGE = "متوسط الانزلاق"
CAP_COUNT = "عدد الصفقات"
HEAD_SUMMARY = "ملخّص الربحية"
HEAD_LEADERBOARD = "ترتيب الأوضاع (حسب التوقّع)"
HEAD_CURVE = "منحنى الربح/الخسارة التراكمي"
HEAD_DIST = "توزيع الصفقات"
LBL_WINS = "رابحة"
LBL_LOSSES = "خاسرة"

_Q2 = Decimal("0.01")
_DASH = "—"


def _c(key, fallback):
    return PALETTE.get(key, fallback)


# ---------------------------------------------------------------------------
# دوال خالصة (قابلة للاختبار بلا QApplication)
# ---------------------------------------------------------------------------
def _to_dec(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def fmt_pct(value) -> str:
    """نسبة مئوية بخانتين وإشارة؛ ``None`` ⇒ شرطة."""
    d = _to_dec(value)
    if d is None:
        return _DASH
    q = d.quantize(_Q2)
    sign = "+" if q > 0 else ""
    return "%s%s%%" % (sign, q)


def fmt_usd(value) -> str:
    """قيمة دولارية بخانتين وإشارة؛ ``None`` ⇒ شرطة. الرمز $ لاحق (محايد لغويًّا)."""
    d = _to_dec(value)
    if d is None:
        return _DASH
    q = d.quantize(_Q2)
    sign = "+" if q > 0 else ""
    return "%s%s $" % (sign, q)


def fmt_count(n) -> str:
    try:
        return str(int(n))
    except (TypeError, ValueError):
        return "0"


def win_rate_fraction(win_rate) -> float:
    """كسر 0..1 لحلقة التقدّم من نسبة مئوية (Decimal)؛ آمن ومحجوز في المدى."""
    d = _to_dec(win_rate)
    if d is None:
        return 0.0
    f = float(d) / 100.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def color_for(value) -> str:
    """أخضر (>0) / أحمر (<0) / محايد (0/None) من PALETTE."""
    d = _to_dec(value)
    if d is None or d == 0:
        return _c("MUTED", "#6f8ba2")
    return _c("GREEN", "#19c58b") if d > 0 else _c("RED", "#ff4b68")


def order_modes_by_expectancy(stats: Dict[str, Any]) -> List[str]:
    """ترتيب مفاتيح الأوضاع تنازليًّا بالتوقّع ثم الصافي (None آخرًا)."""
    def key(mode):
        s = stats[mode]
        exp = _to_dec(_get(s, "expectancy"))
        net = _to_dec(_get(s, "net_usd")) or Decimal(0)
        if exp is None:
            return (Decimal("-1E30"), net)
        return (exp, net)
    return sorted(stats.keys(), key=key, reverse=True)


def cumulative_pnl(trades) -> List[Decimal]:
    """سلسلة PnL تراكمية زمنيًّا (الأقدم أولًا) من ``profit_usd`` المتاح فقط.

    الـdomain يُعيد الصفقات الأحدث أولًا؛ نعكس لنبني منحنى يسار⇒يمين زمنيًّا.
    تُستبعَد الصفقة المفتوحة (status==live) والقيم الغائبة.
    """
    out: List[Decimal] = []
    cum = Decimal(0)
    for t in reversed(list(trades or [])):
        if str(_get(t, "status", "closed")) == "live":
            continue
        usd = _to_dec(_get(t, "profit_usd"))
        if usd is None:
            continue
        cum = cum + usd
        out.append(cum)
    return out


def win_loss_counts(trades, mode: Optional[str] = None) -> Tuple[int, int, int]:
    """(wins, losses, flats) على ``profit_pct`` (>0/<0/==0)، باستبعاد live/الغائب.

    عند تمرير ``mode`` تُحسب للوضع المطابق فقط.
    """
    wins = losses = flats = 0
    for t in trades or []:
        if str(_get(t, "status", "closed")) == "live":
            continue
        if mode is not None and (_get(t, "exit_source", "") or "") != mode:
            continue
        pct = _to_dec(_get(t, "profit_pct"))
        if pct is None:
            continue
        if pct > 0:
            wins += 1
        elif pct < 0:
            losses += 1
        else:
            flats += 1
    return (wins, losses, flats)


def polyline_points(series, width, height, pad=8.0) -> List[Tuple[float, float]]:
    """نقاط (x, y) بالبكسل لرسم ``series`` ضمن مستطيل width×height مع هامش pad.

    دالة **خالصة** (لا Qt). y مقلوب (أعلى = قيمة أكبر). سلسلة فارغة ⇒ [].
    """
    s = list(series or [])
    if not s:
        return []
    fl = [float(x) for x in s]
    w = float(width)
    h = float(height)
    p = float(pad)
    usable_w = max(1.0, w - 2 * p)
    usable_h = max(1.0, h - 2 * p)
    mn = min(fl)
    mx = max(fl)
    rng = (mx - mn) or 1.0
    n = len(fl)
    if n == 1:
        return [(p + usable_w / 2.0, (h - p) - (fl[0] - mn) / rng * usable_h)]
    pts = []
    for i, v in enumerate(fl):
        x = p + usable_w * (i / (n - 1))
        y = (h - p) - (v - mn) / rng * usable_h
        pts.append((x, y))
    return pts


def mode_label(mode: str) -> str:
    """تسمية الوضع المعروضة (مُترجَمة للغة الحالية)."""
    return i18n.translate_for_current(MODE_LABELS_AR.get(mode, mode))


# ---------------------------------------------------------------------------
# ودجات الرسم المخصّص (طبقة رفيعة؛ المنطق في الدوال الخالصة أعلاه)
# ---------------------------------------------------------------------------
class RingWidget(QWidget):
    """حلقة تقدّم دائرية لمعدّل الربح (عرض فقط)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self._color = _c("GREEN", "#19c58b")
        self.setMinimumSize(64, 64)

    def set_fraction(self, fraction: float, color: Optional[str] = None) -> None:
        try:
            self._fraction = max(0.0, min(1.0, float(fraction)))
        except (TypeError, ValueError):
            self._fraction = 0.0
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):  # pragma: no cover - رسم؛ المنطق في set_fraction
        if QPainter is None:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.rect()
            side = min(rect.width(), rect.height()) - 8
            if side <= 0:
                return
            x = (rect.width() - side) / 2.0
            y = (rect.height() - side) / 2.0
            arc_rect = QRectF(x, y, float(side), float(side))
            bg = QPen(QColor(_c("BORDER", "#2a3a4a")))
            bg.setWidth(7)
            painter.setPen(bg)
            painter.drawArc(arc_rect, 0, 360 * 16)
            fg = QPen(QColor(self._color))
            fg.setWidth(7)
            try:
                fg.setCapStyle(Qt.PenCapStyle.RoundCap)
            except AttributeError:
                pass
            painter.setPen(fg)
            painter.drawArc(arc_rect, 90 * 16, int(-360 * 16 * self._fraction))
        finally:
            painter.end()


class PnlCurveWidget(QWidget):
    """منحنى PnL تراكمي بسيط (عرض فقط)؛ أخضر إن ختم موجبًا وإلا أحمر."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series: List[Decimal] = []
        self.setMinimumHeight(90)

    def set_series(self, series) -> None:
        self._series = list(series or [])
        self.update()

    def paintEvent(self, event):  # pragma: no cover - رسم؛ المنطق في polyline_points
        if QPainter is None:
            return
        pts = polyline_points(self._series, self.width(), self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if len(pts) < 2:
                return
            up = self._series[-1] >= self._series[0]
            pen = QPen(QColor(_c("GREEN", "#19c58b") if up else _c("RED", "#ff4b68")))
            pen.setWidth(2)
            painter.setPen(pen)
            for i in range(1, len(pts)):
                x1, y1 = pts[i - 1]
                x2, y2 = pts[i]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        finally:
            painter.end()


class WinLossBar(QWidget):
    """شريط أفقي يقسّم رابح/خاسر بالنِّسب (عرض فقط)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wins = 0
        self._losses = 0
        self.setMinimumHeight(16)

    def set_counts(self, wins: int, losses: int) -> None:
        self._wins = max(0, int(wins))
        self._losses = max(0, int(losses))
        self.update()

    def paintEvent(self, event):  # pragma: no cover - رسم بسيط
        if QPainter is None:
            return
        painter = QPainter(self)
        try:
            total = self._wins + self._losses
            w = float(self.width())
            h = float(self.height())
            if total <= 0:
                painter.fillRect(QRectF(0, 0, w, h), QColor(_c("CARD_ALT", "#16222e")))
                return
            win_w = w * (self._wins / float(total))
            painter.fillRect(QRectF(0, 0, win_w, h), QColor(_c("GREEN", "#19c58b")))
            painter.fillRect(QRectF(win_w, 0, w - win_w, h), QColor(_c("RED", "#ff4b68")))
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# بطاقة وضع واحدة (قابلة للنقر)
# ---------------------------------------------------------------------------
class ModeCard(QFrame):
    """بطاقة مقاييس وضع خروج واحد (عرض فقط، قابلة للنقر لـdrill-down)."""

    clicked = Signal(str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("ProfitModeCard_%s" % mode)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._selected = False
        self._build()

    def _metric(self, caption_ar):
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        cap = QLabel(i18n.translate_for_current(caption_ar))
        cap.setStyleSheet("color:%s;font-size:11px;" % _c("MUTED", "#6f8ba2"))
        val = QLabel(_DASH)
        val.setStyleSheet("color:%s;font-size:14px;font-weight:700;" % _c("TEXT", "#f0f7fb"))
        box.addWidget(cap)
        box.addWidget(val)
        self._captions.append((caption_ar, cap))
        return box, val

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self._captions = []

        self.title = QLabel(mode_label(self.mode))
        self.title.setObjectName("ProfitModeTitle")
        self.title.setStyleSheet("color:%s;font-size:15px;font-weight:800;" % _c("TEXT", "#f0f7fb"))
        root.addWidget(self.title)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.ring = RingWidget()
        top.addWidget(self.ring)
        wr_box = QVBoxLayout()
        wr_cap = QLabel(i18n.translate_for_current(CAP_WIN_RATE))
        wr_cap.setStyleSheet("color:%s;font-size:11px;" % _c("MUTED", "#6f8ba2"))
        self.win_rate_val = QLabel(_DASH)
        self.win_rate_val.setStyleSheet("color:%s;font-size:16px;font-weight:800;" % _c("TEXT", "#f0f7fb"))
        wr_box.addWidget(wr_cap)
        wr_box.addWidget(self.win_rate_val)
        self._captions.append((CAP_WIN_RATE, wr_cap))
        top.addLayout(wr_box)
        top.addStretch(1)
        root.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        b1, self.avg_return_val = self._metric(CAP_AVG_RETURN)
        b2, self.net_val = self._metric(CAP_NET)
        b3, self.expectancy_val = self._metric(CAP_EXPECTANCY)
        b4, self.slippage_val = self._metric(CAP_SLIPPAGE)
        b5, self.count_val = self._metric(CAP_COUNT)
        grid.addLayout(b1, 0, 0)
        grid.addLayout(b2, 0, 1)
        grid.addLayout(b3, 1, 0)
        grid.addLayout(b4, 1, 1)
        grid.addLayout(b5, 2, 0)
        root.addLayout(grid)

        self._apply_style()

    def _apply_style(self):
        border = _c("GREEN", "#19c58b") if self._selected else _c("BORDER", "#2a3a4a")
        self.setStyleSheet(
            "QFrame#%s{background:%s;border:1px solid %s;border-radius:12px;}"
            % (self.objectName(), _c("CARD", "#101a24"), border)
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def set_stats(self, stats) -> None:
        """يملأ قيم البطاقة من ``ModeProfitability`` (أو dict مكافئ)."""
        win_rate = _get(stats, "win_rate")
        self.win_rate_val.setText(fmt_pct(win_rate))
        self.ring.set_fraction(win_rate_fraction(win_rate), color_for(win_rate))
        avg = _get(stats, "avg_return_pct")
        self.avg_return_val.setText(fmt_pct(avg))
        self.avg_return_val.setStyleSheet(
            "color:%s;font-size:14px;font-weight:700;" % color_for(avg))
        net = _get(stats, "net_usd")
        self.net_val.setText(fmt_usd(net))
        self.net_val.setStyleSheet(
            "color:%s;font-size:14px;font-weight:700;" % color_for(net))
        exp = _get(stats, "expectancy")
        self.expectancy_val.setText(fmt_usd(exp))
        self.expectancy_val.setStyleSheet(
            "color:%s;font-size:14px;font-weight:700;" % color_for(exp))
        self.slippage_val.setText(fmt_pct(_get(stats, "avg_slippage_pct")))
        self.count_val.setText(fmt_count(_get(stats, "n", 0)))

    def retranslate_i18n(self) -> None:
        self.title.setText(mode_label(self.mode))
        for caption_ar, lab in self._captions:
            lab.setText(i18n.translate_for_current(caption_ar))

    def mousePressEvent(self, event):  # pragma: no cover - تفاعل نقر
        self.clicked.emit(self.mode)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# اللوحة الجامعة
# ---------------------------------------------------------------------------
class ProfitabilityPanel(QWidget):
    """لوحة الربحية الاحترافية (عرض فقط) — بطاقات + leaderboard + منحنى + توزيع.

    ``modeSelected`` تُصدَر عند النقر على بطاقة وضع (mode) أو زرّ «كل الأوضاع» ("").
    التغذية عبر ``set_data(stats, trades)`` حيث ``stats`` خريطة وضع⇒ModeProfitability.
    """

    modeSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProfitabilityPanel")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._stats: Dict[str, Any] = {}
        self._trades: List[Any] = []
        self._active_mode = ""  # "" = الكل
        self._cards: Dict[str, ModeCard] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        head_row = QHBoxLayout()
        self.heading = QLabel(i18n.translate_for_current(HEAD_SUMMARY))
        self.heading.setObjectName("ProfitSummaryHeading")
        self.heading.setStyleSheet("color:%s;font-size:16px;font-weight:700;" % _c("TEXT", "#f0f7fb"))
        head_row.addWidget(self.heading)
        head_row.addStretch(1)
        self.all_button = QPushButton(i18n.translate_for_current(ALL_MODES))
        self.all_button.setObjectName("ProfitAllModesButton")
        self.all_button.clicked.connect(lambda: self._on_select(""))
        head_row.addWidget(self.all_button)
        root.addLayout(head_row)

        # رسالة فارغة.
        self.empty_note = QLabel(i18n.translate_for_current(EMPTY_PROFIT))
        self.empty_note.setStyleSheet(
            "color:%s;font-size:13px;background:%s;border:1px solid %s;border-radius:10px;"
            "padding:10px 14px;" % (_c("TEXT_SOFT", "#9fb3c6"), _c("CARD_ALT", "#16222e"), _c("BORDER", "#2a3a4a")))
        root.addWidget(self.empty_note)

        # حاوية البطاقات.
        self.cards_row = QHBoxLayout()
        self.cards_row.setSpacing(10)
        cards_host = QWidget()
        cards_host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        cards_host.setLayout(self.cards_row)
        root.addWidget(cards_host)

        # leaderboard + منحنى + توزيع في صفّ سفلي.
        bottom = QHBoxLayout()
        bottom.setSpacing(14)

        lb_box = QVBoxLayout()
        self.lb_head = QLabel(i18n.translate_for_current(HEAD_LEADERBOARD))
        self.lb_head.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % _c("MUTED", "#6f8ba2"))
        lb_box.addWidget(self.lb_head)
        self.leaderboard = QLabel("")
        self.leaderboard.setObjectName("ProfitLeaderboard")
        self.leaderboard.setStyleSheet("color:%s;font-size:13px;" % _c("TEXT", "#f0f7fb"))
        self.leaderboard.setWordWrap(True)
        lb_box.addWidget(self.leaderboard)
        lb_box.addStretch(1)
        bottom.addLayout(lb_box, 1)

        curve_box = QVBoxLayout()
        self.curve_head = QLabel(i18n.translate_for_current(HEAD_CURVE))
        self.curve_head.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % _c("MUTED", "#6f8ba2"))
        curve_box.addWidget(self.curve_head)
        self.curve = PnlCurveWidget()
        curve_box.addWidget(self.curve)
        bottom.addLayout(curve_box, 2)

        dist_box = QVBoxLayout()
        self.dist_head = QLabel(i18n.translate_for_current(HEAD_DIST))
        self.dist_head.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % _c("MUTED", "#6f8ba2"))
        dist_box.addWidget(self.dist_head)
        self.dist_bar = WinLossBar()
        dist_box.addWidget(self.dist_bar)
        self.dist_label = QLabel("")
        self.dist_label.setObjectName("ProfitDistLabel")
        self.dist_label.setStyleSheet("color:%s;font-size:12px;" % _c("TEXT_SOFT", "#9fb3c6"))
        dist_box.addWidget(self.dist_label)
        dist_box.addStretch(1)
        bottom.addLayout(dist_box, 1)

        root.addLayout(bottom)

    # ------------------------------------------------------------------
    def _on_select(self, mode: str) -> None:
        self._active_mode = mode or ""
        for m, card in self._cards.items():
            card.set_selected(m == self._active_mode)
        self.modeSelected.emit(self._active_mode)

    def active_mode(self) -> str:
        return self._active_mode

    def card_modes(self) -> List[str]:
        """ترتيب الأوضاع المعروضة حاليًّا (للاختبار)."""
        return [self.cards_row.itemAt(i).widget().mode
                for i in range(self.cards_row.count())
                if self.cards_row.itemAt(i).widget() is not None]

    def set_data(self, stats: Dict[str, Any], trades=None) -> None:
        """يُعيد بناء اللوحة من خريطة الأوضاع + قائمة الصفقات (عرض فقط)."""
        self._stats = dict(stats or {})
        self._trades = list(trades or [])

        is_empty = not self._stats
        self.empty_note.setVisible(is_empty)

        # ترتيب الأوضاع بالتوقّع (leaderboard order يحكم ترتيب البطاقات أيضًا).
        ordered = order_modes_by_expectancy(self._stats) if self._stats else []

        # إعادة بناء البطاقات.
        self._clear_cards()
        for mode in ordered:
            card = ModeCard(mode)
            card.set_stats(self._stats[mode])
            card.set_selected(mode == self._active_mode)
            card.clicked.connect(self._on_select)
            self.cards_row.addWidget(card)
            self._cards[mode] = card

        # leaderboard نصّي.
        lines = []
        for rank, mode in enumerate(ordered, start=1):
            s = self._stats[mode]
            lines.append("%d. %s — %s" % (rank, mode_label(mode), fmt_usd(_get(s, "expectancy"))))
        self.leaderboard.setText("\n".join(lines))

        # منحنى + توزيع (عالميًّا على كل الصفقات).
        self.curve.set_series(cumulative_pnl(self._trades))
        wins, losses, _flats = win_loss_counts(self._trades)
        self.dist_bar.set_counts(wins, losses)
        self.dist_label.setText(
            "%s: %d  ·  %s: %d"
            % (i18n.translate_for_current(LBL_WINS), wins,
               i18n.translate_for_current(LBL_LOSSES), losses))

    def _clear_cards(self) -> None:
        for m, card in list(self._cards.items()):
            self.cards_row.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = {}

    def retranslate_i18n(self) -> None:
        """إعادة ترجمة النصوص الثابتة وإعادة الرسم من البيانات المخزّنة."""
        self.heading.setText(i18n.translate_for_current(HEAD_SUMMARY))
        self.all_button.setText(i18n.translate_for_current(ALL_MODES))
        self.empty_note.setText(i18n.translate_for_current(EMPTY_PROFIT))
        self.lb_head.setText(i18n.translate_for_current(HEAD_LEADERBOARD))
        self.curve_head.setText(i18n.translate_for_current(HEAD_CURVE))
        self.dist_head.setText(i18n.translate_for_current(HEAD_DIST))
        # إعادة البناء تُترجم تسميات الأوضاع/الكابشنات والـleaderboard والتوزيع.
        self.set_data(self._stats, self._trades)
