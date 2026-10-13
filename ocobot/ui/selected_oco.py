"""شاشة تفاصيل الأمر المحدد (Selected OCO) — T11c قراءة + T12a قسم التعديل (s1..s5).

تعرض هوية الهدف المحدد (SelectedOCO) وفق بطاقة القراءة في مخطط
docs/ui_mockups/03_selected_and_edit: الحقول الثمانية للهوية + شارة قفل الكمية
(Read-only، D7). لا IO ولا شبكة هنا: كل جلب يمرّ عبر build_fn/الرَنَر المحقونين
(مثل T11a/T11b). RTL + ثيم داكن عبر PALETTE (D15). السعر الحيّ (Current Price)
خارج النطاق هنا (لوحة Live / T13 — D14).
"""
from ._qt import (  # واجهة Qt المجرّدة (تسمح بالاختبار offscreen)
    Qt,
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QSizePolicy,
)  # عناصر واجهة قسم القراءة/التعديل
from ocobot.domain.models import SelectedOCO, fmt  # noqa: F401
from ocobot.domain.pricing import compute_levels, max_available_stop  # حساب نقيّ فقط
from ocobot.core.failure_matrix import humanize  # رسائل عربية موحّدة للفشل (T12b/s3)
from decimal import InvalidOperation
from .theme import PALETTE  # لوحة الألوان الداكنة (D15)
from . import i18n  # ترجمة عرض عند التبديل (Arabic مصدر؛ identity في العربية)

# نصوص s3 (DS3): تأكيد التفعيل + شارة النافذة العارية.
CONFIRM_TITLE = "تأكيد"
CONFIRM_TEXT = "تفعيل إعادة التموضع: سيُلغى الأمر الحالي ثم يُنشأ البديل. متابعة؟"
NAKED_WINDOW_TEXT = "⚠️ نافذة عارية: المركز بلا حماية أثناء الإلغاء ثم الإنشاء"
# حالات النتيجة النهائية (سلاسل — لتجنّب استيراد ExecutionState وإبقاء الاقتران منخفضًا).
_STATE_SUCCESS = "SUCCESS"
_STATE_ABORTED = "ABORTED"
_STATE_FAILED = "FAILED_NEEDS_ATTENTION"

EMPTY = "—"  # رمز القيمة الفارغة
NO_SELECTION_NOTE = "لم يُختَر أمر"
LOCK_BADGE = "🔒 مقفولة"  # شارة قفل الكمية (D7)
READONLY_NOTE = "للعرض فقط"

# حقول القراءة الثمانية (بطاقة A، جزء القراءة) بالترتيب: (مفتاح، عنوان).
READ_FIELDS = [
    ("orderListId", "معرّف قائمة الأوامر"),
    ("symbol", "الرمز"),
    ("quantity", "الكمية"),
    ("tp", "جني الأرباح"),
    ("stopTrigger", "مُشغِّل الإيقاف"),
    ("stopLimit", "حد الإيقاف"),
    ("legIds", "معرّفات الأطراف"),
    ("status", "الحالة"),
]  # ترتيب العرض في البطاقة

# ألوان القيم البارزة (D15): TP أخضر، Stop Trigger أحمر، Status أزرق.
_VALUE_ACCENT = {
    "tp": "GREEN",
    "stopTrigger": "RED",
    "status": "BLUE",
}  # خريطة اللكنة اللونية


