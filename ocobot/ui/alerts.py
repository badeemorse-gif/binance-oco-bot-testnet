"""شاشة تنبيهات Telegram (Alerts) — G1.25 (step_5_ui_section).

قسم واجهة لإدارة إشعارات Telegram أحادية الاتجاه (read-only channel):
  - حساب بوت واحد (إضافة/حذف، قابل لإعادة الإضافة) مع تحقّق عبر getMe.
  - مستلمون متعددون (chat_id) بإضافة/حذف فردي أو جماعي (ExtendedSelection).
  - checkbox تفعيل/تعطيل يُظهر الكلمتين الحرفيتين Enabled / Disabled.
  - تحقّق بجوار كل حقل + زرّ إرسال اختباري (confirm-via-successful-test-send).
  - نص إرشادي مثبّت في الأسفل بثلاث نقاط مرقّمة.

قيود معمارية (مطابقة لقرار الجلسة + DoD):
  * كلّ نداء شبكي (التحقّق getMe، الإرسال الاختباري) يمرّ حصريًّا عبر
    ``runner.submit(fn, on_result=..., on_error=...)`` ويُنفَّذ داخل دالة الخلفية
    ``fn`` فقط — لا شبكة متزامنة على خيط الواجهة إطلاقًا (يحترم حارس الواجهة
    ضدّ النداءات الشبكية المباشرة: لا شبكة مباشرة/REST هنا).
  * ``TelegramClient`` يُستورَد من طبقة التنبيهات ويُنشأ/يُستدعى داخل خيط العامل
    فقط؛ الوحدة هنا لا تؤدّي أي IO شبكي بذاتها.
  * التخزين عبر ``AlertsStore`` (مسارات افتراضية) — إعدادات JSON + توكِن سرّي.

RTL + ثيم داكن عبر PALETTE (D15)، على نمط بقية الشاشات. تُسجَّل تحت المفتاح
``09_alerts``.
"""

from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QAbstractItemView,
)
from .theme import PALETTE
from . import i18n
from ocobot.alerts.storage import AlertsStore
from ocobot.alerts.telegram_client import TelegramClient, TelegramError


# الكلمتان الحرفيّتان المطلوبتان في DoD (إنجليزية حرفية، لا تُترجَم).
ENABLED_WORD = "Enabled"
DISABLED_WORD = "Disabled"
# كلمة التحقّق الحرفية + توضيح معناها (valid = Telegram getMe accepted this token).
VALID_WORD = "valid"
INVALID_WORD = "invalid"
VALID_TOOLTIP = "valid = Telegram getMe accepted this token"

# رسالة اختبارية قصيرة تُرسَل عبر زرّ «إرسال رسالة اختبارية».
_TEST_MESSAGE = "OCOBot: رسالة اختبارية (test message)"


def _is_valid_chat_id(text):
    """صيغة chat_id صالحة: غير فارغ، عدد صحيح، مع '-' اختياري في البداية.

    (chat_id للمجموعات/القنوات قد يبدأ بـ '-'. لا كسور ولا أحرف.)
    """
    if text is None:
        return False
    value = text.strip()
    if not value:
        return False
    if value[0] == "-":
        value = value[1:]
    return value.isdigit() and len(value) > 0


