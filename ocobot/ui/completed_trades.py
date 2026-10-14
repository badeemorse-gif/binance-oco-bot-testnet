"""شاشة الصفقات المنتهية (Completed Trades) — G1.14 (step_5).

شاشة قراءة فقط تعرض «الصفقات المنتهية (CLOSED)» المُعاد بناؤها من سجل التدقيق
عبر طبقة الـ domain (``ocobot.domain.completed_trades``) دون أي منطق مُعاد هنا:
كل البناء/الحساب/الإخفاء يمرّ عبر الموديول (load_completed_trades + DismissStore).
لا شبكة ولا IO على خيط الواجهة سوى قراءة ملف السجل عبر الـ domain (يحترم حارس
الواجهة ضدّ النداءات الشبكية المباشرة — لا عميل REST موقَّع ولا مكتبات شبكة هنا).

التقسيم (مطابق لتعريف G1.14):
  - النصف العلوي: قائمة عموديّة قابلة للاختيار بالصفقات المنتهية (تمرير بالعجلة)
    + زرّان: [مسح الصفقة المحددة] (= إخفاء عبر مؤشّر الإخفاء، لا حذف من السجل)
    و[تفاصيل الصفقة] (يحمّل تفاصيل التموضع في النصف السفلي).
  - النصف السفلي: جدول تفاصيل تموضع الصفقة المختارة (تمرير بالعجلة): لكل خطوة
    التاريخ/الوقت الدقيق (ts)، السعر المرجعي/الدخول، سعر الإيقاف، سعر البيع،
    سلسلة إعادة التموضع، والربح $/% محسوبًا من السعر المرجعي عند بدء المراقبة.
    عند غياب سعر البيع (صفقات قديمة) يُعرض «غير متاح» لسعر البيع والربح.

كل النصوص الظاهرة عربية عدا الأرقام ورمز العملة ($) ورمز العملة التداولية (symbol).
RTL + ثيم داكن عبر PALETTE (D15)، على نمط بقية الشاشات (dashboard/open_orders/
monitoring). تُسجَّل في step_6 تحت المفتاح ``08_completed_trades``.
"""
import os

