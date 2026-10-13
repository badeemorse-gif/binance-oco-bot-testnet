"""شاشة وضع العرض (Demo Mode) — T14 (M-UI/4).

عرضٌ آمنٌ تمامًا داخل الواجهة يُحاكي حركة السعر ودورة إعادة التموضع بلا أي
كتابة حقيقية على Binance. يلتزم مبادئ التصميم كأشقّائه (monitoring.py):

  - محاكاة فقط (D14 بالمعنى المعاكس): السعر هنا *مُصطنَع صراحةً* عبر مولّد داخلي
    ``DemoSimulator`` — ووَسْم البيئة يقرأ "DEMO" صراحةً كي لا يُوهم أنه Live.
  - لا كتابة حقيقية إطلاقًا: لا عميل صرف، لا إنشاء/تنفيذ أوامر، لا شبكة، لا
    مُنفِّذ حقيقي ولا مسار كتابة حيّ، لا persistence/audit — كل شيء في الذاكرة (يفرضه
    tests/test_ui_no_direct_network.py + اختبارات T14).
  - لا شبكة/IO داخل طبقة الواجهة: المحاكي نقيّ وحتميّ (بذرة/تسلسل أسعار محقون).
  - RTL + ثيم داكن عبر PALETTE (D15)؛ class تضبط self.screen_key و
    setObjectName("Screen_<key>")؛ دوال ``_build_*`` لبناء البطاقات.

المحاكي ``DemoSimulator``: مولّد سعر متحرّك نقيّ في الذاكرة (random-walk مبذور /
مذبذب) يتقدّم عبر ``tick()`` و/أو ``QTimer``؛ لا كتابة حقيقية بأي شكل.
"""
import random
from decimal import Decimal, InvalidOperation

from ._qt import (
    Qt,
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QTimer,
)
from ocobot.domain.models import fmt
from ocobot.domain.pricing import compute_levels
from .theme import PALETTE
from . import i18n

EMPTY = "—"

# وسم البيئة يقرأ DEMO صراحةً (لا Live) — التصميم D14.
DEMO_ENVIRONMENT = "DEMO"
DEMO_BADGE_TEXT = "وضع DEMO — محاكاة، لا كتابة حقيقية على Binance"

# حقول لوحة النِّسب الثلاثة (كأشقّائه): مفتاح، عنوان.
PCT_FIELDS = [
    ("trigger_pct", "نسبة ارتفاع مُشغِّل إعادة التموضع %"),
    ("tp_pct", "نسبة بُعد جني الأرباح فوق الحالي %"),
    ("sl_pct", "نسبة بُعد وقف الخسارة تحت الحالي %"),
]

# حقول اللوحة الحيّة (المحاكاة) بالترتيب.
LIVE_FIELDS = [
    ("symbol", "الرمز"),
    ("current_price", "السعر الحالي"),
    ("reference_price", "السعر المرجعي"),
    ("trigger_price", "سعر التفعيل"),
    ("next_tp", "جني الأرباح التالي"),
    ("next_sl", "وقف الخسارة التالي"),
    ("sl_limit", "حد وقف الخسارة"),
    ("tick_size", "حجم الخطوة السعرية"),
    ("phase", "الطور"),
    ("last_operation", "آخر عملية محاكاة"),
    ("environment", "البيئة"),
]

# مراحل دورة العرض (Select→Set rules→Start→Price moves→Trigger→Reposition→…).
PHASE_IDLE = "IDLE"
PHASE_MONITORING = "MONITORING"
PHASE_TRIGGERED = "TRIGGERED"
PHASE_REPOSITIONED = "REPOSITIONED"

_PHASE_ACCENT = {
    PHASE_IDLE: "MUTED",
    PHASE_MONITORING: "GREEN",
    PHASE_TRIGGERED: "BLUE",
    PHASE_REPOSITIONED: "TEAL",
}

_HUNDRED = Decimal("100")


