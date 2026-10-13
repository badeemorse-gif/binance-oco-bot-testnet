"""شاشة الاتصال بالحساب (G1.11).

واجهة مرنة لإدخال مفاتيح Binance يدويًا أو اختيار ملف txt، مع زر اتصال
ولمبة حالة (خضراء/حمراء/كهرمانية). لا تُجري هذه الشاشة أي اتصال شبكي
مباشرة؛ كل اختبار اتصال يمرّ عبر connect_handler محقون يُنفَّذ على AsyncRunner.
"""

from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
)
from .theme import PALETTE
from .topbar import Pill
from . import i18n


_STATE_DISPLAY = {
    "CONNECTED": ("متصل", "GREEN"),
    "CONNECTING": ("جارٍ الاتصال", "AMBER"),
    "ERROR": ("خطأ اتصال", "RED"),
    "DISCONNECTED": ("غير متصل", "MUTED"),
    # G1.12: user-initiated disconnect — same label, RED light. Plain
    # DISCONNECTED stays MUTED (non-breaking).
    "DISCONNECTED_USER": ("غير متصل", "RED"),
}

_INPUT_STYLE = (
    "background:%s;color:%s;border:1px solid %s;border-radius:6px;padding:6px 10px;"
    % (PALETTE["CARD"], PALETTE["TEXT"], PALETTE["BORDER"])
)
_BUTTON_STYLE = (
    "background:%s;color:%s;border:none;border-radius:6px;padding:7px 16px;font-weight:600;"
    % (PALETTE["BLUE"], PALETTE["TEXT"])
)
_LABEL_STYLE = "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]