from ._qt import (
    Qt,
    QTimer,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from .theme import PALETTE
from . import i18n
from .profitability_panel import ProfitabilityPanel
from ocobot.domain.models import fmt
from ocobot.domain.completed_trades import (
    DismissStore,
    default_dismiss_path,
    load_completed_trades,
    parse_audit_jsonl,
)
from ocobot.domain.profitability import extract_exit_executions, profitability_by_mode

EMPTY = "—"
NA = "غير متاح"  # يُعرض لسعر البيع/الربح حين يغيب سعر الخروج (صفقات قديمة).
EMPTY_STATE = "لا توجد صفقات منتهية بعد."

# مسار سجل التدقيق الافتراضي (نفس منطق cli._resolve_audit_path دون استيراد CLI):
# متغيّر البيئة OCOBOT_AUDIT_LOG وإلا ocobot_audit.jsonl في مجلّد العمل الحالي.
# الواجهة قارئة فقط ولا تكتب في السجل إطلاقًا (الكتابة الوحيدة = DismissStore).
_DEFAULT_AUDIT_FILENAME = "ocobot_audit.jsonl"


def _default_audit_path():
    """مسار سجل التدقيق الافتراضي (OCOBOT_AUDIT_LOG أو cwd/ocobot_audit.jsonl)."""
    return os.environ.get(
        "OCOBOT_AUDIT_LOG", os.path.join(os.getcwd(), _DEFAULT_AUDIT_FILENAME)
    )


# تسميات سبب الإنهاء (end_reason) — تُعرض في القائمة العلوية ضمن تسمية الصف.
END_REASON_LABELS = {
    "completed_tp": "اكتملت (جني ربح)",
    "completed_sl": "اكتملت (وقف خسارة)",
    "stopped_manual": "موقوفة (يدوي)",
    "stopped_disconnect": "موقوفة (قطع اتصال)",
    "stopped_other": "موقوفة (أخرى)",
}


def _end_reason_label(end_reason):
    """تسمية سبب الإنهاء (عربية) مع تراجع إلى القيمة الخام أو شرطة عند الغياب."""
    return i18n.translate_for_current(END_REASON_LABELS.get(end_reason, end_reason or "—"))


# أعمدة جدول تفاصيل التموضع (رؤوس عربية؛ القيم أرقام/رمز/عملة فقط).
DETAIL_HEADERS = [
    "#",
    "التاريخ والوقت",
    "معرّف قائمة الأوامر",
    "السعر المرجعي / الدخول",
    "سعر الإيقاف",
    "سعر البيع",
    "الربح ($)",
    "الربح (%)",
]


def _readonly_item(text):
    """خلية جدول غير قابلة للتحرير (نفس نمط open_orders._readonly_item)."""
    item = QTableWidgetItem(EMPTY if text is None or text == "" else str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _trade_label(trade):
    """تسمية صف الصفقة في القائمة: معرّف الجلسة + الرمز/الوقت/الربح + سبب الإنهاء.

    - يبدأ النص بـ ``session_id`` (إن كان نصًّا غير فارغ) متبوعًا بـ " — ".
    - يُلحق دومًا " — " + تسمية سبب الإنهاء عند توفّر end_reason (أو session_id).
    - للصفقات القديمة (session_id == "") بلا end_reason تُعاد التسمية الأصلية كما هي.
    """
    symbol = trade.symbol or EMPTY
    closed = trade.closed_at or EMPTY
    if trade.profit_available and trade.profit_pct is not None:
        profit = "%s%% / %s $" % (fmt(trade.profit_pct), fmt(trade.profit_usd))
    else:
        profit = NA
    base = "%s · %s · %s" % (symbol, closed, profit)
    session_id = trade.session_id if isinstance(trade.session_id, str) else ""
    end_reason = trade.end_reason or ""
    if session_id:
        return "%s — %s — %s" % (session_id, base, _end_reason_label(end_reason))
    if end_reason:
        return "%s — %s" % (base, _end_reason_label(end_reason))
    return base


class CompletedTradesScreen(QWidget):
    """شاشة الصفقات المنتهية — قارئة فقط فوق ocobot.domain.completed_trades.

    الحقن (اختياري، كنمط بقية الشاشات):
      - ``audit_path``: مسار سجل التدقيق JSONL (إن غاب يُحسب افتراضيًّا).
      - ``dismiss_path``: مسار ملف الإخفاء JSON (إن غاب يجاور ملف التدقيق).
      - ``runner``: AsyncRunner اختياري لإبقاء قراءة الملف خارج خيط الواجهة؛
        بلا runner تُقرأ متزامنًا (كبقية الشاشات/الاختبارات).
    """

    def __init__(self, parent=None, audit_path=None, dismiss_path=None, runner=None):
        super().__init__(parent)
        self.screen_key = "08_completed_trades"
        self.setObjectName("Screen_08_completed_trades")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        # G1.24 P1: استخدم audit_path المُمرَّر إن وُجد، وإلا تراجَع للقاعدة
        # القديمة (OCOBOT_AUDIT_LOG أو cwd/ocobot_audit.jsonl) — متوافق خلفيًّا.
        self.audit_path = audit_path or _default_audit_path()
        self._audit_path = self.audit_path
        self._dismiss_path = dismiss_path or default_dismiss_path(self._audit_path)
        self._runner = runner

        # G1.24 P2: مؤقّت تحديث دوري (1s) يعيد قراءة سجل التدقيق أثناء ظهور الشاشة
        # فقط؛ يبدأ في showEvent ويتوقّف في hideEvent لتفادي أي IO عندما تكون مخفية.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh)

        # قائمة CompletedTrade الحالية؛ خريطة صف→صفقة للنصف العلوي.
        self._trades = []
        # G1.51: توقيع آخر مجموعة صفقات (قائمة trade_key بالترتيب) لتفادي إعادة
        # بناء الجدول عند كل تحديث دوري متطابق (يحفظ اختيار المستخدم ويزيل تذبذب
        # الجدول كل ثانية). None = لا تعبئة بعد.
        self._last_sig = None
        # G1.54: الصفقات المرئيّة بعد فلترة الوضع، وفلتر الوضع الحالي ("" = الكل)،
        # وتوقيع كل الصفقات (لتحديث لوحة الملخّص عند تغيّرها فقط)، وtelemetry التنفيذ.
        self._visible = []
        self._mode_filter = ""
        self._last_all_sig = None
        self._exit_execs = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة الشاشة.
        self.heading = QLabel("الصفقات المنتهية", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        self._build_profit_panel(root)
        self._build_top_half(root)
        self._build_bottom_half(root)

        # تعبئة أوّليّة من الـ domain (قراءة فقط).
        self.refresh()

    # ------------------------------------------------------------------
    # النصف العلوي: قائمة الصفقات المنتهية + زرّا المسح/التفاصيل
    # ------------------------------------------------------------------
    def _build_profit_panel(self, root):
        """لوحة ملخّص الربحية (G1.54) أعلى الشاشة — عرض فقط + drill-down بالوضع."""
        self.profit_panel = ProfitabilityPanel(self)
        self.profit_panel.modeSelected.connect(self._on_mode_filter)
        root.addWidget(self.profit_panel)

    def _build_top_half(self, root):
        self.list_section = QLabel("قائمة الصفقات المنتهية", self)
        self.list_section.setObjectName("CompletedTradesListSection")
        self.list_section.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.list_section)

        # ملاحظة فارغة/إرشادية.
        self.note = QLabel("", self)
        self.note.setObjectName("CompletedTradesNote")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(
            "color:%s;font-size:13px;background:%s;border:1px solid %s;"
            "border-radius:10px;padding:12px 16px;"
            % (PALETTE["TEXT_SOFT"], PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        root.addWidget(self.note)

        # القائمة = جدول بعمود واحد قابل للاختيار (SingleSelection + SelectRows)،
        # تمرير بالعجلة لكل بكسل، كل الخلايا غير قابلة للتحرير.
        self.list_table = QTableWidget(0, 1, self)
        self.list_table.setObjectName("CompletedTradesList")
        self.list_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.list_table.setHorizontalHeaderLabels(["الصفقة"])
        self.list_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.list_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        # تمرير سلس بالعجلة (per-pixel) + إظهار شريط التمرير العمودي عند الحاجة.
        self.list_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.list_table.setStyleSheet(
            "QTableWidget{background:%s;border:1px solid %s;border-radius:12px;"
            "gridline-color:%s;}"
            "QHeaderView::section{background:%s;color:%s;border:0;"
            "border-bottom:1px solid %s;padding:12px 14px;font-weight:600;}"
            % (
                PALETTE["CARD"],
                PALETTE["BORDER"],
                PALETTE["BORDER"],
                PALETTE["SIDEBAR"],
                PALETTE["MUTED"],
                PALETTE["BORDER"],
            )
        )
        root.addWidget(self.list_table, 1)

        # صفّ الأزرار: [مسح الصفقة المحددة] + [تفاصيل الصفقة].
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.dismiss_button = QPushButton("مسح الصفقة المحددة", self)
        self.dismiss_button.setObjectName("CompletedTradesDismissButton")
        self.dismiss_button.clicked.connect(self._on_dismiss_clicked)
        btn_row.addWidget(self.dismiss_button)

        self.details_button = QPushButton("تفاصيل الصفقة", self)
        self.details_button.setObjectName("CompletedTradesDetailsButton")
        self.details_button.clicked.connect(self._on_details_clicked)
        btn_row.addWidget(self.details_button)

        # اختيار صفّ في القائمة يحمّل التفاصيل مباشرةً (نفس سلوك [تفاصيل الصفقة]).
        self.list_table.itemSelectionChanged.connect(self._on_selection_changed)

        btn_row.addStretch(1)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # النصف السفلي: جدول تفاصيل التموضع للصفقة المختارة
    # ------------------------------------------------------------------
    def _build_bottom_half(self, root):
        self.detail_section = QLabel("تفاصيل سلسلة التموضع", self)
        self.detail_section.setObjectName("CompletedTradesDetailSection")
        self.detail_section.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.detail_section)

        self.detail_title = QLabel("تفاصيل التموضع", self)
        self.detail_title.setObjectName("CompletedTradesDetailTitle")
        self.detail_title.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.detail_title)

        self.detail_table = QTableWidget(0, len(DETAIL_HEADERS), self)
        self.detail_table.setObjectName("CompletedTradesDetailTable")
        self.detail_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.detail_table.setHorizontalHeaderLabels(DETAIL_HEADERS)
        self.detail_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.detail_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.detail_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        # تمرير بالعجلة (per-pixel) للنصف السفلي أيضًا.
        self.detail_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.detail_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.detail_table.setStyleSheet(
            "QTableWidget{background:%s;border:1px solid %s;border-radius:12px;"
            "gridline-color:%s;}"
            "QHeaderView::section{background:%s;color:%s;border:0;"
            "border-bottom:1px solid %s;padding:12px 14px;font-weight:600;}"
            % (
                PALETTE["CARD"],
                PALETTE["BORDER"],
                PALETTE["BORDER"],
                PALETTE["SIDEBAR"],
                PALETTE["MUTED"],
                PALETTE["BORDER"],
            )
        )
        root.addWidget(self.detail_table, 1)

    # ------------------------------------------------------------------
    # قراءة البيانات من الـ domain (قراءة فقط)
    # ------------------------------------------------------------------
    def _load(self):
        """يقرأ الصفقات المنتهية غير المُخفاة عبر الـ domain (قراءة فقط)."""
        return load_completed_trades(self._audit_path, self._dismiss_path)

    def _load_execs(self):
        """G1.54: telemetry تنفيذ الخروج (exit_execution) للوحة الربحية — قراءة فقط.

        متسامح تمامًا: مسار مفقود/تالف ⇒ قائمة فارغة (لا شبكة، لا كتابة).
        """
        try:
            return extract_exit_executions(parse_audit_jsonl(self._audit_path))
        except Exception:
            return []

    def refresh(self):
        """يعيد تحميل القائمة من الـ domain وعرضها (يخفي السفلي حتى يُطلب).

        G1.24 P1b: يُستدعى عند إظهار الشاشة فيعيد قراءة ملف التدقيق
        (``self.audit_path``) حتى تظهر الصفقات المغلقة حديثًا دون إعادة تشغيل.
        G1.54: يُحمّل أيضًا telemetry تنفيذ الخروج للوحة الربحية (قراءة فقط).
        """
        self._exit_execs = self._load_execs()
        if self._runner is not None:
            return self._runner.submit(self._load, on_result=self.set_trades)
        self.set_trades(self._load())
        return None

    # ------------------------------------------------------------------
    # G1.24 P2: تحديث دوري أثناء ظهور الشاشة فقط (showEvent/hideEvent)
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """عند إظهار الشاشة: تحديث فوري ثم بدء المؤقّت الدوري (1s)."""
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()

    def hideEvent(self, event):
        """عند إخفاء الشاشة: إيقاف المؤقّت الدوري لتفادي أي IO وهي مخفية."""
        self._refresh_timer.stop()
        super().hideEvent(event)

    @staticmethod
    def _trades_signature(trades):
        """توقيع ثابت لقائمة الصفقات = tuple من trade_key بالترتيب (G1.51)."""
        return tuple(getattr(t, "trade_key", None) for t in trades)

    def set_trades(self, trades):
        """يحدّث لوحة الملخّص (عند تغيّر الصفقات) ثم يعرض القائمة المفلترة.

        G1.54: لوحة الربحية أعلى الشاشة تُغذَّى من كل الصفقات وتُحدَّث فقط عند تغيّر
        مجموعتها (تفادي الوميض كل ثانية). القائمة الوسطى تُعرض عبر ``_apply_list``
        وفق فلتر الوضع الحالي، مع إبقاء منطق ثبات التحديد (G1.51).
        """
        new_list = list(trades or [])
        self._trades = new_list

        all_sig = self._trades_signature(new_list)
        if all_sig != self._last_all_sig:
            self._update_profit_panel(new_list)
            self._last_all_sig = all_sig

        self._apply_list()

    def _update_profit_panel(self, trades):
        """يُغذّي لوحة الربحية من profitability_by_mode (قراءة فقط، عرض فقط)."""
        stats = profitability_by_mode(trades, self._exit_execs)
        self.profit_panel.set_data(stats, trades)

    def _visible_trades(self):
        """الصفقات بعد تطبيق فلتر الوضع الحالي (""/None ⇒ الكل)."""
        f = self._mode_filter
        if not f:
            return list(self._trades)
        return [t for t in self._trades if (getattr(t, "exit_source", "") or "") == f]

    def _on_mode_filter(self, mode):
        """drill-down: فلترة القائمة الوسطى بالوضع المنقور (لا يمسّ لوحة الملخّص)."""
        self._mode_filter = mode or ""
        self._apply_list()

    def _apply_list(self):
        """يعرض القائمة المفلترة مع ثبات التحديد (منطق G1.51 موسَّعًا بالفلترة).

        التوقيع يضمّ فلتر الوضع، فتغييره يُعيد البناء؛ وأي تحديث دوري متطابق (نفس
        الفلتر ونفس trade_keys المرئيّة) لا يُعيد البناء ولا يسرق التحديد.
        """
        visible = self._visible_trades()
        new_sig = (self._mode_filter,
                   tuple(getattr(t, "trade_key", None) for t in visible))

        # (1) تحديث متطابق والجدول مُعبَّأ: لا إعادة بناء (حفظ الاختيار/التفاصيل).
        if (
            new_sig == self._last_sig
            and self.list_table.rowCount() == len(visible)
            and len(visible) > 0
        ):
            self._visible = visible
            return

        # (2) التقاط الصفقة المحدّدة حاليًّا (من المرئيّة القديمة) قبل أي مسح.
        prev_selected = self._selected_trade()
        prev_key = getattr(prev_selected, "trade_key", None) if prev_selected else None

        self._visible = visible

        # إعادة البناء مع كتم الإشارات لتفادي _on_selection_changed الطيفيّة.
        self.list_table.blockSignals(True)
        try:
            self.list_table.setRowCount(0)
            for trade in visible:
                r = self.list_table.rowCount()
                self.list_table.insertRow(r)
                self.list_table.setItem(r, 0, _readonly_item(_trade_label(trade)))
        finally:
            self.list_table.blockSignals(False)

        # حالة فارغة (لا صفقات أصلًا أو لا صفقات لهذا الوضع): رسالة + تعطيل الأزرار.
        is_empty = not visible
        self.note.setText(i18n.translate_for_current(EMPTY_STATE) if is_empty else "")
        self.note.setVisible(is_empty)
        self.dismiss_button.setEnabled(not is_empty)
        self.details_button.setEnabled(not is_empty)

        self._last_sig = new_sig

        if is_empty:
            # لا صفقات مرئيّة: فرّغ التفاصيل وأعد العنوان الأساسي.
            self.detail_table.setRowCount(0)
            self.detail_title.setText(i18n.translate_for_current("تفاصيل التموضع"))
            return

        # تحديد صفّ الاختيار الجديد: نفس الصفقة إن بقيت، وإلا تراجع للصف 0.
        target_row = 0
        if prev_key is not None:
            for idx, trade in enumerate(visible):
                if getattr(trade, "trade_key", None) == prev_key:
                    target_row = idx
                    break

        # ضبط الاختيار (الإشارات غير مكتومة الآن) ثم تحديث التفاصيل مرّة واحدة.
        self.list_table.setCurrentCell(target_row, 0)
        selected = self._selected_trade()
        if selected is not None:
            self.show_trade_details(selected)

    # ------------------------------------------------------------------
    # اختيار الصف الحالي
    # ------------------------------------------------------------------
    def _selected_trade(self):
        """CompletedTrade للصف المحدّد في القائمة المرئيّة (المفلترة)، أو None."""
        row = self.list_table.currentRow()
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    # ------------------------------------------------------------------
    # [تفاصيل الصفقة]: تحميل سلسلة التموضع في النصف السفلي
    # ------------------------------------------------------------------
    def _on_details_clicked(self, *args):
        trade = self._selected_trade()
        if trade is None:
            return
        self.show_trade_details(trade)

    def _on_selection_changed(self, *args):
        """تغيّر اختيار الصف في القائمة يُحمّل تفاصيله في النصف السفلي فورًا."""
        trade = self._selected_trade()
        if trade is not None:
            self.show_trade_details(trade)

    def show_trade_details(self, trade):
        """يملأ جدول النصف السفلي بخطوات التموضع + الربح للصفقة.

        السعر المرجعي عند بدء المراقبة (trade.reference_price) هو مرجع الربح؛
        الربح يُعرض من الـ domain (trade.profit_usd/pct) على صفّ الخطوة الأخيرة
        (نقطة الإغلاق). سعر البيع/الربح يُعرضان «غير متاح» حين لا يتوفّران.
        """
        self.detail_title.setText(
            i18n.translate_for_current("تفاصيل التموضع") + " — %s" % (trade.symbol or EMPTY)
        )
        self.detail_table.setRowCount(0)

        steps = trade.steps or []
        last_index = len(steps) - 1
        for i, step in enumerate(steps):
            r = self.detail_table.rowCount()
            self.detail_table.insertRow(r)
            self.detail_table.setItem(r, 0, _readonly_item(i + 1))
            self.detail_table.setItem(r, 1, _readonly_item(step.ts or EMPTY))
            self.detail_table.setItem(r, 2, _readonly_item(step.order_list_id))
            self.detail_table.setItem(r, 3, _readonly_item(fmt(step.price)))
            self.detail_table.setItem(r, 4, _readonly_item(fmt(step.stop_trigger)))

            # سعر البيع: من الخطوة إن وُجد؛ وإلا «غير متاح» (صفقات قديمة).
            if step.sell_price is not None:
                sell_text = fmt(step.sell_price)
            else:
                sell_text = NA
            self.detail_table.setItem(r, 5, _readonly_item(sell_text))

            # الربح $/% يُعرض على صفّ الخطوة الأخيرة (نقطة الإغلاق) فقط؛
            # محسوب من الـ domain من السعر المرجعي عند بدء المراقبة.
            if i == last_index and trade.profit_available:
                usd_text = fmt(trade.profit_usd) if trade.profit_usd is not None else NA
                pct_text = fmt(trade.profit_pct) if trade.profit_pct is not None else NA
            elif i == last_index:
                # صفقة بلا سعر خروج (قديمة): «غير متاح» للربح.
                usd_text = NA
                pct_text = NA
            else:
                usd_text = EMPTY
                pct_text = EMPTY
            self.detail_table.setItem(r, 6, _readonly_item(usd_text))
            self.detail_table.setItem(r, 7, _readonly_item(pct_text))

    # ------------------------------------------------------------------
    # [مسح الصفقة المحددة]: إخفاء عبر مؤشّر الإخفاء (لا حذف من السجل)
    # ------------------------------------------------------------------
    def _on_dismiss_clicked(self, *args):
        trade = self._selected_trade()
        if trade is None:
            return
        # الإخفاء فقط عبر DismissStore (ملف JSON منفصل): لا يمسّ سجل التدقيق
        # append-only إطلاقًا (DS1). ثم نعيد التحميل فتختفي الصفقة من القائمة.
        DismissStore(self._dismiss_path).dismiss(trade.trade_key)
        # G1.51: أبطِل التوقيع لإجبار إعادة بناء القائمة بعد الإخفاء (قد تتطابق
        # الأطوال لكن المحتوى تغيّر؛ التوقيع يكفل عدم العودة المبكّرة الخاطئة).
        self._last_sig = None
        self.refresh()

    # ------------------------------------------------------------------
    # مساعدات للاختبارات (قراءة فقط)
    # ------------------------------------------------------------------
    def trade_labels(self):
        """نصوص صفوف القائمة العلوية بالترتيب (يستعملها الاختبار)."""
        return [
            self.list_table.item(i, 0).text()
            for i in range(self.list_table.rowCount())
            if self.list_table.item(i, 0) is not None
        ]

    def detail_column_headers(self):
        """رؤوس أعمدة جدول التفاصيل بالترتيب (يستعملها الاختبار)."""
        return [
            self.detail_table.horizontalHeaderItem(i).text()
            for i in range(self.detail_table.columnCount())
        ]
