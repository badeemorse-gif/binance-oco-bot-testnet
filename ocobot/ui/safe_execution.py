"""شاشة "التنفيذ الآمن" (Safe Execution) — عرض فقط، بلا شبكة (تصميم §3.6 F).

تعرض تقدّم إعادة التموضع الذرّي عبر ستبر من **سبع خطوات** بترتيب RTL صارم،
مع مفتاح حالات، وإبراز "النافذة العارية" أثناء الخطوتين ⑤–⑥، وبطاقة
FAILED_NEEDS_ATTENTION التي تُوضّح غياب إعادة المحاولة التلقائية عند
(Cancel ✓ · Create ✗).

لا IO ولا شبكة إطلاقًا هنا: الشاشة تعرض فقط ``ExecutionResult`` (من
``ocobot.domain.reposition``) الذي يُمرَّر إليها عبر ``show_result``. المُنشئ
متسامح (``parent=None, **kwargs``) كي يبنيه ContentRouter بلا أي خدمات.
RTL + ثيم داكن عبر PALETTE (D15)، بنفس أسلوب ``open_orders.py``/``selected_oco.py``.
"""
from ._qt import (
    Qt,
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
)
from .theme import PALETTE
from . import i18n

# نصّ شارة "النافذة العارية" — نستورده من selected_oco إن أمكن (مصدر واحد للحقيقة)،
# وإلا نُكرّر السلسلة العربية حرفيًا (نفس القيمة تمامًا).
try:  # pragma: no cover - مسار الاستيراد النظيف
    from .selected_oco import NAKED_WINDOW_TEXT
except Exception:  # pragma: no cover - fallback بلا اقتران صلب
    NAKED_WINDOW_TEXT = "⚠️ نافذة عارية: المركز بلا حماية أثناء الإلغاء ثم الإنشاء"

EMPTY = "—"

# ---------------------------------------------------------------------------
# G1.47 — بوّابة التنفيذ الآمن للخروج اليدوي الفوري (خالصة، بلا Qt/شبكة/أثر جانبي).
# تُعيد استخدام قيد منع البيع المزدوج البنيوي نفسه المستعمَل في domain/guardian.py:
#   (1) has_resting_protective_sell ⇒ منع (لا بيع ثانٍ أبدًا).
#   (2) protective_qty = min(free_base_qty, monitored_qty)؛ إن ≤ 0 ⇒ منع.
# نتيجة ناطقة {allowed, reason, protective_qty} يستهلكها ocobot/ui/manual_exit.py
# قبل استدعاء مسار الخروج المُختبَر execute_market_exit. لا Live قبل G1 (§10.5).
# ---------------------------------------------------------------------------
MANUAL_EXIT_GATE_OK = "OK"
MANUAL_EXIT_GATE_RESTING = "resting_protective_sell"
MANUAL_EXIT_GATE_NO_FREE = "no_free_protectable_qty"


def manual_exit_safety_gate(*, has_resting_protective_sell, free_base_qty, monitored_qty):
    """بوّابة أمان خالصة للخروج اليدوي (G1.47) — بلا أثر جانبي ولا شبكة.

    تطبّق قيد منع البيع المزدوج البنيوي قبل أي تنفيذ:
      - بيع حمائي قائم ⇒ ``allowed=False`` (``resting_protective_sell``).
      - ``protective_qty = min(free_base_qty, monitored_qty)``؛ إن ``<= 0`` ⇒
        ``allowed=False`` (``no_free_protectable_qty``) — الرصيد مقفول أو لا مركز.
      - غير ذلك ⇒ ``allowed=True`` بكمية الحماية المحسوبة.
    """
    from decimal import Decimal

    def _dec(v):
        return v if isinstance(v, Decimal) else Decimal(str(v))

    zero = Decimal("0")
    if has_resting_protective_sell:
        return {"allowed": False, "reason": MANUAL_EXIT_GATE_RESTING, "protective_qty": zero}
    qty = min(_dec(free_base_qty), _dec(monitored_qty))
    if qty <= zero:
        return {"allowed": False, "reason": MANUAL_EXIT_GATE_NO_FREE, "protective_qty": zero}
    return {"allowed": True, "reason": MANUAL_EXIT_GATE_OK, "protective_qty": qty}

# حالات النتيجة النهائية (سلاسل — لتجنّب استيراد ExecutionState وإبقاء الاقتران منخفضًا،
# تطابق ExecutionState.* قيمةً في ocobot/domain/reposition.py).
_STATE_SUCCESS = "SUCCESS"
_STATE_ABORTED = "ABORTED"
_STATE_FAILED = "FAILED_NEEDS_ATTENTION"