class DemoSimulator:
    """مولّد سعر متحرّك نقيّ في الذاكرة — حتميّ، بلا أي كتابة حقيقية.

    لا شبكة ولا عميل صرف ولا مُنفِّذ حقيقي ولا persistence: مجرّد random-walk
    مبذور حول سعر أساس، أو تسلسل أسعار محقون صريح (للاختبارات الحتمية).

    - ``seed``: بذرة random لجعل المسار حتميًّا.
    - ``prices``: تسلسل أسعار محقون صريح (يتجاوز الـ random-walk تمامًا).
    - ``start``/``step``/``volatility``: معطيات الـ random-walk.
    """

    def __init__(self, start="60000.00", step="25.00", volatility="0.004",
                 seed=1337, prices=None):
        self._base = Decimal(str(start))
        self._step = Decimal(str(step))
        self._volatility = Decimal(str(volatility))
        self._rng = random.Random(seed)
        self._injected = (
            [Decimal(str(p)) for p in prices] if prices is not None else None
        )
        self._idx = 0
        self.price = self._base  # آخر سعر مُحاكى (لا كتابة حقيقية)

    def tick(self):
        """يتقدّم خطوة واحدة ويُرجع السعر المُحاكى الجديد (في الذاكرة فقط)."""
        if self._injected is not None:
            # تسلسل محقون صريح — حتميّ تمامًا للاختبارات.
            value = self._injected[min(self._idx, len(self._injected) - 1)]
            self._idx += 1
            self.price = value
            return self.price
        # random-walk مبذور: تذبذب صعودًا/هبوطًا حول آخر سعر (حتميّ بالبذرة).
        direction = 1 if self._rng.random() >= 0.5 else -1
        magnitude = self._rng.random()  # 0..1
        delta = self._step * Decimal(str(round(magnitude, 6))) * Decimal(direction)
        drift = self.price * self._volatility * Decimal(direction)
        self.price = (self.price + delta + drift)
        self._idx += 1
        return self.price

    def reset(self):
        """يعيد المحاكي لحالته الابتدائية (في الذاكرة فقط)."""
        self.price = self._base
        self._idx = 0