class SelectedOcoScreen(QWidget):
    """شاشة قراءة لهوية الـ OCO المحدد (تؤسّس عرض السياق الحيّ)."""

    def __init__(self, parent=None, runner=None, build_fn=None, executor=None,
                 execute_cb=None, confirm_cb=None, on_execution_result=None):
        super().__init__(parent)  # تهيئة QWidget
        self.screen_key = "03_selected_and_edit"  # مفتاح الشاشة
        self.setObjectName("Screen_03_selected_and_edit")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # RTL
        self.runner = runner  # منفّذ الخيوط (اختياري)
        self.build_fn = build_fn  # دالة جلب SelectedOCO المحقونة
        # T12b/s3: حقن التنفيذ + بوابة التأكيد (DS1 — تُمرَّر stubs في الاختبارات).
        self._executor = executor          # SafeExecutor أو None (له .execute)
        self._execute_cb = execute_cb      # دالة تنفيذ بديلة (لها الأولويّة على executor)
        self._confirm_cb = confirm_cb or self._default_confirm  # بوابة تأكيد قابلة للحقن
        # خُطّاف اختياري: يُخطر التطبيق بنتيجة التنفيذ (05) بعد اكتمال التفعيل (نجاح/فشل).
        self._on_execution_result = on_execution_result
        self._fields = {}
        # قسم التعديل (T12a/s1..s5): labels القيم القديمة تُبنى داخل _build_edit_section.
        self._old_fields = {}

        root = QVBoxLayout(self)  # التخطيط الجذري
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة + شارة قفل الكمية (مخفيّة حتى يُختار أمر).
        header = QHBoxLayout()
        header.setSpacing(12)
        self.heading = QLabel("تفاصيل الأمر المحدد", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        self._lock = QLabel(LOCK_BADGE, self)
        self._lock.setObjectName("SelectedLockBadge")
        self._lock.setStyleSheet(
            "color:%s;font-size:13px;font-weight:600;" % PALETTE["AMBER"]
        )
        self._lock.setVisible(False)
        header.addWidget(self.heading)
        header.addStretch(1)
        header.addWidget(self._lock)
        root.addLayout(header)  # إضافة الترويسة

        # ملاحظة "لم يُختَر أمر" (الحالة الابتدائية).
        self._note = QLabel(NO_SELECTION_NOTE, self)
        self._note.setObjectName("SelectedNote")
        self._note.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        root.addWidget(self._note)  # ملاحظة الاختيار

        # بطاقة الهوية: صفوف (عنوان + قيمة) مكدّسة عموديًّا.
        card = QFrame(self)
        card.setObjectName("SelectedCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#SelectedCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}"
            % (PALETTE["CARD"], PALETTE["BORDER"])
        )
        card_layout = QVBoxLayout(card)  # تخطيط بطاقة الهوية
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        # G1.4 (REWORK): شبكة مشتركة واحدة للبطاقة — العناوين في العمود 0 (تحت RTL
        # هو أقصى اليمين) بعرض أدنى ثابت وstretch=0 فتصطف كلها في عمود واحد؛ القيم في
        # العمود 1 بstretch=1 محاذاة نحو حافة العنوان (AlignRight = بادئة تحت RTL) فتلاصق
        # العنوان بفجوة أفقية ثابتة مضبوطة. يستبدل نهج QHBoxLayout+AlignRight الفاشل.
        grid = QGridLayout()  # شبكة صفوف العنوان/القيمة (مشتركة)
        grid.setHorizontalSpacing(12)  # فجوة أفقية ثابتة صغيرة بين العمودين
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)  # عمود العناوين لا يتمدّد
        grid.setColumnStretch(1, 1)  # عمود القيم يمتصّ التمدّد
        grid.setColumnMinimumWidth(0, 150)  # عرض أدنى موحّد فتصطف العناوين
        for r, (key, label) in enumerate(READ_FIELDS):
            caption = QLabel(label, card)  # عنوان الحقل الثابت
            caption.setObjectName("SelectedCaption")
            caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])  # نمط العنوان
            caption.setMinimumWidth(150)  # يضمن اصطفاف كل العناوين على نفس x
            value = QLabel(EMPTY, card)  # قيمة الحقل (تُملأ في set_selected)
            value.setObjectName("SelectedValue_%s" % key)
            accent = PALETTE.get(_VALUE_ACCENT.get(key, "TEXT"), PALETTE["TEXT"])  # لكنة القيمة
            value.setStyleSheet(
                "color:%s;font-size:16px;font-weight:600;" % accent  # نمط القيمة
            )
            value.setWordWrap(True)  # القيم الطويلة (مثل legIds) تلتفّ بدل الفيضان
            self._fields[key] = value  # تخزين label القيمة للتحديث لاحقًا
            grid.addWidget(caption, r, 0)  # العنوان في (r,0) — يمين تحت RTL
            # القيمة في (r,1) محاذاة نحو العنوان (بادئة تحت RTL) فتلاصقه بفجوة ثابتة.
            value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            grid.addWidget(value, r, 1)
        card_layout.addLayout(grid)  # إضافة الشبكة إلى البطاقة

        root.addWidget(card)  # بطاقة الهوية

        # ملاحظة Read-only أسفل البطاقة (D7).
        self._readonly_note = QLabel(READONLY_NOTE, self)  # ملاحظة Read-only (D7)
        self._readonly_note.setObjectName("SelectedReadonlyNote")
        self._readonly_note.setStyleSheet(
            "color:%s;font-size:12px;" % PALETTE["MUTED"]  # لون مكتوم
        )
        root.addWidget(self._readonly_note)  # أسفل البطاقة

        # ===== قسم التعديل (T12a — s1..s5): كشف تدريجي + صفوف قديم/جديد =======
        # بنية فقط هنا: لا حساب أسعار ولا شبكة ولا تنفيذ (خطوات s2..s6 لاحقًا).
        self._build_edit_section(root)  # قسم التعديل (s1..s5)

        # ===== لوحة حيّة (T12a — s4): السعر الحالي + أعلى إيقاف متاح + زر =====
        self._build_live_panel(root)  # لوحة حيّة (s4)

        # ===== تفعيل إعادة التموضع (T12b — s3): زر + شارة النافذة العارية =====
        self._build_activate_section(root)  # s3: قسم التفعيل — زرّ + شارة النافذة العارية

        root.addStretch(1)

        # الحالة الابتدائية: بلا اختيار — تفريغ الحقول وتصفير الحالة.
        self.clear()

    def _build_edit_section(self, root):
        """يبني قسم التعديل: مفتاح «تفعيل التعديل» + حقلا TP%/SL% (كشف تدريجي)
        + صفوف «القيمة القديمة ↔ القيمة الجديدة» للأسعار الثلاثة (Stop Limit،
        Trigger، TP). القيم الجديدة placeholders «—» حتى ربط الحساب لاحقًا (s2).
        بنية فقط: لا حساب ولا شبكة ولا تنفيذ هنا."""
        edit_card = QFrame(self)
        edit_card.setObjectName("SelectedEditCard")
        edit_card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        edit_card.setStyleSheet(
            "QFrame#SelectedEditCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}"
            % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        edit_layout = QVBoxLayout(edit_card)  # تخطيط عمودي لقسم التعديل
        edit_layout.setContentsMargins(18, 16, 18, 16)
        edit_layout.setSpacing(10)

        # عنوان القسم.
        edit_heading = QLabel("تعديل الأمر", edit_card)
        edit_heading.setObjectName("SelectedEditHeading")
        edit_heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        edit_layout.addWidget(edit_heading)  # عنوان قسم التعديل

        # مفتاح تفعيل التعديل (كشف تدريجي لحقلَي النِّسب TP%/SL%).
        self._edit_toggle = QCheckBox("تفعيل التعديل", edit_card)
        self._edit_toggle.setObjectName("SelectedEditToggle")
        self._edit_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._edit_toggle.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        edit_layout.addWidget(self._edit_toggle)  # مفتاح تفعيل التعديل

        # صف حقلَي النِّسب: TP % و SL % (مخفيّان حتى تفعيل التعديل).
        pct_row = QHBoxLayout()
        pct_row.setSpacing(12)

        self._tp_pct_label = QLabel("نسبة جني الأرباح %", edit_card)  # عنوان TP%
        self._tp_pct_label.setObjectName("SelectedTpPctLabel")
        self._tp_pct_label.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["MUTED"]
        )
        self._tp_pct_edit = QLineEdit(edit_card)  # مدخل TP%
        self._tp_pct_edit.setObjectName("SelectedTpPctEdit")
        self._tp_pct_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._tp_pct_edit.setStyleSheet(
            "background:%s;color:%s;border:1px solid %s;border-radius:6px;"
            "padding:6px 10px;" % (PALETTE["CARD"], PALETTE["TEXT"], PALETTE["BORDER"])
        )
        self._tp_pct_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._tp_pct_edit.setMinimumWidth(90)

        self._sl_pct_label = QLabel("نسبة وقف الخسارة %", edit_card)  # عنوان SL%
        self._sl_pct_label.setObjectName("SelectedSlPctLabel")
        self._sl_pct_label.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["MUTED"]
        )
        self._sl_pct_edit = QLineEdit(edit_card)  # مدخل SL%
        self._sl_pct_edit.setObjectName("SelectedSlPctEdit")
        self._sl_pct_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._sl_pct_edit.setStyleSheet(
            "background:%s;color:%s;border:1px solid %s;border-radius:6px;"
            "padding:6px 10px;" % (PALETTE["CARD"], PALETTE["TEXT"], PALETTE["BORDER"])
        )
        self._sl_pct_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._sl_pct_edit.setMinimumWidth(90)

        pct_row.addWidget(self._tp_pct_label)  # ترتيب عناصر الصف
        pct_row.addWidget(self._tp_pct_edit, 1)
        pct_row.addWidget(self._sl_pct_label)
        pct_row.addWidget(self._sl_pct_edit, 1)
        edit_layout.addLayout(pct_row)  # صف النِّسب

        # حقول النِّسب وعناوينها مخفيّة افتراضيًّا (كشف تدريجي).
        for w in (
            self._tp_pct_label,
            self._tp_pct_edit,
            self._sl_pct_label,
            self._sl_pct_edit,
        ):
            w.setVisible(False)  # تظهر عند تفعيل التعديل

        # ربط المفتاح: إظهار/إخفاء الحقلين وفق حالة التفعيل.
        self._edit_toggle.toggled.connect(self._on_edit_toggled)  # كشف تدريجي

        # صفوف «القيمة القديمة ↔ القيمة الجديدة» للأسعار الثلاثة.
        # القديمة من SelectedOCO؛ الجديدة placeholders «—» (تُملأ في s2).
        old_new_heading = QLabel("القيمة القديمة ↔ القيمة الجديدة", edit_card)  # عنوان الصفوف
        old_new_heading.setObjectName("SelectedOldNewHeading")
        old_new_heading.setStyleSheet(
            "color:%s;font-size:13px;font-weight:600;" % PALETTE["TEXT_SOFT"]
        )
        edit_layout.addWidget(old_new_heading)  # عنوان صفوف قديم/جديد

        # قيم جديدة (placeholders) مكشوفة للخطوات/الاختبارات اللاحقة.
        self._new_stop_limit = self._build_old_new_row(  # صف Stop Limit (قديم/جديد)
            edit_layout, edit_card, "stop_limit", "حد الإيقاف"
        )
        self._new_trigger = self._build_old_new_row(  # صف Trigger
            edit_layout, edit_card, "stop_trigger", "مُشغِّل الإيقاف"
        )
        self._new_tp = self._build_old_new_row(  # صف TP
            edit_layout, edit_card, "tp", "جني الأرباح"
        )

        # s2: تهيئة مرجع الهدف المحدد + ربط المعاينة الحيّة بتغيّر النِّسب (s2/s5)
        self._selected = None  # الهدف المحدد الحالي (SelectedOCO أو None)
        # s5: السعر المرجعي الحيّ المحقون (يُضبط عبر set_current_price؛ T13 لاحقًا)
        self._current_price = None
        self._tp_pct_edit.textChanged.connect(self._update_preview)  # معاينة حيّة (TP%)
        self._sl_pct_edit.textChanged.connect(self._update_preview)  # معاينة حيّة (SL%)

        # s3: مؤشّر الترتيب الصارم حد الإيقاف < المُشغِّل < السعر المرجعي < جني الأرباح
        self._order_indicator = QLabel(EMPTY, edit_card)  # مؤشّر الترتيب الصارم
        self._order_indicator.setObjectName("SelectedOrderIndicator")
        edit_layout.addWidget(self._order_indicator)  # يظهر مع المعاينة

        root.addWidget(edit_card)  # بطاقة قسم التعديل

    def _build_activate_section(self, root):
        """T12b/s3: زر «تفعيل» إعادة التموضع + شارة «النافذة العارية».

        بوابة تأكيد قابلة للحقن (DS1) تسبق أي تنفيذ؛ لا شبكة هنا — كل التنفيذ
        داخل المنفّذ المحقون. الشارة مخفيّة عند البناء وتظهر فقط بين التأكيد
        والحالة النهائية (REPOSITIONING/إلغاء ثم إنشاء)."""
        activate_card = QFrame(self)  # بطاقة قسم التفعيل
        activate_card.setObjectName("SelectedActivateCard")
        activate_card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        activate_card.setStyleSheet(
            "QFrame#SelectedActivateCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}"
            % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        activate_layout = QVBoxLayout(activate_card)
        activate_layout.setContentsMargins(18, 16, 18, 16)
        activate_layout.setSpacing(10)

        # شارة النافذة العارية (تحذير AMBER) — مخفيّة افتراضيًّا.
        self._naked_banner = QLabel(NAKED_WINDOW_TEXT, activate_card)
        self._naked_banner.setObjectName("SelectedNakedWindowBanner")
        self._naked_banner.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._naked_banner.setWordWrap(True)
        self._naked_banner.setStyleSheet(
            "color:%s;background:%s;border:1px solid %s;border-radius:8px;"
            "padding:8px 12px;font-size:13px;font-weight:700;"
            % (PALETTE["AMBER"], PALETTE["CARD"], PALETTE["AMBER"])
        )
        self._naked_banner.setVisible(False)  # مخفيّة عند البناء (مطلب s3)
        activate_layout.addWidget(self._naked_banner)  # الشارة (مخفيّة)

        # حالة/رسالة التفعيل (نجاح أو رسالة humanize العربية).
        self._activate_status = QLabel(EMPTY, activate_card)
        self._activate_status.setObjectName("SelectedActivateStatus")
        self._activate_status.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._activate_status.setWordWrap(True)
        self._activate_status.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        activate_layout.addWidget(self._activate_status)  # سطر الحالة

        # زر التفعيل.
        self.activate_button = QPushButton("تفعيل", activate_card)
        self.activate_button.setObjectName("SelectedActivateButton")
        self.activate_button.clicked.connect(self._on_activate_clicked)
        activate_layout.addWidget(self.activate_button)  # زر التفعيل

        root.addWidget(activate_card)  # بطاقة قسم التفعيل

    def _default_confirm(self, text):
        """بوابة تأكيد افتراضية عبر QMessageBox (DS1). تُرجع True فقط عند «نعم»."""
        answer = QMessageBox.question(
            self,
            CONFIRM_TITLE,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_activate_clicked(self, *args):
        """T12b/s3: بوابة تأكيد ثم تنفيذ إعادة التموضع عبر المنفّذ المحقون.

        على الرفض: لا تنفيذ ولا شارة (FakeSafeExecutor.calls يبقى فارغًا).
        على القبول: إظهار شارة النافذة العارية ثم submit عبر الرَنَر (أو
        متزامنًا بلا رَنَر) — تُخفى الشارة في كلا المسارين النهائيين.
        لا شبكة هنا مطلقًا."""
        # حل دالة التنفيذ: execute_cb لها الأولويّة، ثم executor.execute.
        execute = self._execute_cb or (
            self._executor.execute if self._executor is not None else None
        )
        selected = getattr(self, "_selected", None)
        if execute is None or selected is None:  # حارس: لا تنفيذ بلا مصدر/هدف
            return
        # G1.13: لا تفعيل إعادة تموضع على مرشّح تحويل (أمر مستقل بلا OCO بعد).
        if getattr(selected, "is_convert_candidate", False):
            self._activate_status.setText(i18n.translate_for_current("سيُحوَّل إلى OCO — يلزم التحويل أولًا"))
            return
        # بوابة التأكيد: على الرفض لا تنفيذ ولا شارة.
        if not self._confirm_cb(i18n.translate_for_current(CONFIRM_TEXT)):
            return
        # اشتقاق وسائط التنفيذ من حالة الشاشة (يطابق تحليل T12a للنِّسب).
        order_list_id = selected.order_list_id
        tp_pct = self._tp_pct_edit.text().strip()  # نصّ TP% كما في _update_preview
        sl_pct = self._sl_pct_edit.text().strip()  # نصّ SL% كما في _update_preview
        reference_price = (
            self._current_price
            if self._current_price is not None
            else getattr(selected, "current_price", None)
        )
        # إظهار شارة النافذة العارية + تعطيل الزر أثناء التنفيذ.
        self._naked_banner.setVisible(True)
        self.activate_button.setEnabled(False)
        self._activate_status.setText(EMPTY)
        # تنفيذ عبر الرَنَر (نفس نمط refresh) أو متزامنًا بلا رَنَر.
        if self.runner:
            self.runner.submit(
                execute,
                order_list_id,
                tp_pct,
                sl_pct,
                reference_price,
                on_result=self._on_activate_result,
                on_error=self._on_activate_error,
            )
        else:
            try:  # مسار متزامن (اختبارات)
                self._on_activate_result(
                    execute(order_list_id, tp_pct, sl_pct, reference_price)
                )
            except Exception as exc:  # noqa: BLE001 — يُوجَّه إلى humanize
                self._on_activate_error(exc)

    def _on_activate_result(self, result):
        """رد نجاح/فشل نهائي: إخفاء الشارة، إعادة تفعيل الزر، ثم رسالة مناسبة."""
        self._naked_banner.setVisible(False)  # الحالة النهائية: إخفاء الشارة
        self.activate_button.setEnabled(True)
        state = getattr(result, "state", None)  # قد يكون Enum أو سلسلة
        state_name = getattr(state, "value", None) or getattr(state, "name", None) or state
        if state_name == _STATE_SUCCESS:
            new_id = getattr(result, "new_order_list_id", None)
            if new_id is not None:
                self._activate_status.setText(i18n.translate_for_current("✓ تم التفعيل — الأمر الجديد:") + " %s" % new_id)
            else:
                self._activate_status.setText(i18n.translate_for_current("✓ تم التفعيل بنجاح"))
        else:  # ABORTED / FAILED_NEEDS_ATTENTION أو أي حالة غير نجاح
            self._activate_status.setText(humanize(result))  # رسالة عربية موحّدة
        # خُطّاف اختياري (05): إخطار التطبيق بنتيجة التنفيذ دون كسر المسار القائم.
        if self._on_execution_result is not None:
            try:
                self._on_execution_result(result, self._selected)
            except Exception:
                pass

    def _on_activate_error(self, exc):
        """رد استثناء: إخفاء الشارة، إعادة تفعيل الزر، ورسالة humanize العربية."""
        self._naked_banner.setVisible(False)  # الحالة النهائية: إخفاء الشارة
        self.activate_button.setEnabled(True)
        self._activate_status.setText(humanize(exc))  # رسالة عربية موحّدة
        # خُطّاف اختياري (05): تمرير كائن الخطأ كما هو دون كسر المسار القائم.
        if self._on_execution_result is not None:
            try:
                self._on_execution_result(exc, self._selected)
            except Exception:
                pass

    def set_current_price(self, price):  # s5
        """خُطّاف حقن السعر المرجعي الحيّ (يستدعيه T13 لاحقًا). لا شبكة في خيط الواجهة."""
        self._current_price = price  # حفظ السعر المرجعي المحقون
        self._update_preview()       # تحديث المعاينة فقط — لا شبكة

    def set_executor(self, executor):
        """G1.18: حقن/تحديث المنفّذ (SafeExecutor) بعد نجاح الاتصال — تخزين فقط.
        None-safe؛ لا تنفيذ تلقائي ولا شبكة هنا (يُستهلك في _on_activate_clicked)."""
        self._executor = executor

    def set_execute_cb(self, cb):
        """G1.18: حقن/تحديث دالة التنفيذ البديلة (لها الأولويّة على executor) —
        تخزين فقط. None-safe؛ لا تنفيذ تلقائي ولا شبكة هنا."""
        self._execute_cb = cb

    def _build_old_new_row(self, edit_layout, edit_card, key, label):
        """صف واحد: عنوان + القيمة القديمة + سهم ↔ + القيمة الجديدة (placeholder).
        يُخزّن label القديم في self._old_fields[key] ويعيد label الجديد."""
        row = QHBoxLayout()
        row.setSpacing(10)

        caption = QLabel(label, edit_card)
        caption.setObjectName("SelectedOldNewCaption_%s" % key)
        caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        # G1.4 (REWORK): عرض أدنى موحّد فتصطف العناوين، بلا Fixed sizePolicy.
        caption.setMinimumWidth(150)

        old_value = QLabel(EMPTY, edit_card)
        old_value.setObjectName("SelectedOldValue_%s" % key)
        old_value.setStyleSheet(
            "color:%s;font-size:15px;font-weight:600;" % PALETTE["TEXT"]
        )
        old_value.setMinimumWidth(90)
        old_value.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._old_fields[key] = old_value

        arrow = QLabel("↔", edit_card)
        arrow.setObjectName("SelectedOldNewArrow_%s" % key)
        arrow.setStyleSheet("color:%s;font-size:14px;" % PALETTE["MUTED"])

        new_value = QLabel(EMPTY, edit_card)
        new_value.setObjectName("SelectedNewValue_%s" % key)
        new_value.setStyleSheet(
            "color:%s;font-size:15px;font-weight:600;" % PALETTE["TEAL"]
        )
        new_value.setMinimumWidth(90)
        new_value.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        row.addWidget(caption)
        # G1.4 (REWORK): الخانتان تتوسّعان (stretch=1) لإظهار الأرقام كاملةً بدل
        # انكماشهما؛ أُزيل addStretch الخارجي الذي كان يبقيهما ملاصقتين ومنكمشتين.
        row.addWidget(old_value, 1)
        row.addWidget(arrow)
        row.addWidget(new_value, 1)
        edit_layout.addLayout(row)
        return new_value

    def _on_edit_toggled(self, checked):
        """كشف تدريجي: إظهار/إخفاء حقلَي TP%/SL% وعناوينهما وفق حالة التفعيل."""
        for w in (
            self._tp_pct_label,
            self._tp_pct_edit,
            self._sl_pct_label,
            self._sl_pct_edit,
        ):
            w.setVisible(bool(checked))
        self._update_preview()

    def _build_live_panel(self, root):
        """s4: لوحة حيّة — السعر الحالي + أعلى إيقاف متاح + زر حسابه.
        الحساب نقيّ عبر pricing.max_available_stop؛ بلا شبكة (D14: لا قيمة قبل current_price)."""
        live_card = QFrame(self)  # بطاقة اللوحة الحيّة (s4)
        live_card.setObjectName("SelectedLiveCard")
        live_layout = QVBoxLayout(live_card)

        title = QLabel("اللوحة الحيّة", live_card)  # عنوان اللوحة
        title.setObjectName("SelectedLiveTitle")
        live_layout.addWidget(title)

        price_row = QHBoxLayout()
        price_row.addWidget(QLabel("السعر الحالي:", live_card))
        self._live_current_price = QLabel(EMPTY, live_card)  # السعر الحالي المعروض
        self._live_current_price.setObjectName("SelectedLiveCurrentPrice")
        self._live_current_price.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._live_current_price.setMinimumWidth(90)
        price_row.addWidget(self._live_current_price, 1)
        live_layout.addLayout(price_row)

        stop_row = QHBoxLayout()
        stop_row.addWidget(QLabel("أعلى إيقاف متاح:", live_card))
        self._live_max_stop = QLabel(EMPTY, live_card)  # أعلى إيقاف متاح
        self._live_max_stop.setObjectName("SelectedLiveMaxStop")
        self._live_max_stop.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._live_max_stop.setMinimumWidth(90)
        stop_row.addWidget(self._live_max_stop, 1)
        live_layout.addLayout(stop_row)

        self._max_stop_btn = QPushButton("أقصى إيقاف متاح", live_card)  # زر الحساب
        self._max_stop_btn.setObjectName("SelectedMaxStopButton")
        self._max_stop_btn.clicked.connect(self._on_max_available_stop)  # حساب عند الضغط
        live_layout.addWidget(self._max_stop_btn)  # زر أعلى إيقاف متاح

        root.addWidget(live_card)  # إضافة اللوحة الحيّة إلى الجذر

    def _on_max_available_stop(self, *args):
        """s4: يحسب أعلى إيقاف متاح عبر pricing.max_available_stop(reference, tick) ويعرضه.
        السعر المرجعي هو المحقون عبر set_current_price ثم fallback إلى الهدف المحدد.
        لا قيمة قبل توفّر السعر المرجعي الحقيقي (D14) أو tick_size."""
        selected = getattr(self, "_selected", None)
        if selected is None:  # لا هدف محدد
            self._live_max_stop.setText(EMPTY)
            return
        # s5: السعر المرجعي المحقون له الأولويّة، ثم fallback إلى الهدف المحدد
        reference = (
            self._current_price
            if self._current_price is not None
            else getattr(selected, "current_price", None)
        )
        filters = getattr(selected, "filters", None)
        tick = getattr(filters, "tick_size", None) if filters is not None else None
        if reference is None or tick is None:  # D14: لا قيمة قبل توفّر سعر حقيقي
            self._live_max_stop.setText(EMPTY)
            return
        try:
            value = max_available_stop(reference, tick)  # حساب نقيّ بلا شبكة
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            self._live_max_stop.setText(EMPTY)  # مدخل غير صالح: تفريغ آمن
            return
        self._live_max_stop.setText(fmt(value))  # عرض النتيجة

    def _update_preview(self, *args):
        """s2: معاينة الأسعار الثلاث حيًّا من TP%/SL% + السعر المرجعي.
        حساب نقيّ عبر pricing.compute_levels بلا أي شبكة؛ ولا معاينة قبل
        توفّر سعر مرجعي حقيقي (المحقون عبر set_current_price ثم fallback إلى
        SelectedOCO.current_price) وفق D14."""
        new_cells = (self._new_stop_limit, self._new_trigger, self._new_tp)  # خلايا المعاينة

        def _blank():  # تفريغ آمن للمعاينة والمؤشّر
            for cell in new_cells:
                cell.setText(EMPTY)
            self._order_indicator.setText(EMPTY)
            self._order_indicator.setProperty("state", "")  # إعادة ضبط حالة المؤشّر
            self._order_indicator.setStyleSheet("")

        selected = getattr(self, "_selected", None)
        if selected is None or not self._edit_toggle.isChecked():  # لا معاينة بلا تفعيل
            _blank()
            return
        # s5: السعر المرجعي المحقون له الأولويّة، ثم fallback إلى الهدف المحدد
        reference = (
            self._current_price
            if self._current_price is not None
            else getattr(selected, "current_price", None)
        )
        if reference is None:            # D14: لا معاينة قبل توفّر سعر حقيقي
            _blank()
            return
        filters = getattr(selected, "filters", None)
        tick = getattr(filters, "tick_size", None) if filters is not None else None
        if tick is None:  # لا معاينة بلا tick_size
            _blank()
            return
        tp_text = self._tp_pct_edit.text().strip()  # النسبة المئوية للربح
        sl_text = self._sl_pct_edit.text().strip()
        if not tp_text or not sl_text:  # لا معاينة قبل ملء الحقلين
            _blank()
            return
        try:  # حساب نقيّ بلا شبكة عبر pricing.compute_levels
            tp, trigger, stop_limit = compute_levels(reference, tp_text, sl_text, tick)
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            _blank()  # مدخل غير صالح: تفريغ آمن للمعاينة
            return
        self._new_tp.setText(fmt(tp))  # حساب نقيّ بلا شبكة
        self._new_trigger.setText(fmt(trigger))
        self._new_stop_limit.setText(fmt(stop_limit))  # عرض القيم الجديدة المحسوبة
        # s3: تحقّق الترتيب الصارم Stop Limit < Trigger < Last(reference) < TP
        ordered = stop_limit < trigger < reference < tp  # التحقّق النقيّ
        if ordered:
            self._order_indicator.setText(
                i18n.translate_for_current("✓ الترتيب الصارم سليم: حد الإيقاف < المُشغِّل < السعر المرجعي < جني الأرباح")
            )
            self._order_indicator.setProperty("state", "ok")  # حالة سليمة
            self._order_indicator.setStyleSheet("color: #2e7d32;")
        else:
            self._order_indicator.setText(
                i18n.translate_for_current("✗ مخالفة الترتيب الصارم: يلزم حد الإيقاف < المُشغِّل < السعر المرجعي < جني الأرباح")
            )
            self._order_indicator.setProperty("state", "bad")  # حالة مخالفة
            self._order_indicator.setStyleSheet("color: #c62828;")

    def set_selected(self, selected):
        """عرض هوية OCO المحدد (SelectedOCO) — أو التفريغ عند None."""
        if selected is None:
            self._selected = None  # إلغاء الاختيار
            self._current_price = None
            self.clear()
            for cell in (self._new_stop_limit, self._new_trigger, self._new_tp):
                cell.setText(EMPTY)
            self._live_current_price.setText(EMPTY)
            self._live_max_stop.setText(EMPTY)  # تفريغ اللوحة الحيّة عند إلغاء الاختيار
            self._naked_banner.setVisible(False)  # إخفاء شارة النافذة العارية (s3)
            self._activate_status.setText(EMPTY)  # تفريغ سطر حالة التفعيل
            self.activate_button.setEnabled(True)  # إعادة تفعيل زر التفعيل
            return
        leg_ids = " / ".join(str(x) for x in (selected.leg_ids or [])) or EMPTY  # legs
        # G1.13: مرشّح تحويل (أمر مستقل) بلا orderListId بعد — تلميح عربي بدل None.
        if getattr(selected, "is_convert_candidate", False) or selected.order_list_id is None:
            src = getattr(selected, "source_order_type", None)
            order_list_display = i18n.translate_for_current("سيُحوَّل إلى OCO") + (f" ({src})" if src else "")
        else:
            order_list_display = str(selected.order_list_id)
        values = {
            "orderListId": order_list_display,
            "symbol": selected.symbol or EMPTY,
            "quantity": fmt(selected.quantity),
            "tp": fmt(selected.tp),
            "stopTrigger": fmt(selected.stop_trigger),
            "stopLimit": fmt(selected.stop_limit),
            "legIds": leg_ids,
            "status": selected.status or EMPTY,
        }
        for key, value in values.items():
            self._fields[key].setText(value)  # تعبئة بطاقة الهوية
        # قفل الكمية (D7): يُعرض ما لم يُصرَّح بغير ذلك.
        if getattr(selected, "quantity_locked", True):
            self._lock.setVisible(True)  # الكمية مقفولة افتراضيًّا
        else:
            self._lock.setVisible(False)
        # تعبئة القيم القديمة في قسم التعديل (صفوف قديم/جديد) — مع حماية None.
        self._old_fields["stop_limit"].setText(
            fmt(getattr(selected, "stop_limit", None))  # stop_limit القديم
        )
        self._old_fields["stop_trigger"].setText(
            fmt(getattr(selected, "stop_trigger", None))  # trigger القديم
        )
        self._old_fields["tp"].setText(fmt(getattr(selected, "tp", None)))  # tp القديم
        self._note.setVisible(False)
        self._selected = selected  # تخزين الهدف قبل الحقن ليراه _update_preview (ترتيب مهمّ)
        # s3: عند اختيار جديد نبدأ من حالة نظيفة — نُخفي الشارة، ونُفرّغ سطر الحالة، ونعيد تمكين زرّ التفعيل.
        self._naked_banner.setVisible(False)
        self._activate_status.setText(EMPTY)
        self.activate_button.setEnabled(True)
        # s5: حقن السعر المرجعي عبر الخُطّاف بدل قراءته مباشرة (يستدعي _update_preview)
        self.set_current_price(getattr(selected, "current_price", None))
        self._live_current_price.setText(fmt(getattr(selected, "current_price", None)))  # عرض السعر الخام من الهدف
        self._live_max_stop.setText(EMPTY)

    def clear(self):
        """تفريغ كل الحقول إلى '—' وإظهار ملاحظة "لم يُختَر أمر" (مع تصفير السعر المرجعي)."""
        for value in self._fields.values():
            value.setText(EMPTY)  # تفريغ حقول الهوية الثمانية
        # تفريغ القيم القديمة/الجديدة في قسم التعديل.
        for old_value in self._old_fields.values():
            old_value.setText(EMPTY)  # القيم القديمة
        for new_value in (self._new_stop_limit, self._new_trigger, self._new_tp):
            new_value.setText(EMPTY)  # القيم الجديدة placeholders
        self._lock.setVisible(False)   # إخفاء شارة القفل
        self._note.setVisible(True)    # إظهار ملاحظة "لم يُختَر أمر"
        # s5: إعادة ضبط السعر المرجعي المحقون عند التفريغ (لا شبكة)
        self._current_price = None
        # T12b/s3: إخفاء شارة النافذة العارية + تفريغ سطر حالة التفعيل + إعادة تفعيل الزر.
        # (يُستدعى clear() ابتدائيًّا قبل بناء قسم التفعيل؛ لذا نتحقّق من وجود العناصر.)
        if hasattr(self, "_naked_banner"):
            self._naked_banner.setVisible(False)
        if hasattr(self, "_activate_status"):
            self._activate_status.setText(EMPTY)
        if hasattr(self, "activate_button"):
            self.activate_button.setEnabled(True)

    def refresh(self, build_fn=None):
        """جلب SelectedOCO عبر build_fn وعرضه.

        مع runner يُنفَّذ على خيط منفصل؛ بلا runner يُنفَّذ متزامنًا (اختبارات).
        """
        fn = build_fn or self.build_fn
        if fn is None:  # بلا مصدر جلب
            return
        if self.runner:
            self.runner.submit(fn, on_result=self.set_selected)  # خيط منفصل
        else:
            self.set_selected(fn())  # متزامن للاختبارات