# الخطوات السبع الذرّية بترتيب RTL الصارم (تصميم §3.6 F).
# (key, label) — المفاتيح تطابق SafeExecutor.execute() في domain/reposition.py:
#   verify · price · recalc · gate · cancel · create · confirm
STEPS = [
    ("verify", "① إعادة التحقق من الأمر المحدد"),
    ("price", "② جلب أحدث سعر صالح + الكمية المتبقية"),
    ("recalc", "③ إعادة حساب المستويات (tick/step + ترتيب صارم)"),
    ("gate", "④ 🛡️ بوابة تحقّق مسبق قبل الإلغاء (Pre-Cancel Validation Gate)"),
    ("cancel", "⑤ إلغاء الأمر المحدد فقط"),
    ("create", "⑥ إنشاء الأمر البديل"),
    ("confirm", "⑦ تأكيد orderListId الجديد"),
]

# الخطوتان اللتان تفتحان "النافذة العارية" (بين الإلغاء والإنشاء).
_NAKED_STEPS = ("cancel", "create")

# علامات/ألوان حالة كل خطوة على الشاشة.
_STATUS_MARKERS = {
    "done": ("✓", "GREEN"),
    "current": ("◉", "BLUE"),
    "wait": ("○", "MUTED"),
    "failed": ("✗", "RED"),
    "aborted": ("⊘", "AMBER"),
}

# ترجمة حالة الخطوة القادمة من المحرّك (ExecutionStep.status) إلى علامة الشاشة.
# ملاحظة: "skipped" تُترجَم لاحقًا حسب الحالة النهائية (aborted مقابل wait).
_ENGINE_STATUS_MAP = {
    "done": "done",
    "failed": "failed",
    "pending": "wait",
    "naked": "current",
}

# مفتاح الحالات (مفتاح الحالات) — مطلوب سرده كاملًا (تصميم §3.6 F).
_LEGEND = [
    ("Connected", "متصل", "GREEN"),
    ("Selected", "أمر محدَّد", "BLUE"),
    ("Monitoring Active", "المراقبة نشطة", "TEAL"),
    ("Triggered", "مُفعَّل", "AMBER"),
    ("Repositioning", "إعادة تموضع", "BLUE"),
    ("Success", "نجاح", "GREEN"),
    ("Aborted", "أُلغي", "AMBER"),
    ("FAILED_NEEDS_ATTENTION", "فشل — تدخّل يدوي", "RED"),
]

# نصّ بطاقة الفشل الحرفي (No Blind Retry).
FAILURE_HEADLINE = (
    "FAILED_NEEDS_ATTENTION — يتطلب تدخّلًا يدويًا. لا توجد إعادة محاولة تلقائية."
)


def _state_name(result):
    """يستخرج اسم الحالة كسلسلة سواء كانت Enum أو نصًّا (نفس نمط selected_oco)."""
    state = getattr(result, "state", None)
    return getattr(state, "value", None) or getattr(state, "name", None) or state


class _StepRow(QFrame):
    """صف خطوة واحد: علامة الحالة + عنوان الخطوة + تفصيل اختياري."""

    def __init__(self, key, label, parent=None):
        super().__init__(parent)
        self.step_key = key
        self.setObjectName("SafeExecStepRow_%s" % key)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)

        self._marker = QLabel(EMPTY, self)
        self._marker.setObjectName("SafeExecStepMarker_%s" % key)
        self._marker.setMinimumWidth(24)

        self._label = QLabel(label, self)
        self._label.setObjectName("SafeExecStepLabel_%s" % key)
        self._label.setWordWrap(True)

        self._detail = QLabel(EMPTY, self)
        self._detail.setObjectName("SafeExecStepDetail_%s" % key)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
        self._detail.setVisible(False)

        row.addWidget(self._marker)
        row.addWidget(self._label, 1)
        row.addWidget(self._detail, 1)

        self._naked = False
        self.set_status("wait")

    def set_naked(self, naked):
        """يعلّم هذا الصف كجزء من النافذة العارية (للإبراز البصري لاحقًا)."""
        self._naked = bool(naked)

    def set_status(self, status, detail=None):
        """يضبط علامة/لون الصف حسب الحالة (done/current/wait/failed/aborted)."""
        marker, color_key = _STATUS_MARKERS.get(status, _STATUS_MARKERS["wait"])
        self.status = status
        self._marker.setText(marker)
        self._marker.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % PALETTE[color_key]
        )
        # إبراز الصف الجاري (والخطوات العارية الجارية) ببطاقة مميّزة.
        highlight = status in ("current", "failed")
        naked_active = self._naked and status in ("current", "wait")
        border = PALETTE["AMBER"] if (naked_active or status == "failed") else PALETTE["BORDER"]
        bg = PALETTE["CARD_ALT"] if (highlight or naked_active) else PALETTE["CARD"]
        self.setStyleSheet(
            "QFrame#SafeExecStepRow_%s{background:%s;border:1px solid %s;"
            "border-radius:8px;}" % (self.step_key, bg, border)
        )
        # عنوان الخطوة: أبرزها لونيًّا حين تكون جارية/فاشلة.
        label_color = PALETTE["TEXT"] if status in ("current", "failed", "done") else PALETTE["TEXT_SOFT"]
        weight = 700 if status in ("current", "failed") else 600
        self._label.setStyleSheet(
            "color:%s;font-size:14px;font-weight:%d;" % (label_color, weight)
        )
        if detail is not None and detail != "":
            self._detail.setText(str(detail))
            self._detail.setVisible(True)
        elif detail == "":
            self._detail.setText(EMPTY)
            self._detail.setVisible(False)