class DemoModeScreen(QWidget):
    """شاشة وضع العرض — محاكاة حركة السعر ودورة إعادة التموضع بلا كتابة حقيقية.

    الحقن (كأشقّائه): ``simulator`` (DemoSimulator محقون أو يُنشأ افتراضيًّا)،
    ``symbol`` و``tick_size`` للعرض فقط. لا engine/executor/شبكة إطلاقًا.
    """

    def __init__(self, parent=None, simulator=None, symbol="BTCUSDT",
                 tick_size=Decimal("0.01")):
        super().__init__(parent)
        self.screen_key = "06_demo"
        self.setObjectName("Screen_06_demo")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        # محاكي داخلي نقيّ (لا كتابة حقيقية). قابل للحقن للاختبارات الحتمية.
        self._simulator = simulator or DemoSimulator()
        self._symbol = symbol
        self._tick_size = tick_size if isinstance(tick_size, Decimal) else Decimal(str(tick_size))
        self._phase = PHASE_IDLE
        self._reference_price = None      # يُثبَّت عند بدء العرض
        self._current_price = None        # آخر سعر مُحاكى معروض
        self._last_operation = EMPTY
        self._pct_edits = {}
        self._live = {}

        # مؤقّت التشغيل التلقائي (محاكاة فقط — لا IO). يُنشأ لكن لا يبدأ إلا بطلب.
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.advance)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة.
        self.heading = QLabel("وضع العرض (Demo)", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        self._build_badge(root)          # شارة DEMO بارزة
        self._build_rules_section(root)  # 3 حقول نِسب + أزرار المحاكاة
        self._build_live_panel(root)     # اللوحة الحيّة (المحاكاة)

        root.addStretch(1)

        self._refresh_live_panel()

    # ---- بناء الأقسام ----
    def _build_badge(self, root):
        """شارة DEMO بارزة بلون accent مميّز عن Live (لا يُوهم أنه حقيقي)."""
        badge = QLabel(DEMO_BADGE_TEXT, self)
        badge.setObjectName("DemoBadge")
        badge.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        badge.setStyleSheet(
            "QLabel#DemoBadge{background:%s;color:%s;border:1px solid %s;"
            "border-radius:8px;padding:8px 14px;font-size:14px;font-weight:700;}"
            % (PALETTE["AMBER"], PALETTE["BG"], PALETTE["AMBER"])
        )
        self.badge = badge
        root.addWidget(badge)

    def _build_rules_section(self, root):
        """3 حقول نِسب + أزرار: بدء العرض · خطوة · تشغيل/إيقاف تلقائي."""
        card = QFrame(self)
        card.setObjectName("DemoRulesCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#DemoRulesCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        heading = QLabel("قواعد العرض (محاكاة)", card)
        heading.setObjectName("DemoRulesHeading")
        heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(heading)

        pct_row = QHBoxLayout()
        pct_row.setSpacing(12)
        for key, label in PCT_FIELDS:
            col = QVBoxLayout()
            col.setSpacing(4)
            caption = QLabel(label, card)
            caption.setObjectName("DemoPctLabel_%s" % key)
            caption.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
            edit = QLineEdit(card)
            edit.setObjectName("DemoPctEdit_%s" % key)
            edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            edit.setStyleSheet(
                "background:%s;color:%s;border:1px solid %s;border-radius:6px;"
                "padding:6px 10px;"
                % (PALETTE["CARD"], PALETTE["TEXT"], PALETTE["BORDER"])
            )
            edit.textChanged.connect(self._refresh_live_panel)
            self._pct_edits[key] = edit
            col.addWidget(caption)
            col.addWidget(edit)
            pct_row.addLayout(col, 1)
        lay.addLayout(pct_row)

        # أزرار المحاكاة.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.start_button = QPushButton("بدء العرض", card)
        self.start_button.setObjectName("DemoStartButton")
        self.start_button.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_button)

        self.step_button = QPushButton("خطوة", card)
        self.step_button.setObjectName("DemoStepButton")
        self.step_button.clicked.connect(self.advance)
        btn_row.addWidget(self.step_button)

        self.auto_button = QPushButton("تشغيل تلقائي", card)
        self.auto_button.setObjectName("DemoAutoButton")
        self.auto_button.setCheckable(True)
        self.auto_button.toggled.connect(self._on_auto_toggled)
        btn_row.addWidget(self.auto_button)

        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        root.addWidget(card)

    def _build_live_panel(self, root):
        """اللوحة الحيّة للمحاكاة — كل الحقول ظاهرة دائمًا."""
        card = QFrame(self)
        card.setObjectName("DemoLiveCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#DemoLiveCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        title = QLabel("اللوحة الحيّة (محاكاة)", card)
        title.setObjectName("DemoLiveTitle")
        title.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(title)

        for key, label in LIVE_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(12)
            caption = QLabel(label, card)
            caption.setObjectName("DemoLiveCaption_%s" % key)
            caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
            value = QLabel(EMPTY, card)
            value.setObjectName("DemoLiveValue_%s" % key)
            value.setStyleSheet(
                "color:%s;font-size:16px;font-weight:600;" % PALETTE["TEXT"]
            )
            self._live[key] = value
            row.addWidget(caption)
            row.addStretch(1)
            row.addWidget(value)
            lay.addLayout(row)

        root.addWidget(card)

    # ---- أزرار المحاكاة ----
    def _on_start_clicked(self, *args):
        """يبدأ العرض: يثبّت السعر المرجعي من المحاكي وينتقل لمرحلة المراقبة."""
        self._reference_price = self._simulator.price
        self._current_price = self._simulator.price
        self._phase = PHASE_MONITORING
        self._set_last_operation(i18n.translate_for_current("بدء العرض"), i18n.translate_for_current("محاكاة نشطة (لا كتابة حقيقية)"))
        self._refresh_live_panel()

    def _on_auto_toggled(self, checked):
        """يشغّل/يوقف المؤقّت (محاكاة فقط) — لا IO."""
        self.auto_button.setText(
            i18n.translate_for_current("إيقاف تلقائي") if checked
            else i18n.translate_for_current("تشغيل تلقائي")
        )
        if checked:
            self._timer.start()
        else:
            self._timer.stop()

    def advance(self, *args):
        """يتقدّم خطوة محاكاة واحدة: يحرّك السعر ويحدّث المرحلة (لا كتابة حقيقية)."""
        self._current_price = self._simulator.tick()
        if self._reference_price is None:
            self._reference_price = self._current_price
        self._advance_phase()
        self._refresh_live_panel()

    def _advance_phase(self):
        """آلة حالات محاكاة: المراقبة → تجاوز التفعيل → إعادة تموضع (محاكاة)."""
        if self._phase == PHASE_IDLE:
            return
        trigger = self._trigger_price()
        if trigger is None or self._current_price is None:
            return
        if self._phase == PHASE_MONITORING and self._current_price >= trigger:
            self._phase = PHASE_TRIGGERED
            self._set_last_operation(i18n.translate_for_current("محاكاة تفعيل"), i18n.translate_for_current("تجاوز مستوى التفعيل"))
        elif self._phase == PHASE_TRIGGERED:
            # إعادة تموضع محاكاة: يُثبَّت مرجع جديد على السعر الحالي (لا أمر حقيقي).
            self._reference_price = self._current_price
            self._phase = PHASE_REPOSITIONED
            self._set_last_operation(i18n.translate_for_current("محاكاة إعادة تموضع"), i18n.translate_for_current("مرجع جديد (بلا أمر حقيقي)"))
        elif self._phase == PHASE_REPOSITIONED:
            self._phase = PHASE_MONITORING

    # ---- مساعدات الحساب النقيّ ----
    def _trigger_price(self):
        """مستوى التفعيل = reference * (1 + trigger%/100) — حساب نقيّ (لا شبكة)."""
        reference = self._reference_price
        if reference is None:
            return None
        trigger_text = self._pct_edits["trigger_pct"].text().strip()
        if not trigger_text:
            return None
        try:
            ref = reference if isinstance(reference, Decimal) else Decimal(str(reference))
            pct = Decimal(str(trigger_text))
            return ref * (Decimal("1") + pct / _HUNDRED)
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            return None

    def _computed_levels(self):
        """يحسب (next_tp, next_trigger, next_sl_limit) عبر pricing.compute_levels."""
        reference = self._reference_price
        if reference is None:
            return None
        tp_text = self._pct_edits["tp_pct"].text().strip()
        sl_text = self._pct_edits["sl_pct"].text().strip()
        if not tp_text or not sl_text:
            return None
        try:
            return compute_levels(reference, tp_text, sl_text, self._tick_size)
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            return None

    def _set_last_operation(self, operation, result):
        self._last_operation = "%s — %s" % (operation, result) if result else operation

    # ---- اللوحة الحيّة ----
    def _refresh_live_panel(self, *args):
        """يعيد ملء اللوحة الحيّة كاملةً (محاكاة) — كل الحقول تبقى ظاهرة دائمًا."""
        if not self._live:
            return
        levels = self._computed_levels()
        trigger_price = self._trigger_price()

        values = {
            "symbol": self._symbol or EMPTY,
            "current_price": fmt(self._current_price) if self._current_price is not None else EMPTY,
            "reference_price": fmt(self._reference_price) if self._reference_price is not None else EMPTY,
            "trigger_price": fmt(trigger_price) if trigger_price is not None else EMPTY,
            "next_tp": fmt(levels[0]) if levels else EMPTY,
            "next_sl": fmt(levels[1]) if levels else EMPTY,
            "sl_limit": fmt(levels[2]) if levels else EMPTY,
            "tick_size": fmt(self._tick_size) if self._tick_size is not None else EMPTY,
            "phase": self._phase,
            "last_operation": self._last_operation or EMPTY,
            # وسم البيئة يقرأ DEMO صراحةً — لا يُوهم أنه Live (D14).
            "environment": DEMO_ENVIRONMENT,
        }
        for key, label in self._live.items():
            val = values.get(key)
            label.setText(EMPTY if val in (None, "") else str(val))

        # تلوين المرحلة (D15).
        accent = PALETTE.get(_PHASE_ACCENT.get(self._phase, "TEXT"), PALETTE["TEXT"])
        self._live["phase"].setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % accent
        )


__all__ = [
    "DemoSimulator",
    "DemoModeScreen",
    "LIVE_FIELDS",
    "PCT_FIELDS",
    "EMPTY",
    "DEMO_ENVIRONMENT",
]