class ConnectionScreen(QWidget):
    """شاشة إدخال المفاتيح واختبار الاتصال بحساب Binance التجريبي."""

    screen_key = "07_connection"

    def __init__(self, parent=None, runner=None, connect_handler=None):
        super().__init__(parent)
        self.screen_key = "07_connection"
        self.setObjectName("Screen_07_connection")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._runner = runner
        self._connect_handler = connect_handler
        self._disconnect_handler = None  # G1.12: isolated disconnect callable
        self._selected_path = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        self.heading = QLabel("الاتصال بالحساب", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        hint = QLabel(
            "أدخل مفتاح API والمفتاح السري يدويًا، أو اختر ملف txt يحوي المفاتيح. "
            "اترك الحقول فارغة لاستخدام المسار الافتراضي كخيار احتياطي.",
            self,
        )
        hint.setObjectName("ConnectionHint")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
        root.addWidget(hint)

        key_label = QLabel("مفتاح API", self)
        key_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(key_label)
        self._api_key_input = QLineEdit(self)
        self._api_key_input.setObjectName("ConnectionApiKey")
        self._api_key_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._api_key_input.setPlaceholderText("API Key")
        self._api_key_input.setStyleSheet(_INPUT_STYLE)
        root.addWidget(self._api_key_input)

        secret_label = QLabel("المفتاح السري", self)
        secret_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(secret_label)
        self._api_secret_input = QLineEdit(self)
        self._api_secret_input.setObjectName("ConnectionApiSecret")
        self._api_secret_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_secret_input.setPlaceholderText("API Secret")
        self._api_secret_input.setStyleSheet(_INPUT_STYLE)
        root.addWidget(self._api_secret_input)

        file_row = QHBoxLayout()
        self._path_field = QLineEdit(self)
        self._path_field.setObjectName("ConnectionKeyFile")
        self._path_field.setReadOnly(True)
        self._path_field.setPlaceholderText("لم يتم اختيار ملف")
        self._path_field.setStyleSheet(_INPUT_STYLE)
        file_row.addWidget(self._path_field, 1)
        self._open_file_btn = QPushButton("فتح ملف", self)
        self._open_file_btn.setObjectName("ConnectionOpenFile")
        self._open_file_btn.setStyleSheet(_BUTTON_STYLE)
        self._open_file_btn.clicked.connect(self._on_open_file_clicked)
        file_row.addWidget(self._open_file_btn)
        root.addLayout(file_row)

        action_row = QHBoxLayout()
        self._connect_btn = QPushButton("اتصال", self)
        self._connect_btn.setObjectName("ConnectionConnect")
        self._connect_btn.setStyleSheet(_BUTTON_STYLE)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        action_row.addWidget(self._connect_btn)
        # G1.12: isolated disconnect button next to the connect button.
        self._disconnect_btn = QPushButton("قطع الاتصال", self)
        self._disconnect_btn.setObjectName("ConnectionDisconnect")
        self._disconnect_btn.setStyleSheet(_BUTTON_STYLE)
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        action_row.addWidget(self._disconnect_btn)
        self._light = Pill("غير متصل", PALETTE["MUTED"], self)
        self._light.setObjectName("ConnectionLight")
        action_row.addWidget(self._light)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self._message = QLabel("", self)
        self._message.setObjectName("ConnectionMessage")
        self._message.setWordWrap(True)
        self._message.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
        root.addWidget(self._message)

        root.addStretch(1)

    def api_key_value(self):
        return self._api_key_input.text().strip()

    def api_secret_value(self):
        return self._api_secret_input.text().strip()

    def selected_file_path(self):
        return self._selected_path or ""

    def set_connect_handler(self, handler):
        self._connect_handler = handler

    def set_disconnect_handler(self, handler):
        """G1.12: يحقن معالج القطع المعزول (يُنفَّذ عند الضغط على «قطع الاتصال»)."""
        self._disconnect_handler = handler

    def _on_disconnect_clicked(self):
        """G1.12: يقطع الاتصال (مسح مصدر المفاتيح عبر المعالج) ويُظهر لمبة حمراء + «غير متصل». لا شبكة."""
        if self._disconnect_handler is not None:
            self._disconnect_handler()
        self.set_connection_state("DISCONNECTED_USER")

    def set_connection_state(self, state, message=None):
        label, accent_key = _STATE_DISPLAY.get(state, ("غير متصل", "MUTED"))
        self._light.set_accent(i18n.translate_for_current(label), PALETTE[accent_key])
        if message is not None:
            self._message.setText(i18n.translate_for_current(message))

    def _on_open_file_clicked(self):
        path, _selected = QFileDialog.getOpenFileName(
            self, i18n.translate_for_current("اختر ملف المفاتيح"), "", i18n.translate_for_current("ملفات نصية (*.txt);;كل الملفات (*)")
        )
        if path:
            self._selected_path = path
            self._path_field.setText(path)

    def _on_connect_clicked(self):
        if self._connect_handler is None:
            self.set_connection_state("DISCONNECTED", "لم يتم تفعيل الاتصال بعد.")
            return
        self.set_connection_state("CONNECTING", "جارٍ الاتصال...")
        api_key = self.api_key_value()
        api_secret = self.api_secret_value()
        keys_path = self.selected_file_path()
        if self._runner is not None:
            self._runner.submit(
                self._connect_handler,
                api_key=api_key,
                api_secret=api_secret,
                keys_path=keys_path,
                on_result=self._on_connect_result,
                on_error=self._on_connect_error,
            )
        else:
            try:
                result = self._connect_handler(
                    api_key=api_key, api_secret=api_secret, keys_path=keys_path
                )
            except Exception as exc:  # noqa: BLE001
                self._on_connect_error(exc)
            else:
                self._on_connect_result(result)

    def _on_connect_result(self, result):
        ok = bool(getattr(result, "ok", result))
        message = getattr(result, "message", "") or ""
        if ok:
            self.set_connection_state("CONNECTED", message or "تم الاتصال بنجاح.")
        else:
            self.set_connection_state("ERROR", message or i18n.translate_for_current("فشل الاتصال."))

    def _on_connect_error(self, error):
        self.set_connection_state("ERROR", i18n.translate_for_current("فشل الاتصال: %s") % error)