class SafeExecutionScreen(QWidget):
    """شاشة عرض تقدّم التنفيذ الآمن (سبع خطوات ذرّية + مفتاح حالات + فشل يدوي).

    عرض فقط: ``show_result(result)`` يشتق حالات الخطوات والحالة النهائية من
    ``ExecutionResult`` الحقيقي. لا شبكة إطلاقًا.
    """

    def __init__(self, parent=None, **kwargs):  # تسامح: ContentRouter يبنيه بلا خدمات
        super().__init__(parent)
        self.screen_key = "05_safe_execution"
        self.setObjectName("Screen_05_safe_execution")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة القسم.
        self.heading = QLabel("التنفيذ الآمن", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        # شارة "النافذة العارية" — تُبرَز أثناء الخطوتين ⑤–⑥ (current/pending).
        self._naked_banner = QLabel(NAKED_WINDOW_TEXT, self)
        self._naked_banner.setObjectName("SafeExecNakedWindowBanner")
        self._naked_banner.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._naked_banner.setWordWrap(True)
        self._naked_banner.setStyleSheet(
            "color:%s;background:%s;border:1px solid %s;border-radius:8px;"
            "padding:8px 12px;font-size:13px;font-weight:700;"
            % (PALETTE["AMBER"], PALETTE["CARD"], PALETTE["AMBER"])
        )
        root.addWidget(self._naked_banner)

        # بطاقة الستبر: صفوف الخطوات السبع بالترتيب.
        stepper_card = QFrame(self)
        stepper_card.setObjectName("SafeExecStepperCard")
        stepper_card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        stepper_card.setStyleSheet(
            "QFrame#SafeExecStepperCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD"], PALETTE["BORDER"])
        )
        stepper_layout = QVBoxLayout(stepper_card)
        stepper_layout.setContentsMargins(14, 12, 14, 12)
        stepper_layout.setSpacing(8)

        self._steps = {}
        for key, label in STEPS:
            row = _StepRow(key, label, stepper_card)
            row.set_naked(key in _NAKED_STEPS)
            self._steps[key] = row
            stepper_layout.addWidget(row)
        root.addWidget(stepper_card)

        # بطاقة مفتاح الحالات (مفتاح الحالات).
        legend_card = QFrame(self)
        legend_card.setObjectName("SafeExecLegendCard")
        legend_card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        legend_card.setStyleSheet(
            "QFrame#SafeExecLegendCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        legend_layout = QVBoxLayout(legend_card)
        legend_layout.setContentsMargins(14, 12, 14, 12)
        legend_layout.setSpacing(8)

        legend_title = QLabel("مفتاح الحالات", legend_card)
        legend_title.setObjectName("SafeExecLegendTitle")
        legend_title.setStyleSheet(
            "color:%s;font-size:14px;font-weight:700;" % PALETTE["TEXT"]
        )
        legend_layout.addWidget(legend_title)

        for code, arabic, color_key in _LEGEND:
            item_row = QHBoxLayout()
            item_row.setSpacing(10)
            dot = QLabel("●", legend_card)
            dot.setObjectName("SafeExecLegendDot_%s" % code)
            dot.setStyleSheet(
                "color:%s;font-size:14px;font-weight:700;" % PALETTE[color_key]
            )
            text = QLabel("%s — %s" % (code, i18n.translate_for_current(arabic)), legend_card)
            text.setObjectName("SafeExecLegendText_%s" % code)
            text.setStyleSheet("color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"])
            item_row.addWidget(dot)
            item_row.addWidget(text, 1)
            legend_layout.addLayout(item_row)
        root.addWidget(legend_card)

        # بطاقة FAILED_NEEDS_ATTENTION (مخفيّة افتراضيًا).
        self._failure_card = QFrame(self)
        self._failure_card.setObjectName("SafeExecFailureCard")
        self._failure_card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._failure_card.setStyleSheet(
            "QFrame#SafeExecFailureCard{background:%s;border:2px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD"], PALETTE["RED"])
        )
        failure_layout = QVBoxLayout(self._failure_card)
        failure_layout.setContentsMargins(16, 14, 16, 14)
        failure_layout.setSpacing(8)

        self._failure_headline = QLabel(FAILURE_HEADLINE, self._failure_card)
        self._failure_headline.setObjectName("SafeExecFailureHeadline")
        self._failure_headline.setWordWrap(True)
        self._failure_headline.setStyleSheet(
            "color:%s;font-size:14px;font-weight:700;" % PALETTE["RED"]
        )
        failure_layout.addWidget(self._failure_headline)

        self._failure_detail = QLabel(EMPTY, self._failure_card)
        self._failure_detail.setObjectName("SafeExecFailureDetail")
        self._failure_detail.setWordWrap(True)
        self._failure_detail.setStyleSheet(
            "color:%s;font-size:13px;font-weight:600;" % PALETTE["TEXT"]
        )
        failure_layout.addWidget(self._failure_detail)
        root.addWidget(self._failure_card)

        # سطر الحالة النهائية (نجاح/إلغاء/فشل).
        self._final_status = QLabel(EMPTY, self)
        self._final_status.setObjectName("SafeExecFinalStatus")
        self._final_status.setWordWrap(True)
        self._final_status.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        root.addWidget(self._final_status)

        root.addStretch(1)

        # الحالة الابتدائية: كل الخطوات "wait"، الشارة خافتة، بطاقة الفشل مخفيّة.
        self.reset()

    # ---- API عام ----------------------------------------------------------
    def retranslate_i18n(self):
        """يعيد عرض مفتاح الحالات باللغة الفعّالة (عند تبديل اللغة)."""
        for code, arabic, _color_key in _LEGEND:
            lbl = self.findChild(QLabel, "SafeExecLegendText_%s" % code)
            if lbl is not None:
                lbl.setText("%s — %s" % (code, i18n.translate_for_current(arabic)))

    def reset(self):
        """يعيد كل الخطوات إلى "wait"، يخفي بطاقة الفشل، ويُخمِد الشارة."""
        for row in self._steps.values():
            row.set_status("wait", detail="")
        self._failure_card.setVisible(False)
        self._failure_detail.setText(EMPTY)
        self._final_status.setText(EMPTY)
        self._set_naked_emphasis(active=False)

    def show_result(self, result, *, selected=None):
        """يشتق حالات الخطوات والحالة النهائية من ``ExecutionResult`` (عرض فقط).

        يقرأ الحالات مباشرةً من ``result.steps`` حين تكون متاحة (المحرّك يضبطها)،
        ثم يعيّن الحالة النهائية من ``result.state``. لا شبكة إطلاقًا.
        """
        if result is None:
            self.reset()
            return

        state_name = _state_name(result)

        # 1) حالات الخطوات — الأفضل من result.steps، وإلا اشتقاق تحفّظي.
        engine_steps = getattr(result, "steps", None) or []
        seen = set()
        for step in engine_steps:
            key = getattr(step, "key", None)
            row = self._steps.get(key)
            if row is None:
                continue
            seen.add(key)
            raw = getattr(step, "status", "pending")
            mapped = _ENGINE_STATUS_MAP.get(raw, "wait")
            # "skipped" ⇒ aborted عند إلغاء الإجراء، وإلا مجرّد انتظار.
            if raw == "skipped":
                mapped = "aborted" if state_name == _STATE_ABORTED else "wait"
            row.set_status(mapped, detail=getattr(step, "detail", "") or "")
        # أي خطوة لم يذكرها المحرّك تبقى "wait".
        for key, row in self._steps.items():
            if key not in seen and engine_steps:
                row.set_status("wait", detail="")

        # إن لم توجد خطوات على النتيجة إطلاقًا: اشتقاق تحفّظي من الحالة النهائية.
        if not engine_steps:
            self._derive_steps_from_state(state_name, result)

        # 2) إبراز النافذة العارية فقط أثناء ⑤–⑥ (current/wait).
        naked_active = any(
            self._steps[k].status in ("current", "wait") for k in _NAKED_STEPS
        ) and state_name not in (_STATE_SUCCESS, _STATE_ABORTED, _STATE_FAILED)
        self._set_naked_emphasis(active=naked_active)

        # 3) الحالة النهائية + بطاقة الفشل.
        cancelled = getattr(result, "cancelled_order_list_id", None)
        new_id = getattr(result, "new_order_list_id", None)
        reason = getattr(result, "reason", "") or ""

        if state_name == _STATE_SUCCESS:
            self._failure_card.setVisible(False)
            msg = (
                i18n.translate_for_current("✓ نجاح — الأمر الجديد:") + " %s" % new_id
                if new_id is not None
                else i18n.translate_for_current("✓ نجاح")
            )
            self._final_status.setText(msg)
            self._final_status.setStyleSheet(
                "color:%s;font-size:13px;font-weight:700;" % PALETTE["GREEN"]
            )
        elif state_name == _STATE_FAILED:
            # Cancel ✓ · Create ✗ — لا إعادة محاولة تلقائية.
            self._show_failure_card(cancelled_id=cancelled, new_id=new_id)
            self._final_status.setText(reason or i18n.translate_for_current(FAILURE_HEADLINE))
            self._final_status.setStyleSheet(
                "color:%s;font-size:13px;font-weight:700;" % PALETTE["RED"]
            )
        else:  # ABORTED أو أي حالة غير نهائية أخرى
            self._failure_card.setVisible(False)
            self._final_status.setText(reason or i18n.translate_for_current("⊘ أُلغي الإجراء — الأمر الأصلي سليم."))
            self._final_status.setStyleSheet(
                "color:%s;font-size:13px;font-weight:600;" % PALETTE["AMBER"]
            )

    # ---- داخليّ -----------------------------------------------------------
    def _derive_steps_from_state(self, state_name, result):
        """اشتقاق تحفّظي لحالات الخطوات حين لا يحمل النتيجة قائمة خطوات."""
        new_id = getattr(result, "new_order_list_id", None)
        cancelled = getattr(result, "cancelled_order_list_id", None)
        if state_name == _STATE_SUCCESS:
            for row in self._steps.values():
                row.set_status("done")
        elif state_name == _STATE_FAILED:
            # Cancel ✓ حتى ⑤، ⑥ فشل، ⑦ انتظار.
            for key in ("verify", "price", "recalc", "gate", "cancel"):
                self._steps[key].set_status("done")
            self._steps["create"].set_status("failed")
            self._steps["confirm"].set_status("wait")
        elif state_name == _STATE_ABORTED:
            # أُلغي قبل الإلغاء الفعلي عادةً: الخطوات المنجزة done والباقي aborted.
            done_upto = "cancel" if cancelled is not None else "gate"
            reached = False
            for key, _label in STEPS:
                if not reached:
                    self._steps[key].set_status("done")
                    if key == done_upto:
                        reached = True
                else:
                    self._steps[key].set_status("aborted")
        else:
            for row in self._steps.values():
                row.set_status("wait")

    def _show_failure_card(self, *, cancelled_id, new_id):
        """يُظهر بطاقة الفشل مع تفصيل orderListId ونمط Cancel ✓ · Create ✗."""
        oid = cancelled_id if cancelled_id is not None else EMPTY
        # cancel-succeeded-but-create-failed: إلغاء تمّ، إنشاء لم يتمّ.
        cancel_mark = "Cancel ✓" if cancelled_id is not None else "Cancel ✗"
        create_mark = "Create ✓" if new_id is not None else "Create ✗"
        self._failure_detail.setText(
            "orderListId: %s  ·  %s · %s" % (oid, cancel_mark, create_mark)
        )
        self._failure_card.setVisible(True)

    def _set_naked_emphasis(self, *, active):
        """يبرز/يخمد شارة النافذة العارية حسب كون ⑤–⑥ جاريتين/معلّقتين."""
        if active:
            self._naked_banner.setStyleSheet(
                "color:%s;background:%s;border:2px solid %s;border-radius:8px;"
                "padding:10px 14px;font-size:14px;font-weight:700;"
                % (PALETTE["AMBER"], PALETTE["CARD_ALT"], PALETTE["AMBER"])
            )
        else:
            # خافتة (مكتومة) خارج نافذة الإلغاء/الإنشاء.
            self._naked_banner.setStyleSheet(
                "color:%s;background:%s;border:1px solid %s;border-radius:8px;"
                "padding:8px 12px;font-size:13px;font-weight:600;"
                % (PALETTE["MUTED"], PALETTE["CARD"], PALETTE["BORDER"])
            )