class AlertsScreen(QWidget):
    """قسم تنبيهات Telegram — نفس نمط الحقن الذي تستخدمه الشاشات الشقيقة.

    الحقن (اختياري/متسامح، كبقية الشاشات):
      - ``runner``: ``AsyncRunner`` لتشغيل كلّ الشبكة خارج خيط الواجهة. بلا runner
        تُعطَّل أزرار الشبكة (لا تنفيذ متزامن للشبكة إطلاقًا).
      - ``store``: ``AlertsStore`` اختياري (للاختبار)؛ وإلا يُنشأ بمسارات افتراضية.
    """

    def __init__(self, parent=None, runner=None, store=None):
        super().__init__(parent)
        self.screen_key = "09_alerts"
        self.setObjectName("Screen_09_alerts")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self._runner = runner
        # AlertsStore الخاص بالشاشة (مسارات افتراضية) ما لم يُحقَن غيره.
        self._store = store if store is not None else AlertsStore()

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة الشاشة.
        self.heading = QLabel("تنبيهات Telegram", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        self._build_bot_section(root)
        self._build_recipients_section(root)
        self._build_enable_section(root)
        self._build_test_section(root)

        # يدفع القسم الإرشادي إلى الأسفل.
        root.addStretch(1)
        self._build_instructions(root)

        # تعبئة أوّليّة من التخزين (قراءة فقط، بلا شبكة).
        self.reload_settings()

    # ------------------------------------------------------------------
    # القسم 1: حساب بوت واحد (توكِن مُقنَّع + إضافة/حذف + حالة valid/invalid)
    # ------------------------------------------------------------------
    def _build_bot_section(self, root):
        self.bot_section = QLabel("حساب البوت", self)
        self.bot_section.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.bot_section)

        row = QHBoxLayout()
        row.setSpacing(10)

        # إدخال التوكِن مُقنَّع (password echo) — لا يُسجَّل التوكِن مطلقًا.
        self.token_input = QLineEdit(self)
        self.token_input.setObjectName("AlertsTokenInput")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("توكِن البوت من @BotFather")
        self.token_input.setStyleSheet(self._field_style())
        row.addWidget(self.token_input, 1)

        self.add_bot_button = QPushButton("إضافة البوت", self)
        self.add_bot_button.setObjectName("AlertsAddBotButton")
        self.add_bot_button.clicked.connect(self._on_add_bot_clicked)
        row.addWidget(self.add_bot_button)

        self.remove_bot_button = QPushButton("حذف البوت", self)
        self.remove_bot_button.setObjectName("AlertsRemoveBotButton")
        self.remove_bot_button.clicked.connect(self._on_remove_bot_clicked)
        row.addWidget(self.remove_bot_button)

        root.addLayout(row)

        # سطر الحالة: اسم البوت + مؤشّر valid/invalid مع توضيح معنى valid.
        status_row = QHBoxLayout()
        status_row.setSpacing(10)

        self.bot_status_label = QLabel("", self)
        self.bot_status_label.setObjectName("AlertsBotStatus")
        self.bot_status_label.setWordWrap(True)
        self.bot_status_label.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        status_row.addWidget(self.bot_status_label, 1)

        self.bot_valid_label = QLabel("", self)
        self.bot_valid_label.setObjectName("AlertsBotValid")
        # توضيح معنى valid (DoD): valid = Telegram getMe accepted this token.
        self.bot_valid_label.setToolTip(VALID_TOOLTIP)
        status_row.addWidget(self.bot_valid_label)

        root.addLayout(status_row)

    # ------------------------------------------------------------------
    # القسم 2: مستلمون متعددون (chat_id + قائمة ExtendedSelection + حذف)
    # ------------------------------------------------------------------
    def _build_recipients_section(self, root):
        self.recipients_section = QLabel("المستلمون", self)
        self.recipients_section.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.recipients_section)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.chat_id_input = QLineEdit(self)
        self.chat_id_input.setObjectName("AlertsChatIdInput")
        self.chat_id_input.setPlaceholderText("chat_id (رقم؛ قد يبدأ بـ -)")
        self.chat_id_input.setStyleSheet(self._field_style())
        self.chat_id_input.textChanged.connect(self._on_chat_id_text_changed)
        row.addWidget(self.chat_id_input, 1)

        self.add_recipient_button = QPushButton("إضافة مستلم", self)
        self.add_recipient_button.setObjectName("AlertsAddRecipientButton")
        self.add_recipient_button.clicked.connect(self._on_add_recipient_clicked)
        row.addWidget(self.add_recipient_button)

        root.addLayout(row)

        # تحقّق صيغة chat_id بجوار الحقل (inline).
        self.chat_id_valid_label = QLabel("", self)
        self.chat_id_valid_label.setObjectName("AlertsChatIdValid")
        self.chat_id_valid_label.setStyleSheet(
            "color:%s;font-size:12px;" % PALETTE["TEXT_SOFT"]
        )
        root.addWidget(self.chat_id_valid_label)

        # قائمة المستلمين (اختيار متعدّد ExtendedSelection).
        self.recipients_list = QListWidget(self)
        self.recipients_list.setObjectName("AlertsRecipientsList")
        self.recipients_list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.recipients_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.recipients_list.setStyleSheet(
            "QListWidget{background:%s;border:1px solid %s;border-radius:12px;"
            "color:%s;padding:6px;}"
            % (PALETTE["CARD"], PALETTE["BORDER"], PALETTE["TEXT"])
        )
        root.addWidget(self.recipients_list, 1)

        self.remove_recipients_button = QPushButton("حذف المحدد", self)
        self.remove_recipients_button.setObjectName("AlertsRemoveRecipientsButton")
        self.remove_recipients_button.clicked.connect(
            self._on_remove_recipients_clicked
        )
        root.addWidget(self.remove_recipients_button)

    # ------------------------------------------------------------------
    # القسم 3: تفعيل/تعطيل + تسمية Enabled/Disabled الحرفية
    # ------------------------------------------------------------------
    def _build_enable_section(self, root):
        row = QHBoxLayout()
        row.setSpacing(10)

        self.enable_checkbox = QCheckBox("تفعيل التنبيهات", self)
        self.enable_checkbox.setObjectName("AlertsEnableCheckbox")
        self.enable_checkbox.toggled.connect(self._on_enabled_toggled)
        row.addWidget(self.enable_checkbox)

        # تسمية الحالة الحرفية: Enabled عند التفعيل، Disabled عند التعطيل.
        self.enable_state_label = QLabel(DISABLED_WORD, self)
        self.enable_state_label.setObjectName("AlertsEnableStateLabel")
        self.enable_state_label.setStyleSheet(
            "color:%s;font-size:13px;font-weight:700;" % PALETTE["TEXT_SOFT"]
        )
        row.addWidget(self.enable_state_label)

        row.addStretch(1)
        root.addLayout(row)

    # ------------------------------------------------------------------
    # القسم 4: إرسال رسالة اختبارية (confirm-via-successful-test-send)
    # ------------------------------------------------------------------
    def _build_test_section(self, root):
        row = QHBoxLayout()
        row.setSpacing(10)

        self.test_button = QPushButton("إرسال رسالة اختبارية", self)
        self.test_button.setObjectName("AlertsTestButton")
        self.test_button.clicked.connect(self._on_test_clicked)
        row.addWidget(self.test_button)

        self.test_status_label = QLabel("", self)
        self.test_status_label.setObjectName("AlertsTestStatus")
        self.test_status_label.setWordWrap(True)
        self.test_status_label.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        row.addWidget(self.test_status_label, 1)

        root.addLayout(row)

    # ------------------------------------------------------------------
    # القسم الإرشادي المثبّت في الأسفل (ثلاث نقاط مرقّمة)
    # ------------------------------------------------------------------
    def _build_instructions(self, root):
        text = (
            "إرشادات الإعداد:\n"
            "1) أنشئ بوتًا عبر @BotFather في Telegram واحصل على التوكِن (token)؛ "
            "أرسل /newbot واتبع الخطوات، ثم انسخ التوكِن.\n"
            "2) لكي يحصل المستلم على chat_id الخاص به: يبدأ محادثة مع البوت "
            "بالضغط Start، ثم يستخدم مساعدًا مثل @userinfobot أو عبر getUpdates "
            "للحصول على chat_id.\n"
            "3) خطوات الإضافة هنا: الصق التوكِن واضغط «إضافة البوت»، ثم أضِف "
            "chat_id لكل مستلم عبر «إضافة مستلم»، فعِّل التنبيهات، وأرسل رسالة "
            "اختبارية للتأكّد."
        )
        self.instructions_label = QLabel(text, self)
        self.instructions_label.setObjectName("AlertsInstructions")
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setStyleSheet(
            "color:%s;font-size:12px;background:%s;border:1px solid %s;"
            "border-radius:10px;padding:12px 16px;"
            % (PALETTE["TEXT_SOFT"], PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        root.addWidget(self.instructions_label)

    # ------------------------------------------------------------------
    # أنماط مشتركة
    # ------------------------------------------------------------------
    def _field_style(self):
        return (
            "QLineEdit{background:%s;border:1px solid %s;border-radius:10px;"
            "color:%s;padding:8px 12px;}"
            % (PALETTE["CARD"], PALETTE["BORDER"], PALETTE["TEXT"])
        )

    def _set_valid_label(self, label, is_valid, extra=""):
        """يضبط تسمية حالة إلى الكلمة الحرفية valid/invalid مع تلوين."""
        word = VALID_WORD if is_valid else INVALID_WORD
        color = PALETTE["GREEN"] if is_valid else PALETTE["RED"]
        label.setText((word + (" — " + extra if extra else "")))
        label.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % color)

    # ------------------------------------------------------------------
    # تحميل/عكس الإعدادات (قراءة فقط، بلا شبكة)
    # ------------------------------------------------------------------
    def retranslate_i18n(self):
        """يعيد عرض تسميات الحالة باللغة الفعّالة (عند تبديل اللغة)."""
        self.reload_settings()

    def reload_settings(self):
        """يعيد قراءة إعدادات AlertsStore ويعكسها في الواجهة (بلا شبكة)."""
        settings = self._store.load()

        # حالة البوت.
        bot = settings.bot
        bot_present = bool(bot is not None and getattr(bot, "present", False))
        if bot_present:
            username = getattr(bot, "username", "") or ""
            shown = ("@" + username) if username else "(بوت مُضاف)"
            self.bot_status_label.setText(i18n.translate_for_current("البوت: %s") % shown)
            # بوت مُضاف = توكِن سبق أن قبِله getMe ⇒ valid.
            self._set_valid_label(self.bot_valid_label, True)
            self.token_input.clear()
            self.token_input.setEnabled(False)
            self.add_bot_button.setEnabled(False)
            self.remove_bot_button.setEnabled(True)
        else:
            self.bot_status_label.setText(i18n.translate_for_current("لا يوجد بوت مُضاف بعد."))
            self.bot_valid_label.setText("")
            self.token_input.setEnabled(True)
            self.add_bot_button.setEnabled(self._runner is not None)
            self.remove_bot_button.setEnabled(False)

        # قائمة المستلمين.
        self.recipients_list.clear()
        for chat_id in self._store.recipients_provider():
            self._append_recipient_item(chat_id)

        # حالة التفعيل + تسمية Enabled/Disabled الحرفية.
        enabled = bool(settings.enabled)
        # نضبط دون إطلاق set_enabled مجددًا (blockSignals) لأنها مجرد قراءة.
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.blockSignals(False)
        self._update_enabled_label(enabled)

        # أزرار الشبكة تتطلّب runner (لا شبكة متزامنة).
        self.test_button.setEnabled(self._runner is not None)

    def _append_recipient_item(self, chat_id):
        chat_id = str(chat_id)
        item = QListWidgetItem(chat_id)
        # نخزّن chat_id الخام في UserRole لاستعماله عند الحذف.
        item.setData(Qt.ItemDataRole.UserRole, chat_id)
        self.recipients_list.addItem(item)
        # G1.35: صفّ لكل مستلم بزرّ «حذف» فردي يزيله فورًا من التخزين والواجهة.
        row = QWidget(self.recipients_list)
        row.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(6, 2, 6, 2)
        row_lay.setSpacing(8)
        id_label = QLabel(chat_id, row)
        id_label.setStyleSheet("color:%s;font-size:13px;" % PALETTE["TEXT"])
        row_lay.addWidget(id_label, 1)
        del_button = QPushButton(i18n.translate_for_current("حذف"), row)
        del_button.setObjectName("AlertsDeleteRecipientButton")
        del_button.setProperty("chat_id", chat_id)
        del_button.clicked.connect(
            lambda _checked=False, cid=chat_id: self._on_delete_recipient(cid)
        )
        row_lay.addWidget(del_button, 0)
        item.setSizeHint(row.sizeHint())
        self.recipients_list.setItemWidget(item, row)

    def _on_delete_recipient(self, chat_id):
        """G1.35: حذف مستلم واحد فورًا من التخزين الدائم ثم تحديث قائمة الواجهة.

        ``Notifier`` يقرأ ``recipients_provider`` حيًّا عند كل إرسال، فإزالة المستلم
        من التخزين تمنع وصول أي إشعار إليه بعد الحذف — دون لمس منطق الإرسال/التوقيع/
        التنسيق المختوم ولا hot_path.
        """
        try:
            self._store.remove_recipients([str(chat_id)])
        except Exception:
            pass
        self.reload_settings()

    def _update_enabled_label(self, enabled):
        """يُظهر الكلمة الحرفية Enabled عند التفعيل وDisabled عند التعطيل."""
        self.enable_state_label.setText(ENABLED_WORD if enabled else DISABLED_WORD)

    # ------------------------------------------------------------------
    # القسم 1: مُعالِجات البوت
    # ------------------------------------------------------------------
    def _on_add_bot_clicked(self, *args):
        token = self.token_input.text().strip()
        if not token:
            self._set_valid_label(
                self.bot_valid_label, False, i18n.translate_for_current("الصق توكِن البوت أولًا")
            )
            return
        if self._runner is None:
            # لا شبكة متزامنة على خيط الواجهة إطلاقًا.
            self._set_valid_label(
                self.bot_valid_label, False, i18n.translate_for_current("تعذّر التحقّق (لا منفّذ خلفي)")
            )
            return

        self.bot_status_label.setText(i18n.translate_for_current("جارٍ التحقّق من التوكِن عبر getMe…"))
        self.add_bot_button.setEnabled(False)

        # كلّ الشبكة داخل دالة الخلفية؛ لا شبكة على خيط الواجهة.
        def _validate(_token=token):
            client = TelegramClient(_token)
            return client.get_me()

        def _on_ok(result, _token=token):
            self._handle_bot_validated(_token, result)

        def _on_err(exc):
            self._handle_bot_error(exc)

        self._runner.submit(_validate, on_result=_on_ok, on_error=_on_err)

    def _handle_bot_validated(self, token, result):
        """يعمل على خيط الواجهة: يخزّن التوكِن + بيانات البوت ويعكس حالة valid."""
        username = ""
        if isinstance(result, dict):
            username = result.get("username", "") or ""
        try:
            self._store.set_token(token)
            self._store.set_bot(username=username, label=username)
        except Exception:
            # لا نُسرّب أي تفاصيل؛ نظهر فشلًا عامًّا فقط.
            self._set_valid_label(self.bot_valid_label, False, i18n.translate_for_current("تعذّر الحفظ"))
            self.add_bot_button.setEnabled(self._runner is not None)
            return
        # نعيد عكس الحالة (بوت مُضاف + valid + تقنيع/مسح حقل التوكِن).
        self.reload_settings()

    def _handle_bot_error(self, exc):
        """يعمل على خيط الواجهة: يعرض invalid مع سبب قصير (بلا تسريب توكِن)."""
        reason = i18n.translate_for_current("رُفض التوكِن")
        if isinstance(exc, TelegramError):
            desc = getattr(exc, "description", None)
            if desc:
                reason = str(desc)
        else:
            reason = i18n.translate_for_current("تعذّر الاتصال بـ Telegram")
        self._set_valid_label(self.bot_valid_label, False, reason)
        self.bot_status_label.setText(i18n.translate_for_current("فشل التحقّق من البوت."))
        self.add_bot_button.setEnabled(self._runner is not None)

    def _on_remove_bot_clicked(self, *args):
        try:
            self._store.clear_token()
            self._store.clear_bot()
        except Exception:
            pass
        # نعيد الواجهة إلى حالة الإضافة (قابل لإعادة الإضافة).
        self.token_input.clear()
        self.reload_settings()

    # ------------------------------------------------------------------
    # القسم 2: مُعالِجات المستلمين
    # ------------------------------------------------------------------
    def _on_chat_id_text_changed(self, text):
        """تحقّق صيغة chat_id بجوار الحقل مباشرةً (inline)."""
        value = (text or "").strip()
        if not value:
            self.chat_id_valid_label.setText("")
            return
        self._set_valid_label(self.chat_id_valid_label, _is_valid_chat_id(value))

    def _on_add_recipient_clicked(self, *args):
        chat_id = self.chat_id_input.text().strip()
        if not _is_valid_chat_id(chat_id):
            self._set_valid_label(
                self.chat_id_valid_label, False, i18n.translate_for_current("صيغة chat_id غير صحيحة")
            )
            return
        try:
            self._store.add_recipient(chat_id)  # يزيل التكرار بـ chat_id
        except Exception:
            self._set_valid_label(
                self.chat_id_valid_label, False, i18n.translate_for_current("تعذّر الحفظ")
            )
            return
        self.chat_id_input.clear()
        self.chat_id_valid_label.setText("")
        self.reload_settings()

    def _on_remove_recipients_clicked(self, *args):
        selected = self.recipients_list.selectedItems()
        if not selected:
            return
        chat_ids = []
        for item in selected:
            raw = item.data(Qt.ItemDataRole.UserRole)
            chat_ids.append(str(raw) if raw is not None else item.text())
        try:
            self._store.remove_recipients(chat_ids)
        except Exception:
            pass
        self.reload_settings()

    # ------------------------------------------------------------------
    # القسم 3: تفعيل/تعطيل
    # ------------------------------------------------------------------
    def _on_enabled_toggled(self, checked):
        try:
            self._store.set_enabled(bool(checked))
        except Exception:
            pass
        self._update_enabled_label(bool(checked))

    # ------------------------------------------------------------------
    # القسم 4: إرسال رسالة اختبارية (كلّ الشبكة في الخلفية)
    # ------------------------------------------------------------------
    def _on_test_clicked(self, *args):
        if self._runner is None:
            self.test_status_label.setText(i18n.translate_for_current("تعذّر الإرسال (لا منفّذ خلفي)."))
            return

        token = self._store.get_token()
        recipients = list(self._store.recipients_provider())
        if not token:
            self.test_status_label.setText(i18n.translate_for_current("أضِف البوت أولًا."))
            return
        if not recipients:
            self.test_status_label.setText(i18n.translate_for_current("أضِف مستلمًا واحدًا على الأقل."))
            return

        self.test_status_label.setText(i18n.translate_for_current("جارٍ إرسال رسالة اختبارية…"))

        # كلّ الشبكة داخل دالة الخلفية؛ لا شبكة على خيط الواجهة.
        def _send(_token=token, _recipients=recipients):
            client = TelegramClient(_token)
            sent = 0
            for chat_id in _recipients:
                client.send_message(chat_id, _TEST_MESSAGE)
                sent += 1
            return sent

        def _on_ok(count):
            self.test_status_label.setStyleSheet(
                "color:%s;font-size:13px;" % PALETTE["GREEN"]
            )
            self.test_status_label.setText(
                i18n.translate_for_current("تم الإرسال بنجاح إلى %s مستلم.") % count
            )

        def _on_err(exc):
            reason = i18n.translate_for_current("فشل الإرسال")
            if isinstance(exc, TelegramError):
                desc = getattr(exc, "description", None)
                if desc:
                    reason = str(desc)
            self.test_status_label.setStyleSheet(
                "color:%s;font-size:13px;" % PALETTE["RED"]
            )
            self.test_status_label.setText(i18n.translate_for_current("فشل الإرسال الاختباري: %s") % reason)

        self._runner.submit(_send, on_result=_on_ok, on_error=_on_err)

    # ------------------------------------------------------------------
    # دورة حياة الشاشة: عند الإظهار نعيد تحميل الإعدادات ونعكسها
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self.reload_settings()

    # ------------------------------------------------------------------
    # مساعدات للاختبارات (قراءة فقط)
    # ------------------------------------------------------------------
    def recipient_values(self):
        """قيم chat_id المعروضة في القائمة بالترتيب (يستعملها الاختبار)."""
        return [
            self.recipients_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.recipients_list.count())
        ]
