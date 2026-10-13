"""شاشة جدول Open OCO Orders — T11b.

تعرض قوائم OCO المفتوحة الحقيقية عبر oco_reader (قراءة فقط، بلا نداء شبكة
مباشر — كل IO يمرّ عبر الخدمات/الرَنَر مثل T11a). الأعمدة الثمانية مطابقة
لموك-أب docs/ui_mockups/02_open_orders (التصميم §3.2 B) بالترتيب:
  # · Order List ID · Symbol · Status · Qty · سعر البيع / TP · Stop Trigger · Limit بعد التفعيل

- الكمية (Qty) Read-only إجباريًا (D7)، وكل الخلايا غير قابلة للتحرير.
- الدقّة/الفلاتر symbol-agnostic من exchangeInfo (D8): لا hardcode — القيم تُعرض
  كما تُنسّقها طبقة الـ domain (OcoOrder.to_row) بلا أي إعادة تدوير رقمي هنا.
- RTL + ثيم داكن عبر PALETTE (D15).
"""
from ._qt import (
    Qt,
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
from ocobot.domain.models import classify_badge
from ocobot.domain.selection import Selector

EMPTY = "—"
SELECT_NOTE = "الاختيار يعمل فقط على الـ orderListId المحدد — لا يُمَس أي أمر آخر حتى لو لنفس العملة."

# G1.17: حارس داخلي لتمييز "المفتاح غير موجود" عن القيمة None في _field.
_MISSING = object()


def _field(order, *names, default=None):
    """قراءة حقل بشكل محايد للشكل: يدعم dict ومفاتيحها وكذلك الكائن وسِماته.

    يجرّب الأسماء بالترتيب ويُعيد أول قيمة موجودة فعلًا (حتى لو كانت None)؛
    وإلا يُعيد default. يسمح لـ set_open_sell_orders أن تعرض صفوف OpenSellOrder
    والصفوف من نوع dict (مثل مسار الاتصال/اختبار G1.17) على حدٍّ سواء.
    """
    for n in names:
        if isinstance(order, dict):
            if n in order:
                return order[n]
        else:
            v = getattr(order, n, _MISSING)
            if v is not _MISSING:
                return v
    return default

# الأعمدة الثمانية القانونية (رؤوس verbatim من الموك-أب) مربوطة بمفاتيح OcoOrder.to_row().
# العمود "#" رقم صف تسلسلي؛ الباقي من to_row(). لا مفتاح to_row للعمود "#".
COLUMN_HEADERS = [
    "#",
    "معرّف قائمة الأوامر",
    "الرمز",
    "الحالة",
    "الكمية",
    "سعر البيع / جني الأرباح",
    "مُشغِّل الإيقاف",
    "سعر الحد بعد التفعيل",
]

# ترتيب مفاتيح to_row() المقابلة للأعمدة بعد عمود التسلسل "#".
ROW_KEYS = [
    "orderListId",
    "symbol",
    "status",
    "qty",
    "saleTp",
    "stopTrigger",
    "limitAfterTrigger",
]

# فهرس عمود الكمية (Qty) للتوثيق/التأكيد على D7 (Read-only).
QTY_COLUMN = 4


def _readonly_item(text):
    """خلية جدول غير قابلة للتحرير (تزيل ItemIsEditable مع إبقاء التمكين/الاختيار)."""
    item = QTableWidgetItem(EMPTY if text is None or text == "" else str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class OpenOrdersScreen(QWidget):
    """شاشة قراءة لجدول Open OCO Orders موصولة بمخرجات oco_reader."""

    def __init__(self, parent=None, runner=None, build_fn=None, on_select=None):
        super().__init__(parent)
        self.screen_key = "02_open_orders"
        self.setObjectName("Screen_02_open_orders")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._runner = runner
        self._build_fn = build_fn
        self._on_select = on_select
        # خريطة صف→orderListId (P1): الاختيار يعمل على المعرّف المحدد فقط.
        self._row_order_ids = []
        # G1.3: تذكّر آخر orderListId مختار لإعادة التظليل بعد إعادة التعبئة.
        self._selected_order_id = None
        # G1.13 (إضافي): حالة مسار "كل أوامر البيع" + التحويل إلى OCO.
        # تبقى فارغة في مسار OCO الافتراضي (set_orders) فلا تؤثّر عليه إطلاقًا.
        self._sell_rows = []          # list[OpenSellOrder] للمسار الجديد
        self._sell_mode = False       # True فقط بعد set_open_sell_orders
        self._selector = None         # domain/selection.Selector (اختياري)
        self._convert_cb = None       # callback التحويل (محقون)
        self._on_sell_select = None   # callback اختيار صفّ بيع (يتلقّى SelectedOCO)
        self._last_error = None
        self._current_selection = None  # آخر SelectedOCO من مسار البيع

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة القسم: عنوان + زر تحديث (verbatim من الموك-أب).
        header = QHBoxLayout()
        header.setSpacing(12)
        self.heading = QLabel("أوامر OCO المفتوحة على Binance", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        self.refresh_button = QPushButton("↻ تحديث الأوامر", self)
        self.refresh_button.setObjectName("RefreshOpenOrders")
        self.refresh_button.clicked.connect(self.refresh)
        # G1.13 (CHUNK 1): شاشة 02 صارت عرض+اختيار فقط. أُزيل زر «تحويل إلى OCO»
        # وتوجيهه؛ التحويل صار يُوجَّه لشاشة 04 عبر convert_cb في الـ wiring.
        header.addWidget(self.heading)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        # ملاحظة الأمان (P1): الاختيار على orderListId فقط.
        self.note = QLabel(SELECT_NOTE, self)
        self.note.setObjectName("OpenOrdersNote")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(
            "color:%s;font-size:13px;background:%s;border:1px solid %s;"
            "border-radius:10px;padding:12px 16px;"
            % (PALETTE["TEXT_SOFT"], PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        root.addWidget(self.note)

        # الجدول: الأعمدة الثمانية، كل الخلايا غير قابلة للتحرير (D7).
        self.table = QTableWidget(0, len(COLUMN_HEADERS), self)
        self.table.setObjectName("OpenOrdersTable")
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setStyleSheet(
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
        # ربط تغيّر الاختيار → إبلاغ callback بالـ orderListId للصف المحدد (P1).
        self.table.itemSelectionChanged.connect(self._handle_selection_changed)

        root.addWidget(self.table, 1)

    def set_on_select(self, cb):
        """حقن/تحديث callback الاختيار (يتلقّى orderListId للصف المحدد)."""
        self._on_select = cb

    # --- G1.13 (إضافي): حقن تبعيات مسار "كل أوامر البيع" --------
    def set_selector(self, selector):
        """حقن Selector (domain) لتوجيه select_from_row (G1.13)."""
        self._selector = selector

    def set_on_sell_select(self, cb):
        """حقن callback اختيار صفّ البيع (يتلقّى SelectedOCO) — G1.13."""
        self._on_sell_select = cb

    def selected_sell_selection(self):
        """آخر SelectedOCO ناتج من مسار البيع (أو None)."""
        return self._current_selection

    def set_source(self, build_fn=None, runner=None):
        """حقن مصدر البيانات (build_fn تُرجع list[OcoOrder]) و/أو المُشغِّل (runner)."""
        if build_fn is not None:
            self._build_fn = build_fn
        if runner is not None:
            self._runner = runner

    def _handle_selection_changed(self):
        model = self.table.selectionModel()
        selected_rows = model.selectedRows() if model is not None else []
        if selected_rows:
            row = selected_rows[0].row()
        else:
            row = self.table.currentRow()
        # G1.13 (إضافي): في مسار "كل أوامر البيع" نوجّه الاختيار عبر Selector
        # بدل مسار OCO الافتراضي، دون أن نمسّ سلوك OCO القديم.
        if self._sell_mode:
            self._handle_sell_selection_changed(row)
            return
        if 0 <= row < len(self._row_order_ids):
            oid = self._row_order_ids[row]
            self._selected_order_id = oid
            if self._on_select is not None:
                self._on_select(oid)

    def selected_order_id(self):
        """orderListId للصف المحدد حاليًّا، أو None."""
        row = self.table.currentRow()
        if 0 <= row < len(self._row_order_ids):
            return self._row_order_ids[row]
        return None

    def select_row(self, row):
        """اختيار صف برمجيًّا (يُطلق itemSelectionChanged)."""
        if 0 <= row < self.table.rowCount():
            self.table.setCurrentCell(row, 0)

    def column_headers(self):
        """رؤوس الأعمدة الفعلية للجدول بالترتيب (يستعملها الاختبار)."""
        return [
            self.table.horizontalHeaderItem(i).text()
            for i in range(self.table.columnCount())
        ]

    def set_orders(self, orders):
        """تعبئة الجدول من قائمة OcoOrder (تُستخدم to_row لكل صف)."""
        orders = orders or []
        self._sell_mode = False  # G1.13: مسار OCO الافتراضي (لا شارات/تحويل)
        self.table.setRowCount(0)
        self._row_order_ids = []
        for i, order in enumerate(orders, start=1):
            row = order.to_row() if hasattr(order, "to_row") else dict(order)
            r = self.table.rowCount()
            self.table.insertRow(r)
            # العمود "#": رقم تسلسلي (ليس من to_row).
            self.table.setItem(r, 0, _readonly_item(i))
            for col, key in enumerate(ROW_KEYS, start=1):
                self.table.setItem(r, col, _readonly_item(row.get(key)))
            # خريطة صف→orderListId (P1): من OcoOrder.order_list_id أو مفتاح dict.
            if hasattr(order, "order_list_id"):
                self._row_order_ids.append(order.order_list_id)
            else:
                self._row_order_ids.append(row.get("orderListId"))
        # G1.3: إعادة تظليل الصف المختار سابقًا بعد إعادة التعبئة (دون إعادة إطلاق الاختيار).
        if self._selected_order_id is not None and self._selected_order_id in self._row_order_ids:
            idx = self._row_order_ids.index(self._selected_order_id)
            blocker = self.table.blockSignals(True)
            try:
                self.table.setCurrentCell(idx, 0)
            finally:
                self.table.blockSignals(blocker)

    # --- G1.13 (إضافي): مسار "كل أوامر البيع" مع شارات + تحويل ----------
    def set_open_sell_orders(self, orders):
        """مسار إضافي: يعرض كل أوامر البيع (مستقلة + OCO مدموجة) مع شارة لكل صف.

        لا يمسّ مسار OCO الافتراضي (set_orders): يملأ الجدول نفسه بثمانية أعمدة
        لكن يضيف شارة .selbadge (classify_badge — TRAILING عند trailingDelta>0)
        داخل خلية "الحالة". الاختيار يمرّ عبر Selector.select_from_row فيُنتج
        SelectedOCO (OCO عادي، أو مرشّح تحويل is_convert_candidate لغير OCO).
        """
        orders = orders or []
        self._sell_mode = True
        self._sell_rows = list(orders)
        self.table.setRowCount(0)
        self._row_order_ids = []
        for i, order in enumerate(orders, start=1):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, _readonly_item(i))
            # G1.17: قراءة كل خلية بشكل محايد للشكل (OpenSellOrder أو dict) عبر
            # _field مع اسم السِمة ومفتاح dict كبدائل لكل عمود.
            # معرّف قائمة الأوامر: orderListId للـ OCO وإلا orderId/معرّف المستقل.
            olid = _field(order, "orderListId", default=-1)
            ident = olid if _field(order, "is_oco", default=False) else _field(order, "orderId", "orderListId")
            self.table.setItem(r, 1, _readonly_item(ident))
            self.table.setItem(r, 2, _readonly_item(_field(order, "symbol")))
            # عمود "الحالة": status + شارة النوع (pill) عبر classify_badge.
            self._set_status_with_badge(r, order)
            # الكمية (Qty) Read-only (D7).
            self.table.setItem(r, 4, _readonly_item(_field(order, "origQty", "qty")))
            self.table.setItem(r, 5, _readonly_item(_field(order, "price", "saleTp")))
            self.table.setItem(r, 6, _readonly_item(_field(order, "stopPrice", "stopTrigger")))
            self.table.setItem(r, 7, _readonly_item(_field(order, "limitAfterTrigger", default=EMPTY)))
            self._row_order_ids.append(ident)

    def _badge_text(self, order):
        """نص الشارة: OCO للمدموج، وإلا classify_badge من حقول الأمر الخام."""
        if _field(order, "is_oco", default=False):
            return "OCO"
        raw = {
            "type": _field(order, "order_type", "type", default=""),
            "trailingDelta": _field(order, "trailingDelta", default=""),
        }
        return classify_badge(raw)

    def _set_status_with_badge(self, row, order):
        """خلية "الحالة" = status + شارة pill (.selbadge) بلون PALETTE['GREEN']."""
        status = _field(order, "status", default="") or ""
        badge = self._badge_text(order)
        cell = QWidget(self.table)
        cell.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(8)
        status_label = QLabel(str(status) if status else EMPTY, cell)
        status_label.setStyleSheet("color:%s;" % PALETTE["TEXT"])
        pill = QLabel(badge, cell)
        pill.setObjectName("SellBadge")
        # نفس مواصفات .selbadge من الموك-أب: pill دائري أخضر شفّاف.
        pill.setStyleSheet(
            "border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;"
            "background:rgba(25,197,139,.18);color:%s;" % PALETTE["GREEN"]
        )
        lay.addWidget(status_label)
        lay.addWidget(pill)
        lay.addStretch(1)
        self.table.setCellWidget(row, 3, cell)
        # نُبقي أيضًا عنصر خلية نصّي (غير قابل للتحرير) للوصول البرمجي/الاختبار.
        self.table.setItem(row, 3, _readonly_item(status))

    def badge_for_row(self, row):
        """نص الشارة المعروض في الصف (يستعمله الاختبار)."""
        if 0 <= row < len(self._sell_rows):
            return self._badge_text(self._sell_rows[row])
        return None

    def _handle_sell_selection_changed(self, row):
        """اختيار صفّ بيع: يوجّه عبر Selector.select_from_row وينتج SelectedOCO."""
        if not (0 <= row < len(self._sell_rows)):
            return
        order = self._sell_rows[row]
        selected = None
        if self._selector is not None:
            # G1.19: get_oco للـ OCO القائمة نداء شبكي متزامن قد يرمي استثناءً؛
            # نلتقطه كي لا يبقى selected=None صامتًا ويمنع تغذية الشاشتين 03/04.
            try:
                selected = self._selector.select_from_row(order)
            except Exception as exc:  # noqa: BLE001
                self._last_error = exc
                selected = None
        self._current_selection = selected
        if selected is not None and self._on_sell_select is not None:
            self._on_sell_select(selected)

    def clear(self):
        self.table.setRowCount(0)
        self._row_order_ids = []
        self._sell_rows = []
        self._sell_mode = False
        self._current_selection = None

    def refresh(self, build_fn=None):
        """جلب القوائم عبر build_fn وعرضها.

        مع runner يُنفَّذ على خيط منفصل (T10c)؛ بلا runner يُنفَّذ متزامنًا (اختبارات).
        لا نداء شبكة هنا: build_fn هو استدعاء طبقة خدمات يملك أي IO.

        G1.13 (CHUNK 1): عندما يكون المصدر مسار "كل أوامر البيع" (set_selector
        محقون) نعرض النتائج عبر set_open_sell_orders مع الشارات؛ وإلا نُبقي مسار
        OCO الافتراضي (set_orders) دون أي تغيير.
        """
        fn = build_fn or self._build_fn
        if fn is None:
            return None
        on_result = self.set_open_sell_orders if self._selector is not None else self.set_orders
        if self._runner is not None:
            return self._runner.submit(fn, on_result=on_result, on_error=self._on_refresh_error)
        try:
            on_result(fn())
        except Exception as exc:  # noqa: BLE001
            self._on_refresh_error(exc)
        return None

    def _on_refresh_error(self, error):
        self._last_error = error
        self.clear()

    @property
    def last_error(self):
        return self._last_error
