"""شاشة المراقبة الديناميكية (Dynamic Monitoring) — T13 (M-UI/3).

تعرض السعر الحيّ والمستويات الحيّة وحالة المراقبة، وتتحكّم في ``MonitoringEngine``
المحقون: Start / Pause / Resume / Kill Switch. تلتزم مبادئ التصميم:

  - D14: السعر الحيّ حقيقي — يُحقن مصدرٌ حيّ (PriceFeedController: WS مع سقوط REST)
    عبر ``price_provider`` قابل للاستدعاء؛ لا Preview ثابت.
  - Pause/Resume وKill Switch لا يمسّان أي أمر على Binance (P2/P3) — كل التحكّم يمرّ
    عبر المحرّك المحقون الذي يفوّض التنفيذ للـ SafeExecutor فقط.
  - لا شبكة/IO داخل طبقة الواجهة (تحترم حارس test_ui_no_direct_network): جلب السعر
    يمرّ عبر الرَنَر (AsyncRunner) أو متزامنًا في الاختبارات؛ لا نداءات شبكة هنا.
  - رسالة Kill Switch = MSG_KILL_SWITCH (تُعاد كما هي من المحرّك).

RTL + ثيم داكن عبر PALETTE (D15). لوحة حيّة تُبقي ظاهرًا دائمًا (لا يختفي أثناء
المراقبة): Symbol · Order List ID · Current Price · Reference Price · Trigger Price ·
Current TP · Current SL · Next TP · Next SL · SL Limit · Tick Size · Monitoring State ·
Last Operation + Result · Connection · Environment (التصميم §3.5 E).
"""
import os
import time
from decimal import Decimal, InvalidOperation

from ._qt import (
    Qt,
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTimer,
)
from ocobot.domain.guardian_status import GuardianMode
from .guardian_indicator import GuardianIndicator, BtcFollowIndicator
from .percent_tracker import PercentTracker
from .btc_slippage_tracker import BtcSlippageTracker, window_slippage
from .deal_result_card import DealResultCard
from ocobot.domain.btc_follow_supervisor import BtcFollowSupervisor
from ocobot.domain.btc_follow import BtcFollowConfig
from ocobot.domain.bracket import BracketConfig, validate_bracket
from ocobot.domain.models import fmt
from ocobot.domain.pricing import compute_levels
from ocobot.domain.monitoring import MSG_KILL_SWITCH, MonitoringStateEnum
from ocobot.domain.reposition import ExecutionState
from ocobot.domain.completed_trades import load_completed_trades, default_dismiss_path
from .theme import PALETTE
from . import i18n

EMPTY = "—"
NO_SELECTION_NOTE = "لم يُختَر أمر"

# G1.34: حالة عرضية مشتقّة (عرض فقط) تُعرض بعد ملامسة القوس ووضع أمر جديد.
#        ليست حالة محرّك — المحرّك يبقى MONITORING_ACTIVE فيستمرّ النبض.
ORDER_PLACED_STATE = "ORDER_PLACED"

# G1.34: حقول بانل «الأمر النشط بعد الملامسة» (مفتاح، عنوان) — عرض فقط.
ACTIVE_ORDER_FIELDS = [
    ("list_id", "معرّف الأمر الجديد"),
    ("type", "النوع"),
    ("limit", "سعر الليمت"),
    ("stop", "سعر الوقف"),
    ("qty", "الكمية"),
    ("reason", "سبب التفعيل"),
    ("time", "وقت التفعيل"),
]

# حقول لوحة النِّسب الثلاثة (التصميم §3.5 E): مفتاح، عنوان.
PCT_FIELDS = [
    ("trigger_pct", "نسبة ارتفاع مُشغِّل إعادة التموضع %"),
    ("tp_pct", "نسبة بُعد جني الأرباح فوق الحالي %"),
    ("sl_pct", "نسبة بُعد وقف الخسارة تحت الحالي %"),
]

# حقول اللوحة الحيّة التي لا تختفي أثناء المراقبة (التصميم §3.5 E) — بالترتيب.
LIVE_FIELDS = [
    ("symbol", "الرمز"),
    ("order_list_id", "معرّف قائمة الأوامر"),
    ("current_price", "السعر الحالي"),
    ("reference_price", "السعر المرجعي"),
    ("trigger_price", "سعر التفعيل"),
    ("current_tp", "جني الأرباح الحالي"),
    ("current_sl", "وقف الخسارة الحالي"),
    ("next_tp", "جني الأرباح التالي"),
    ("next_sl", "وقف الخسارة التالي"),
    ("sl_limit", "حد وقف الخسارة"),
    ("tick_size", "حجم الخطوة السعرية"),
    ("monitoring_state", "حالة المراقبة"),
    ("last_operation", "آخر عملية والنتيجة"),
    ("connection", "الاتصال"),
    ("environment", "البيئة"),
]

# تلوين حالة المراقبة (D15) — مطابق لنمط dashboard._STATE_ACCENT ويغطّي حالات المحرّك.
_STATE_ACCENT = {
    "ORDER_PLACED": "GREEN",  # G1.34: حالة عرضية بعد الملامسة ووضع أمر جديد
    "MONITORING_ACTIVE": "GREEN",
    "ACTIVE": "GREEN",
    "TRIGGERED": "BLUE",
    "LATCHED": "BLUE",
    "REPOSITIONING": "TEAL",
    "IN_FLIGHT": "TEAL",
    "PAUSED": "AMBER",
    "MONITORING_STOPPED": "RED",
    "CLOSED": "RED",
    "ABORTED": "RED",
    "FAILED_NEEDS_ATTENTION": "RED",
    "SUCCESS": "GREEN",
    "IDLE": "MUTED",
    "DISCONNECTED": "MUTED",
    "CONNECTED": "MUTED",
    "SELECTED": "MUTED",
}

_HUNDRED = Decimal("100")


class DynamicMonitoringScreen(QWidget):
    """شاشة المراقبة الديناميكية — تتحكّم في MonitoringEngine المحقون.

    الحقن (كنمط SelectedOcoScreen): ``engine`` (MonitoringEngine له start/pause/
    resume/kill_switch)؛ ``price_provider`` callable يُرجع السعر الحيّ الحقيقي
    (PriceFeedController.get_price)؛ ``runner`` (AsyncRunner) لإبقاء IO خارج خيط
    الواجهة. لا شبكة هنا مطلقًا.
    """

    def __init__(self, parent=None, engine=None, price_provider=None, runner=None,
                 selected_oco=None, environment=None, convert_cb=None,
                 audit_path=None, dismiss_path=None):
        super().__init__(parent)
        self.screen_key = "04_dynamic_monitoring"
        self.setObjectName("Screen_04_dynamic_monitoring")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self._engine = engine                 # MonitoringEngine المحقون (يفوّض للـ SafeExecutor)
        self._price_provider = price_provider  # callable يُرجع السعر الحيّ الحقيقي (D14)
        self.runner = runner                   # AsyncRunner (اختياري) — لا IO في الواجهة
        self._manual_exit_fn = None            # G1.47: callable الخروج اليدوي الفوري (يُحقن عبر set_manual_exit_fn)
        # G1.13 (CHUNK 1 — plumbing فقط): callback التحويل إلى OCO محقون ومخزَّن.
        # لا يُستعمل في _on_start_clicked هذا الـ chunk (ذلك في CHUNK 2).
        self._convert_cb = convert_cb
        self._selected = selected_oco          # الـ OCO المختار (SelectedOCO أو None)
        self._environment = environment        # اسم البيئة (Testnet/Live) للعرض
        self._current_price = None             # آخر سعر حيّ حقيقي محقون (لا Preview)
        self._pct_edits = {}
        self._live = {}
        # G1.34: «الأمر النشط بعد الملامسة» (عرض فقط) + حالة عرضية مشتقّة ORDER_PLACED
        #        تُبقى حتى ملامسة جديدة؛ لا تمسّ حالة المحرّك ولا تُوقف النبض.
        self._active_order = None
        self._display_state = None
        self._ticking = False                  # G1.8: هل حلقة التحديث الحيّ نشطة
        self._tick_interval = 1.0              # G1.8: مباعدة النبضات (ثوانٍ) خارج خيط الواجهة
        # G1.31 (chunk_3): وضع الحارس المختار من الواجهة (افتراضيًّا OFF — لا تدخّل).
        self._guardian_mode = GuardianMode.OFF
        self.guardian_indicator = None         # يُبنى ضمن _build_guardian_row
        # G1.44 / chunk_4: وضع حارس هبوط BTC المستقلّ (افتراضيًّا OFF — لا تدخّل).
        self._btc_follow_mode = GuardianMode.OFF
        self.btc_follow_indicator = None       # يُبنى ضمن _build_btc_follow_row
        # G1.44 / chunk_4: موفّر سعر BTC المعزول (يُحقن من الربط؛ قابل للاستدعاء أو None).
        #   لا شبكة في الواجهة: الربط يحقن callable يقرأ تغذية BTC خارج خيط الواجهة.
        self._btc_price_provider = None
        # G1.45: لوحات تتبّع النِّسب (عرض فقط). anchor مثبّت للعملة المراقَبة + مُشرِف عرض BTC.
        self._monitored_anchor = None
        # G1.48: مراجع «نسبة التغيّر» (rolling) للعملة المراقَبة + مرساة BTC المجمّدة للتتبّع.
        self._monitored_prev = None
        self._monitored_last = None
        self._btc_anchor = None
        self._btc_tracker = None
        self._btc_slip_tracker = None
        self._monitored_tracker = None
        try:
            self._btc_display_sup = BtcFollowSupervisor(
                config=BtcFollowConfig(enabled=True, window_seconds=5.0)
            )
        except Exception:
            self._btc_display_sup = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        # ترويسة.
        self.heading = QLabel("المراقبة الديناميكية", self)
        self.heading.setObjectName("ScreenHeading")
        self.heading.setStyleSheet(
            "color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"]
        )
        root.addWidget(self.heading)

        self._note = QLabel(NO_SELECTION_NOTE, self)
        self._note.setObjectName("MonitoringNote")
        self._note.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        root.addWidget(self._note)

        # G1.46: مرجع بطاقات نتيجة الصفقة لكل وسيلة (تُنشأ داخل بطاقة كل وسيلة).
        self._deal_result_cards = {}
        # G1.46.1: مصدر بيانات بطاقة النتيجة (قراءة فقط من سجل التدقيق) + مؤقّت
        # تحديث دوري أثناء ظهور الشاشة فقط — نفس نمط CompletedTradesScreen (G1.24).
        # الافتراض متوافق خلفيًّا: OCOBOT_AUDIT_LOG أو cwd/ocobot_audit.jsonl.
        self._deal_audit_path = audit_path or os.environ.get(
            "OCOBOT_AUDIT_LOG", os.path.join(os.getcwd(), "ocobot_audit.jsonl"))
        self._deal_dismiss_path = dismiss_path or default_dismiss_path(self._deal_audit_path)
        self._deal_results_timer = QTimer(self)
        self._deal_results_timer.setInterval(1000)
        self._deal_results_timer.timeout.connect(self.refresh_deal_results)
        self._build_rules_section(root)   # checkbox تفعيل + 3 حقول نِسب + أزرار التحكّم
        self._build_guardian_row(root)    # G1.31: شارة الحارس + مُبدِّل وضع Off/Observe/Live
        self._build_btc_follow_row(root)  # G1.44: حارس هبوط BTC (مؤشّر + مُبدِّل مستقلّ)
        self._build_bracket_row(root)     # G1.32b: قوس الخروج بالسعر (خانتا سعر + مفتاح)
        self._build_active_order_panel(root)  # G1.34: بانل «الأمر النشط بعد الملامسة» تحت الحدود
        self._build_monitored_tracker_row(root)  # G1.45: تتبّع نسبة العملة المراقَبة من سعر البدء المثبّت
        self._build_live_panel(root)      # اللوحة الحيّة (لا تختفي أثناء المراقبة)

        # G1.13: تلميح أنّ الأمر مرشّح تحويل (ليس OCO بعد) — يلزم التحويل قبل البدء.
        self._convert_hint = QLabel("", self)
        self._convert_hint.setObjectName("MonitoringConvertHint")
        self._convert_hint.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        self._convert_hint.setVisible(False)
        root.addWidget(self._convert_hint)

        root.addStretch(1)

        # الحالة الابتدائية.
        self._refresh_live_panel()

    # ---- بناء الأقسام ----
    def _build_rules_section(self, root):
        """checkbox تفعيل يكشف 3 حقول نِسب + أزرار Start / Pause-Resume / Kill Switch."""
        card = QFrame(self)
        card.setObjectName("MonitoringRulesCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringRulesCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        heading = QLabel("قواعد المراقبة", card)
        heading.setObjectName("MonitoringRulesHeading")
        heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(heading)

        # checkbox تفعيل (كشف تدريجي للحقول الثلاثة).
        self._enable_toggle = QCheckBox("تفعيل", card)
        self._enable_toggle.setObjectName("MonitoringEnableToggle")
        self._enable_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._enable_toggle.setStyleSheet(
            "color:%s;font-size:13px;" % PALETTE["TEXT_SOFT"]
        )
        lay.addWidget(self._enable_toggle)

        # صف حقول النِّسب الثلاثة (مخفيّة حتى التفعيل).
        pct_row = QHBoxLayout()
        pct_row.setSpacing(12)
        self._pct_widgets = []
        for key, label in PCT_FIELDS:
            col = QVBoxLayout()
            col.setSpacing(4)
            caption = QLabel(label, card)
            caption.setObjectName("MonitoringPctLabel_%s" % key)
            caption.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
            edit = QLineEdit(card)
            edit.setObjectName("MonitoringPctEdit_%s" % key)
            edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            edit.setStyleSheet(
                "background:%s;color:%s;border:1px solid %s;border-radius:6px;"
                "padding:6px 10px;"
                % (PALETTE["CARD"], PALETTE["TEXT"], PALETTE["BORDER"])
            )
            edit.textChanged.connect(self._refresh_live_panel)
            self._pct_edits[key] = edit
            self._pct_widgets.append(caption)
            self._pct_widgets.append(edit)
            col.addWidget(caption)
            col.addWidget(edit)
            pct_row.addLayout(col, 1)
        lay.addLayout(pct_row)

        for w in self._pct_widgets:
            w.setVisible(False)  # كشف تدريجي
        self._enable_toggle.toggled.connect(self._on_enable_toggled)

        # أزرار التحكّم: Start · Pause/Resume · Kill Switch.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.start_button = QPushButton("بدء", card)
        self.start_button.setObjectName("MonitoringStartButton")
        self.start_button.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_button)

        self.pause_resume_button = QPushButton("إيقاف مؤقت", card)
        self.pause_resume_button.setObjectName("MonitoringPauseResumeButton")
        self.pause_resume_button.clicked.connect(self._on_pause_resume_clicked)
        btn_row.addWidget(self.pause_resume_button)

        # Kill Switch — زر أحمر ثابت الوصول (التصميم §3.8 I).
        self.kill_switch_button = QPushButton("إيقاف طارئ", card)
        self.kill_switch_button.setObjectName("MonitoringKillSwitchButton")
        self.kill_switch_button.setStyleSheet(
            "QPushButton#MonitoringKillSwitchButton{background:%s;color:%s;"
            "border:1px solid %s;border-radius:6px;padding:6px 12px;font-weight:700;}"
            % (PALETTE["RED"], PALETTE["TEXT"], PALETTE["RED"])
        )
        self.kill_switch_button.clicked.connect(self._on_kill_switch_clicked)
        btn_row.addWidget(self.kill_switch_button)

        # G1.47: زرّ «تنفيذ الخروج الفوري» — خروج يدوي أحادي بأولوية عُليا (Testnet فقط).
        self.manual_exit_button = QPushButton("تنفيذ الخروج الفوري", card)
        self.manual_exit_button.setObjectName("MonitoringManualExitButton")
        self.manual_exit_button.setToolTip(
            "خروج يدوي فوري بأفضل سعر لحظي — أولوية عُليا على الوسائل الأربع (Testnet)"
        )
        self.manual_exit_button.setStyleSheet(
            "QPushButton#MonitoringManualExitButton{background:%s;color:%s;"
            "border:1px solid %s;border-radius:6px;padding:6px 12px;font-weight:700;}"
            % (PALETTE["AMBER"], PALETTE["TEXT"], PALETTE["AMBER"])
        )
        self.manual_exit_button.clicked.connect(self._on_manual_exit_clicked)
        btn_row.addWidget(self.manual_exit_button)

        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # G1.46: بطاقة نتيجة الصفقة أسفل وسيلة المراقبة (MONITORING) — عرض فقط.
        try:
            _drc = DealResultCard(card)
            _drc.setObjectName("MonitoringDealResultMonitoring")
            self._deal_result_cards["MONITORING"] = _drc
            lay.addWidget(_drc)
        except Exception:
            self._deal_result_cards["MONITORING"] = None

        root.addWidget(card)

    def _build_live_panel(self, root):
        """اللوحة الحيّة — تُبقي كل الحقول ظاهرة دائمًا (لا تختفي أثناء المراقبة)."""
        card = QFrame(self)
        card.setObjectName("MonitoringLiveCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringLiveCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        title = QLabel("اللوحة الحيّة", card)
        title.setObjectName("MonitoringLiveTitle")
        title.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(title)

        # G1.4 (REWORK): شبكة مشتركة واحدة — العناوين في العمود 0 (أقصى اليمين تحت RTL)
        # بعرض أدنى ثابت وstretch=0 فتصطف في عمود واحد؛ القيم في العمود 1 بstretch=1
        # محاذاة نحو حافة العنوان فتلاصقه بفجوة أفقية ثابتة. يستبدل QHBoxLayout+AlignRight.
        # G1.21: four-column grid; paired rows (current/next TP, then current/next SL); others single full-width rows
        # G1.22: TP/SL pair rows reflowed to 5 columns so the current/next prices
        #   face each other (RTL col0..col4):
        #     col0=caption_current | col1=value_current | col2=arrow(←) | col3=value_next | col4=caption_next
        #   Value cells are coloured: TP row = GREEN bg + white bold; SL row = RED bg + white bold.
        #   The arrow is a standalone QLabel (NOT added to self._live → key count stays 15).
        #   All other single-field rows keep a full-width value by spanning the extra column.
        label_of = dict(LIVE_FIELDS)
        # Keys whose value cells get coloured (facing-price pairs). Maps key -> palette colour.
        _TP_SL_VALUE_COLOR = {
            "current_tp": PALETTE["GREEN"],
            "next_tp": PALETTE["GREEN"],
            "current_sl": PALETTE["RED"],
            "next_sl": PALETTE["RED"],
        }
        row_plan = [
            ["symbol"], ["order_list_id"], ["current_price"],
            ["reference_price"], ["trigger_price"],
            ["current_tp", "next_tp"],
            ["current_sl", "next_sl"],
            ["sl_limit"], ["tick_size"], ["monitoring_state"],
            ["last_operation"], ["connection"], ["environment"],
        ]
        assert {k for row in row_plan for k in row} == {k for k, _ in LIVE_FIELDS}
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)
        # G1.22: 5th column (col4) carries the facing caption_next of the TP/SL rows.
        grid.setColumnStretch(4, 0)
        grid.setColumnMinimumWidth(0, 180)
        grid.setColumnMinimumWidth(1, 140)
        # G1.22: col2 is the narrow arrow column between the two facing price cells
        # (small fixed width so prices stay close yet columns can still shrink at 420px).
        grid.setColumnMinimumWidth(2, 24)
        grid.setColumnMinimumWidth(3, 140)
        grid.setColumnMinimumWidth(4, 180)

        def _make_caption(key):
            caption = QLabel(label_of[key], card)
            caption.setObjectName("MonitoringLiveCaption_%s" % key)
            caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
            caption.setMinimumWidth(180)
            return caption

        def _make_value(key):
            value = QLabel(EMPTY, card)
            value.setObjectName("MonitoringLiveValue_%s" % key)
            # G1.22: TP/SL facing-price value cells are coloured (green/red) with
            # white bold text; all other value cells keep the default style.
            colour = _TP_SL_VALUE_COLOR.get(key)
            if colour is not None:
                value.setStyleSheet(
                    "QLabel#MonitoringLiveValue_%s{background:%s;color:%s;"
                    "font-size:15px;font-weight:700;border-radius:6px;"
                    "padding:2px 6px;}" % (key, colour, PALETTE["TEXT"])
                )
            else:
                value.setStyleSheet(
                    "color:%s;font-size:15px;font-weight:600;" % PALETTE["TEXT"]
                )
            value.setMinimumWidth(120)
            value.setWordWrap(True)
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            self._live[key] = value
            return value

        def _make_arrow(pair):
            # G1.22: standalone facing-price arrow between the two value cells.
            # NOT added to self._live (key count stays 15). The "←" glyph is not
            # displayed English, so it respects the Arabic-UI guard (test_g1_7).
            arrow = QLabel("←", card)
            arrow.setObjectName("MonitoringLiveArrow_%s" % pair)
            arrow.setStyleSheet(
                "color:%s;font-size:15px;font-weight:700;" % PALETTE["MUTED"]
            )
            arrow.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            )
            return arrow

        # Map each paired row's key-prefix (tp/sl) for the arrow objectName.
        _PAIR_OF = {"current_tp": "tp", "current_sl": "sl"}
        for r, row_keys in enumerate(row_plan):
            if len(row_keys) == 1:
                # G1.22: single rows now span the full 5-column width (was 3).
                key = row_keys[0]
                grid.addWidget(_make_caption(key), r, 0)
                grid.addWidget(_make_value(key), r, 1, 1, 4)
            else:
                # G1.22: facing-prices layout (RTL col0..col4):
                #   caption_current | value_current | arrow(←) | value_next | caption_next
                k0, k1 = row_keys
                pair = _PAIR_OF[k0]
                grid.addWidget(_make_caption(k0), r, 0)
                grid.addWidget(_make_value(k0), r, 1)
                grid.addWidget(_make_arrow(pair), r, 2)
                grid.addWidget(_make_value(k1), r, 3)
                grid.addWidget(_make_caption(k1), r, 4)
        lay.addLayout(grid)

        root.addWidget(card)

    # ---- G1.32b: قوس الخروج بالسعر ----
    def _build_bracket_row(self, root):
        """G1.32b (chunk_1): قوس الخروج بالسعر — خانتا سعر (علوي/سفلي) + مفتاح تفعيل.

        إضافيّ بالكامل: لا يمسّ/يعيد ترتيب أيّ عنصر قائم. المفتاح مطفأ افتراضيًّا
        (لا خروج). التحقّق المنطقي فقط هنا (سفلي < الحالي < علوي؛ تحذير لو مقلوب) —
        بلا شبكة وبلا تنفيذ. الربط بالمُراقِب/المنفّذ يتمّ في app.py (chunk_2).
        """
        card = QFrame(self)
        card.setObjectName("MonitoringBracketCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringBracketCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        heading = QLabel("قوس الخروج بالسعر", card)
        heading.setObjectName("MonitoringBracketHeading")
        heading.setStyleSheet("color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"])
        lay.addWidget(heading)

        self._bracket_enable_toggle = QCheckBox("تفعيل قوس الخروج", card)
        self._bracket_enable_toggle.setObjectName("MonitoringBracketEnable")
        self._bracket_enable_toggle.setChecked(False)  # مطفأ افتراضيًّا
        self._bracket_enable_toggle.toggled.connect(self._on_bracket_changed)
        lay.addWidget(self._bracket_enable_toggle)

        row = QHBoxLayout()
        row.setSpacing(12)

        up_caption = QLabel("حدّ علوي", card)
        up_caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        row.addWidget(up_caption)
        self._bracket_upper_edit = QLineEdit(card)
        self._bracket_upper_edit.setObjectName("MonitoringBracketUpper")
        self._bracket_upper_edit.setPlaceholderText("سعر علوي")
        self._bracket_upper_edit.textChanged.connect(self._on_bracket_changed)
        row.addWidget(self._bracket_upper_edit)

        lo_caption = QLabel("حدّ سفلي", card)
        lo_caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        row.addWidget(lo_caption)
        self._bracket_lower_edit = QLineEdit(card)
        self._bracket_lower_edit.setObjectName("MonitoringBracketLower")
        self._bracket_lower_edit.setPlaceholderText("سعر سفلي")
        self._bracket_lower_edit.textChanged.connect(self._on_bracket_changed)
        row.addWidget(self._bracket_lower_edit)

        lay.addLayout(row)

        # G1.33: نِسب تسعير قابلة للتعديل — الفارغ = الافتراضي القديم (0.1/1/8/1).
        prow = QHBoxLayout()
        prow.setSpacing(10)

        def _mini(caption_text, object_name, placeholder):
            cap = QLabel(caption_text, card)
            cap.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
            prow.addWidget(cap)
            edit = QLineEdit(card)
            edit.setObjectName(object_name)
            edit.setPlaceholderText(placeholder)
            edit.textChanged.connect(self._on_bracket_changed)
            prow.addWidget(edit)
            return edit

        self._bracket_slip_edit = _mini("انزلاق علوي %", "MonitoringBracketSlipPct", "0.1")
        self._bracket_sl_edit = _mini("زناد سفلي %", "MonitoringBracketSlPct", "1")
        self._bracket_floor_edit = _mini("أرضية %", "MonitoringBracketFloorPct", "8")
        self._bracket_gap_edit = _mini("gap", "MonitoringBracketGapTicks", "1")

        lay.addLayout(prow)

        # G1.49 chunk_5: بارامترات سياسة تنفيذ الخروج الموحّدة (عرض/ضبط فقط؛ الفارغ ⇒ الافتراضي).
        xheading = QLabel("سياسة تنفيذ الخروج الموحّدة", card)
        xheading.setObjectName("MonitoringExitPolicyHeading")
        xheading.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % PALETTE["TEXT"])
        lay.addWidget(xheading)

        xrow = QHBoxLayout()
        xrow.setSpacing(10)

        def _mini2(caption_text, object_name, placeholder):
            cap = QLabel(caption_text, card)
            cap.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
            xrow.addWidget(cap)
            edit = QLineEdit(card)
            edit.setObjectName(object_name)
            edit.setPlaceholderText(placeholder)
            xrow.addWidget(edit)
            return edit

        self._exit_band_edit = _mini2("نطاق العبور %", "MonitoringExitBandPct", "0.2")
        self._exit_chase_step_edit = _mini2("خطوة الملاحقة %", "MonitoringExitChaseStepPct", "0.2")
        self._exit_chase_attempts_edit = _mini2("محاولات الملاحقة", "MonitoringExitChaseAttempts", "6")
        self._exit_chase_interval_edit = _mini2("مهلة الملاحقة ث", "MonitoringExitChaseIntervalS", "0.5")
        self._exit_stop_offset_edit = _mini2("إزاحة ستوب الحارس %", "MonitoringExitStopOffsetPct", "0.3")

        lay.addLayout(xrow)

        self._bracket_hint = QLabel("", card)
        self._bracket_hint.setObjectName("MonitoringBracketHint")
        self._bracket_hint.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
        self._bracket_hint.setVisible(False)
        lay.addWidget(self._bracket_hint)

        # G1.46: بطاقة نتيجة الصفقة أسفل وسيلة قوس الخروج بالسعر (PRICE_BRACKET).
        try:
            _drc = DealResultCard(card)
            _drc.setObjectName("MonitoringDealResultBracket")
            self._deal_result_cards["PRICE_BRACKET"] = _drc
            lay.addWidget(_drc)
        except Exception:
            self._deal_result_cards["PRICE_BRACKET"] = None

        root.addWidget(card)

    def _on_bracket_changed(self, *args):
        """يحدّث تلميح التحقّق فقط (سفلي < الحالي < علوي؛ تحذير لو مقلوب). لا تنفيذ."""
        hint = getattr(self, "_bracket_hint", None)
        if hint is None:
            return
        lo = self._bracket_lower_edit.text() if getattr(self, "_bracket_lower_edit", None) is not None else None
        up = self._bracket_upper_edit.text() if getattr(self, "_bracket_upper_edit", None) is not None else None
        v = validate_bracket(lo, up, getattr(self, "_current_price", None))
        if v["inverted"]:
            hint.setText(i18n.translate_for_current("⚠ الحدّ السفلي يجب أن يكون أقلّ من العلوي."))
            hint.setVisible(True)
        elif v.get("in_range") is False:
            hint.setText(i18n.translate_for_current("⚠ السعر الحالي خارج الحدّين."))
            hint.setVisible(True)
        else:
            hint.setText("")
            hint.setVisible(False)

    def bracket_config(self):
        """يُعيد ``BracketConfig`` الحيّة من الواجهة (None-safe؛ الافتراضي مطفأ).

        G1.33: يقرأ أيضًا نِسب التسعير القابلة للتعديل؛ الفارغ ⇒ الافتراضي القديم.
        """
        def _txt(attr):
            e = getattr(self, attr, None)
            return e.text() if e is not None else None
        toggle = getattr(self, "_bracket_enable_toggle", None)
        enabled = bool(toggle.isChecked()) if toggle is not None else False
        return BracketConfig.from_inputs(
            enabled, _txt("_bracket_lower_edit"), _txt("_bracket_upper_edit"),
            slip_pct=_txt("_bracket_slip_edit"), sl_pct=_txt("_bracket_sl_edit"),
            floor_pct=_txt("_bracket_floor_edit"), gap_ticks=_txt("_bracket_gap_edit"),
        )

    def exit_policy_values(self):
        """G1.49: قيم سياسة تنفيذ الخروج الموحّدة من الواجهة (الفارغ/غير الصالح ⇒ None).

        عرض/ضبط فقط لطبقة الربط عند تسليح الخروج الحيّ؛ لا تنفيذ هنا ولا لمس hot_path.
        None لأي حقل ⇒ استعمال الافتراضي في ExitExecutionPolicy / الوسيلة المعنيّة.
        """
        def _dec(attr):
            e = getattr(self, attr, None)
            if e is None:
                return None
            t = (e.text() or "").strip()
            if not t:
                return None
            try:
                v = Decimal(t)
            except (InvalidOperation, ValueError):
                return None
            return v if v >= 0 else None

        def _int(attr):
            e = getattr(self, attr, None)
            if e is None:
                return None
            t = (e.text() or "").strip()
            if not t:
                return None
            try:
                v = int(t)
            except (TypeError, ValueError):
                return None
            return v if v >= 1 else None

        return {
            "band_pct": _dec("_exit_band_edit"),
            "chase_step_pct": _dec("_exit_chase_step_edit"),
            "chase_max_attempts": _int("_exit_chase_attempts_edit"),
            "chase_interval_s": _dec("_exit_chase_interval_edit"),
            "stop_limit_offset_pct": _dec("_exit_stop_offset_edit"),
        }

    def exit_execution_policy(self):
        """G1.49: يبني ``ExitExecutionPolicy`` من قيم الواجهة (None ⇒ الافتراضي)."""
        from ocobot.domain.market_exit import ExitExecutionPolicy
        v = self.exit_policy_values()
        pol = ExitExecutionPolicy()
        if v["band_pct"] is not None:
            pol.band_pct = v["band_pct"]
        if v["chase_step_pct"] is not None:
            pol.chase_step_pct = v["chase_step_pct"]
        if v["chase_max_attempts"] is not None:
            pol.chase_max_attempts = v["chase_max_attempts"]
        return pol

    # ---- G1.34: بانل «الأمر النشط بعد الملامسة» ----
    def _build_active_order_panel(self, root):
        """G1.34: بانل عرضيّ تحت خانات الحدود يُظهر الأمر الجديد بعد ملامسة القوس.

        إضافيّ بالكامل (عرض فقط): لا يمسّ المحرّك ولا أيّ أمر على Binance. مخفيّ حتى
        أوّل ملامسة تضع أمرًا جديدًا؛ يبقى ظاهرًا حتى ملامسة جديدة تستبدل محتواه.
        """
        card = QFrame(self)
        card.setObjectName("MonitoringActiveOrderCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringActiveOrderCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        heading = QLabel("الأمر النشط بعد الملامسة", card)
        heading.setObjectName("MonitoringActiveOrderHeading")
        heading.setStyleSheet("color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"])
        lay.addWidget(heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 160)
        self._active_order_values = {}
        for r, (key, label) in enumerate(ACTIVE_ORDER_FIELDS):
            cap = QLabel(label, card)
            cap.setStyleSheet("color:%s;font-size:12px;" % PALETTE["MUTED"])
            val = QLabel(EMPTY, card)
            val.setObjectName("MonitoringActiveOrder_%s" % key)
            val.setStyleSheet("color:%s;font-size:13px;font-weight:700;" % PALETTE["TEXT"])
            grid.addWidget(cap, r, 0)
            grid.addWidget(val, r, 1)
            self._active_order_values[key] = val
        lay.addLayout(grid)

        self._active_order_card = card
        card.setVisible(False)  # مخفيّ حتى أوّل ملامسة
        root.addWidget(card)

    def _refresh_active_order_panel(self):
        """يملأ/يُظهر/يُخفي بانل الأمر النشط وفق ``self._active_order`` (عرض فقط)."""
        card = getattr(self, "_active_order_card", None)
        if card is None:
            return
        ao = self._active_order
        if not ao:
            card.setVisible(False)
            return
        display = {
            "list_id": str(ao.get("list_id")) if ao.get("list_id") is not None else EMPTY,
            "type": ao.get("type") or EMPTY,
            "limit": fmt(ao.get("limit")) if ao.get("limit") is not None else EMPTY,
            "stop": fmt(ao.get("stop")) if ao.get("stop") is not None else EMPTY,
            "qty": fmt(ao.get("qty")) if ao.get("qty") is not None else EMPTY,
            "reason": ao.get("reason") or EMPTY,
            "time": ao.get("time") or EMPTY,
        }
        for key, lbl in self._active_order_values.items():
            lbl.setText(display.get(key, EMPTY))
        card.setVisible(True)

    # ---- كشف تدريجي ----
    def _build_guardian_row(self, root):
        """G1.31 (chunk_3): صفّ شبكة أمان المركز — شارة الحارس + مُبدِّل الوضع.

        إضافيّ بالكامل: لا يمسّ/يعيد ترتيب أي عنصر قائم. المُبدِّل يبدأ على
        ``OFF`` (أول عنصر) فلا يتغيّر السلوك الافتراضي (لا تدخّل). لا شبكة هنا.
        """
        card = QFrame(self)
        card.setObjectName("MonitoringGuardianCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringGuardianCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        heading = QLabel("شبكة أمان المركز", card)
        heading.setObjectName("MonitoringGuardianHeading")
        heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(12)

        # شارة الحارس (عرض فقط — تُحدَّث عبر set_guardian_status).
        self.guardian_indicator = GuardianIndicator(card)
        row.addWidget(self.guardian_indicator)

        row.addStretch(1)

        mode_caption = QLabel("وضع الحارس", card)
        mode_caption.setObjectName("MonitoringGuardianModeCaption")
        mode_caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        row.addWidget(mode_caption)

        # مُبدِّل الوضع: Off (افتراضي) · Observe · Live — بالترتيب نفسه لـ_MODE_ORDER.
        self._guardian_mode_combo = QComboBox(card)
        self._guardian_mode_combo.setObjectName("MonitoringGuardianModeCombo")
        self._guardian_mode_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._guardian_mode_order = [GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE]
        for label in ("مطفأ", "مراقبة", "تدخّل"):
            self._guardian_mode_combo.addItem(label)
        self._guardian_mode_combo.setCurrentIndex(0)  # OFF افتراضيًّا
        self._guardian_mode_combo.currentIndexChanged.connect(self._on_guardian_mode_changed)
        row.addWidget(self._guardian_mode_combo)

        lay.addLayout(row)
        # G1.46: بطاقة نتيجة الصفقة أسفل وسيلة شبكة أمان المركز (POSITION_SAFETY_NET).
        try:
            _drc = DealResultCard(card)
            _drc.setObjectName("MonitoringDealResultSafetyNet")
            self._deal_result_cards["POSITION_SAFETY_NET"] = _drc
            lay.addWidget(_drc)
        except Exception:
            self._deal_result_cards["POSITION_SAFETY_NET"] = None
        root.addWidget(card)

    def _on_guardian_mode_changed(self, index):
        """يحدّث الوضع الداخلي عند تبديل المُبدِّل. تخزين فقط؛ لا تدخّل من هنا."""
        try:
            order = getattr(self, "_guardian_mode_order", None) or [
                GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE
            ]
            if 0 <= index < len(order):
                self._guardian_mode = order[index]
        except Exception:
            self._guardian_mode = GuardianMode.OFF

    # ---- واجهة الحارس العامّة (G1.31) ----
    def guardian_mode(self):
        """يُعيد ``GuardianMode`` المختار حاليًّا من المُبدِّل."""
        return getattr(self, "_guardian_mode", GuardianMode.OFF)

    def set_guardian_mode(self, mode):
        """يضبط الوضع برمجيًّا ويزامن المُبدِّل. None-safe (الافتراضي OFF)."""
        try:
            order = getattr(self, "_guardian_mode_order", None) or [
                GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE
            ]
            target = mode if mode in order else GuardianMode.OFF
            self._guardian_mode = target
            combo = getattr(self, "_guardian_mode_combo", None)
            if combo is not None:
                combo.setCurrentIndex(order.index(target))
        except Exception:
            self._guardian_mode = GuardianMode.OFF

    def set_guardian_status(self, status):
        """يحدّث شارة الحارس من ``GuardianStatus`` (عرض فقط). None-safe."""
        indicator = getattr(self, "guardian_indicator", None)
        if indicator is not None and status is not None:
            try:
                indicator.update_status(status)
            except Exception:
                pass

    # ---- G1.44 / chunk_4: صفّ حارس هبوط BTC المستقلّ (مؤشّر + مُبدِّل) --------
    def _build_btc_follow_row(self, root):
        """صفّ حارس هبوط BTC — مؤشّر حالة + مُبدِّل Off/Observe/Live مستقلّ.

        إضافيّ بالكامل ومرآة لصفّ شبكة أمان المركز. المُبدِّل يبدأ على ``OFF``
        (أول عنصر) فلا يتغيّر السلوك الافتراضي (لا تدخّل). لا شبكة هنا.
        """
        card = QFrame(self)
        card.setObjectName("MonitoringBtcFollowCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringBtcFollowCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        heading = QLabel("حارس هبوط BTC", card)
        heading.setObjectName("MonitoringBtcFollowHeading")
        heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.btc_follow_indicator = BtcFollowIndicator(card)
        self.btc_follow_indicator.setObjectName("MonitoringBtcFollowIndicator")
        row.addWidget(self.btc_follow_indicator)

        row.addStretch(1)

        mode_caption = QLabel("وضع حارس BTC", card)
        mode_caption.setObjectName("MonitoringBtcFollowModeCaption")
        mode_caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])
        row.addWidget(mode_caption)

        self._btc_follow_mode_combo = QComboBox(card)
        self._btc_follow_mode_combo.setObjectName("MonitoringBtcFollowModeCombo")
        self._btc_follow_mode_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._btc_follow_mode_order = [GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE]
        for label in ("مطفأ", "مراقبة", "تدخّل"):
            self._btc_follow_mode_combo.addItem(label)
        self._btc_follow_mode_combo.setCurrentIndex(0)  # OFF افتراضيًّا
        self._btc_follow_mode_combo.currentIndexChanged.connect(self._on_btc_follow_mode_changed)
        row.addWidget(self._btc_follow_mode_combo)

        lay.addLayout(row)

        # G1.45: لوحة تتبّع نسبة BTC اللحظية (عرض فقط) داخل بطاقة حارس هبوط BTC.
        try:
            self._btc_tracker = PercentTracker(card)
            self._btc_tracker.setObjectName("MonitoringBtcPercentTracker")
            lay.addWidget(self._btc_tracker)
        except Exception:
            self._btc_tracker = None

        # G1.50: لوحة انزلاق BTC بنافذة متحرّكة (عرض فقط) بجوار لوحة التتبّع.
        try:
            self._btc_slip_tracker = BtcSlippageTracker(card)
            self._btc_slip_tracker.setObjectName("MonitoringBtcSlippageTracker")
            lay.addWidget(self._btc_slip_tracker)
        except Exception:
            self._btc_slip_tracker = None

        # G1.46: بطاقة نتيجة الصفقة أسفل وسيلة حارس هبوط BTC (BTC_FOLLOW).
        try:
            _drc = DealResultCard(card)
            _drc.setObjectName("MonitoringDealResultBtcFollow")
            self._deal_result_cards["BTC_FOLLOW"] = _drc
            lay.addWidget(_drc)
        except Exception:
            self._deal_result_cards["BTC_FOLLOW"] = None

        root.addWidget(card)

    def _build_monitored_tracker_row(self, root):
        """G1.45: بطاقة تتبّع نسبة العملة المراقَبة من سعر بدء المراقبة المثبّت (عرض فقط)."""
        card = QFrame(self)
        card.setObjectName("MonitoringMonitoredTrackerCard")
        card.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        card.setStyleSheet(
            "QFrame#MonitoringMonitoredTrackerCard{background:%s;border:1px solid %s;"
            "border-radius:12px;}" % (PALETTE["CARD_ALT"], PALETTE["BORDER"])
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        heading = QLabel("تتبّع العملة المراقَبة", card)
        heading.setObjectName("MonitoringMonitoredTrackerHeading")
        heading.setStyleSheet(
            "color:%s;font-size:15px;font-weight:700;" % PALETTE["TEXT"]
        )
        lay.addWidget(heading)

        try:
            self._monitored_tracker = PercentTracker(card)
            self._monitored_tracker.setObjectName("MonitoringMonitoredPercentTracker")
            lay.addWidget(self._monitored_tracker)
        except Exception:
            self._monitored_tracker = None

        root.addWidget(card)

    def _on_btc_follow_mode_changed(self, index):
        """يحدّث وضع حارس BTC الداخلي عند تبديل المُبدِّل. تخزين فقط؛ لا تدخّل من هنا."""
        try:
            order = getattr(self, "_btc_follow_mode_order", None) or [
                GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE
            ]
            if 0 <= index < len(order):
                self._btc_follow_mode = order[index]
        except Exception:
            self._btc_follow_mode = GuardianMode.OFF

    def btc_follow_mode(self):
        """يُعيد ``GuardianMode`` المختار حاليًّا لحارس هبوط BTC."""
        return getattr(self, "_btc_follow_mode", GuardianMode.OFF)

    # اسم بديل متوافق مع صياغة get_* المطلوبة.
    def get_btc_follow_mode(self):
        return self.btc_follow_mode()

    def set_btc_follow_mode(self, mode):
        """يضبط وضع حارس BTC برمجيًّا ويزامن المُبدِّل. None-safe (الافتراضي OFF)."""
        try:
            order = getattr(self, "_btc_follow_mode_order", None) or [
                GuardianMode.OFF, GuardianMode.OBSERVE, GuardianMode.LIVE
            ]
            target = mode if mode in order else GuardianMode.OFF
            self._btc_follow_mode = target
            combo = getattr(self, "_btc_follow_mode_combo", None)
            if combo is not None:
                combo.setCurrentIndex(order.index(target))
        except Exception:
            self._btc_follow_mode = GuardianMode.OFF

    def set_btc_follow_status(self, status):
        """يحدّث مؤشّر حارس BTC من ``GuardianStatus`` (عرض فقط). None-safe."""
        indicator = getattr(self, "btc_follow_indicator", None)
        if indicator is not None and status is not None:
            try:
                indicator.update_status(status)
            except Exception:
                pass

    def _on_enable_toggled(self, checked):
        for w in self._pct_widgets:
            w.setVisible(bool(checked))
        self._refresh_live_panel()

    # ---- حقن السياق ----
    def set_deal_results(self, trades):
        """G1.46: يحدّث بطاقة نتيجة الصفقة لكل وسيلة من أحدث صفقة مُغلقة مُسنَدة إليها.

        عرض فقط: يختار آخر صفقة ``status == "closed"`` لكل ``exit_source`` ويعرضها
        أسفل بطاقة الوسيلة المطابقة؛ الوسائل بلا نتيجة تُخفى بطاقتها. محروس تمامًا.
        """
        cards = getattr(self, "_deal_result_cards", None)
        if not cards:
            return
        latest = {}
        for tr in (trades or []):
            if getattr(tr, "status", "") != "closed":
                continue
            src = getattr(tr, "exit_source", "") or "MONITORING"
            latest[src] = tr
        for src, card in cards.items():
            if card is None:
                continue
            try:
                card.update_result(latest.get(src))
            except Exception:
                pass

    # ---- G1.46.1: الاستدعاء التلقائي لتعبئة بطاقة نتيجة الصفقة (عرض فقط) ----
    def refresh_deal_results(self):
        """G1.46.1: يحمّل الصفقات المنتهية (قراءة فقط) ويعبّئ بطاقات نتيجة الصفقة.

        يُستدعى تلقائيًّا عند إظهار الشاشة (التنقّل) ودوريًّا (1s) أثناء ظهورها.
        عبر الرَنَر إن توفّر لتفادي أي IO على خيط الواجهة؛ وإلّا متزامنًا (اختبارات).
        إضافة عرض-فقط محروسة (fail-safe): لا شبكة، ولا مساس بأي منطق تنفيذ/إصدار.
        """
        def _load():
            return load_completed_trades(self._deal_audit_path, self._deal_dismiss_path)

        try:
            if self.runner is not None:
                return self.runner.submit(_load, on_result=self.set_deal_results)
            self.set_deal_results(_load())
        except Exception:
            # قراءة عرض-فقط؛ أي تعذّر (ملف غائب/تالف) لا يكسر الشاشة.
            pass
        return None

    def showEvent(self, event):
        """G1.46.1: عند التنقّل إلى الشاشة: تعبئة فورية ثم بدء المؤقّت الدوري (1s)."""
        super().showEvent(event)
        self.refresh_deal_results()
        try:
            self._deal_results_timer.start()
        except Exception:
            pass

    def hideEvent(self, event):
        """G1.46.1: عند إخفاء الشاشة: إيقاف المؤقّت الدوري (لا IO وهي مخفية)."""
        try:
            self._deal_results_timer.stop()
        except Exception:
            pass
        super().hideEvent(event)

    def set_manual_exit_fn(self, fn):
        """G1.47: حقن/تحديث callable الخروج اليدوي الفوري (أو None) — تخزين فقط.
        None-safe؛ لا شبكة هنا (التنفيذ يجري على خيط الرَنَر عند الضغط)."""
        self._manual_exit_fn = fn

    def set_convert_cb(self, convert_cb):
        """حقن/تحديث callback التحويل إلى OCO (G1.13 CHUNK 1 — plumbing، تخزين فقط)."""
        self._convert_cb = convert_cb

    def set_engine(self, engine):
        """G1.18: حقن/تحديث المحرّك (MonitoringEngine) بعد نجاح الاتصال — تخزين فقط
        ثم تحديث لوحة التحكّم/حالة الأزرار. None-safe؛ لا أمر ولا شبكة هنا."""
        self._engine = engine
        self._refresh_live_panel()

    def set_price_provider(self, price_provider):
        """G1.18: حقن/تحديث مزوّد السعر الحيّ (يستهلكه refresh_price/اللوحة الحيّة)
        — تخزين فقط. None-safe؛ لا شبكة هنا (الجلب يبقى داخل refresh_price)."""
        self._price_provider = price_provider

    def set_btc_price_provider(self, provider):
        """G1.45: حقن موفّر سعر BTCUSDT الحيّ (callable أو None). تخزين فقط؛ لا شبكة
        في الواجهة — السحب يجري على نبض المراقبة خارج خيط الواجهة (fail-safe)."""
        self._btc_price_provider = provider

    def set_selected(self, selected):
        """يضبط الـ OCO المختار (SelectedOCO أو None) ويحدّث اللوحة الحيّة."""
        self._selected = selected
        self._monitored_anchor = None  # G1.45: جلسة مراقبة جديدة ⇒ أعِد تجميد السعر المرجعي
        self._monitored_prev = None    # G1.48: جلسة جديدة ⇒ صفّر مراجع التغيّر/التتبّع
        self._monitored_last = None
        self._btc_anchor = None
        if selected is None:
            self._current_price = None
        else:
            # قد يحمل الهدف سعرًا مرجعيًا حقيقيًا مبدئيًا (يُستبدَل بأول tick حيّ).
            self._current_price = getattr(selected, "current_price", None)
        self._refresh_live_panel()

    def set_current_price(self, price):
        """خُطّاف حقن السعر الحيّ الحقيقي (يستدعيه الرَنَر/الاختبار). لا شبكة هنا."""
        self._current_price = price
        self._refresh_live_panel()

    def refresh_price(self, price_provider=None):
        """يجلب السعر الحيّ عبر ``price_provider`` المحقون (WS مع سقوط REST).

        مع runner يُنفَّذ على خيط منفصل (T10c)؛ بلا runner يُنفَّذ متزامنًا (اختبارات).
        لا شبكة في هذه الطبقة — كل IO داخل المزوّد المحقون خارج خيط الواجهة.
        """
        provider = price_provider or self._price_provider
        if provider is None:
            return None
        if self.runner is not None:
            return self.runner.submit(provider, on_result=self.set_current_price)
        self.set_current_price(provider())
        return None

    # ---- G1.8: حلقة التحديث الحيّ الدوري (بلا QTimer؛ نبضات عبر AsyncRunner) ----
    def start_live_updates(self):
        """يبدأ حلقة النبض الحيّة (لا تعمل بلا رَنَر حقيقي أو بلا مزوّد سعر)."""
        if self.runner is None or self._price_provider is None or self._ticking:
            return
        self._ticking = True
        self._schedule_tick()

    def stop_live_updates(self):
        """يوقف حلقة النبض (لا يمسّ المحرّك ولا أي أمر على Binance)."""
        self._ticking = False

    def _active_for_ticking(self):
        """هل المراقبة في حالة تسمح باستمرار النبض؟ (نشطة/مُفعَّلة فقط)."""
        return self._engine_state_name() in ("MONITORING_ACTIVE", "TRIGGERED")

    def _schedule_tick(self):
        """يجدول نبضة واحدة: مباعدة + جلب سعر + تغذية المحرّك، كلّها خارج خيط الواجهة."""
        if not self._ticking or self.runner is None or self._price_provider is None:
            return
        provider = self._price_provider
        engine = self._engine
        interval = self._tick_interval

        def _work():
            if interval:
                time.sleep(interval)
            price = provider()
            tick = None
            if (engine is not None and engine.state.enabled
                    and engine.state.state in (MonitoringStateEnum.MONITORING_ACTIVE,
                                               MonitoringStateEnum.TRIGGERED)):
                tick = engine.on_price_tick(price)
            # G1.45: سحب سعر BTC على النبض القائم (خارج خيط الواجهة) وتغذية مُشرِف
            # العرض ثم أخذ لقطة — مستقلّ عن وضع حارس BTC، fail-safe (لا يرمي).
            btc_snap = None
            try:
                prov = self._btc_price_provider
                sup = self._btc_display_sup
                if prov is not None and sup is not None:
                    bp = prov()
                    if bp is not None:
                        sup.ingest(bp)
                    btc_snap = sup.price_snapshot()
            except Exception:
                btc_snap = None
            return price, tick, btc_snap

        self.runner.submit(_work, on_result=self._on_live_tick,
                           on_error=self._on_tick_error)

    def _on_live_tick(self, result):
        """على خيط الواجهة: حدّث السعر/العرض، ثم أعِد التسليح إن بقيت المراقبة نشطة."""
        btc_snap = None
        try:
            if isinstance(result, tuple) and len(result) == 3:
                price, tick, btc_snap = result
            elif isinstance(result, tuple) and len(result) == 2:
                price, tick = result
            else:
                price, tick = result, None
        except (TypeError, ValueError):
            price, tick, btc_snap = result, None, None
        self._current_price = price
        event = getattr(tick, "event", "") if tick is not None else ""
        if event == "REPOSITIONED":
            # G1.34: ملامسة القوس ووضع أمر جديد ⇒ حالة عرضية ORDER_PLACED + رسالة التنقّل
            #        الجديدة بدل «أعيد التموضع إلى OCO …» + التقاط الأمر النشط (عرض فقط).
            new_msg = self._capture_active_order(tick, price)
            if new_msg:
                self._set_last_operation("مراقبة", new_msg)
            # G1.10: دحرجة مصدر الخانات الثلاث في اللوحة الحية إلى قيم الـ OCO الجديد (عرض فقط)
            res = getattr(tick, "execution_result", None)
            if res is not None and self._selected is not None:
                new_id = getattr(res, "new_order_list_id", None)
                if new_id is not None:
                    self._selected.order_list_id = new_id
                draft = getattr(res, "draft", None)
                if draft is not None:
                    if getattr(draft, "tp_price", None) is not None:
                        self._selected.tp = draft.tp_price
                    if getattr(draft, "stop_trigger", None) is not None:
                        self._selected.stop_trigger = draft.stop_trigger
                    if getattr(draft, "stop_limit", None) is not None:
                        self._selected.stop_limit = draft.stop_limit
        elif (tick is not None and event not in ("IDLE", "PAUSED")
                and getattr(tick, "message", "")):
            self._set_last_operation("مراقبة", tick.message)
        self._refresh_btc_tracker(btc_snap)
        self._refresh_btc_slip_tracker()
        self._refresh_live_panel()
        if self._ticking and self._active_for_ticking():
            self._schedule_tick()
        else:
            self._ticking = False

    def _on_tick_error(self, exc):
        """فشل جلب/معالجة النبضة: اعرض السبب وأعِد المحاولة إن بقيت المراقبة نشطة."""
        self._set_last_operation("مراقبة", str(exc))
        self._refresh_live_panel()
        if self._ticking and self._active_for_ticking():
            self._schedule_tick()
        else:
            self._ticking = False

    # ---- G1.45: تحديث لوحات التتبّع (عرض فقط؛ fail-safe) ----
    def _refresh_btc_tracker(self, snap):
        """يحدّث لوحة BTC من لقطة (last, prev, window_start). None-safe؛ لا يرمي.

        G1.48: «نسبة التغيّر» عن السعر السابق (prev — لكل انتقال)، و«نسبة التتبّع» عن
        سعر BTC المُجمّد عند بدء المراقبة (_btc_anchor = أول window_start صالح) بدل
        النافذة المتدحرجة."""
        tr = getattr(self, "_btc_tracker", None)
        if tr is None or not snap:
            return
        try:
            last, prev, wstart = snap
            if self._btc_anchor is None and wstart is not None:
                self._btc_anchor = wstart  # تجميد مرّة واحدة عند بدء المراقبة
            tr.update_prices(last, prev, self._btc_anchor)
        except Exception:
            pass

    def _refresh_btc_slip_tracker(self):
        """G1.50: يحدّث لوحة انزلاق BTC بنافذة متحرّكة قراءةً فقط من مُشرِف العرض. fail-safe."""
        tr = getattr(self, "_btc_slip_tracker", None)
        if tr is None:
            return
        try:
            sup = getattr(self, "_btc_display_sup", None)
            if sup is None:
                tr.update_slippage(None, None, None, None)
                return
            samples = tuple(getattr(sup, "_samples", ()) or ())
            now = float(sup._time_fn())
            window = float(getattr(sup.config, "window_seconds", 3.0))
            slip = window_slippage(samples, now, window)
            phase = getattr(getattr(sup, "state", None), "phase", None)
            phase_val = getattr(phase, "value", None)
            if slip is None:
                tr.update_slippage(None, None, None, phase_val)
            else:
                tr.update_slippage(slip["current"], slip["peak"], slip["drop_pct"], phase_val)
        except Exception:
            try:
                tr.update_slippage(None, None, None, None)
            except Exception:
                pass

    def _refresh_monitored_tracker(self):
        """يحدّث لوحة العملة المراقَبة (G1.48): «نسبة التغيّر» لكل انتقال سعري لحظي
        (مقابل آخر سعر حيّ سابق)، و«نسبة التتبّع» مقابل سعر بدء المراقبة المُجمّد
        (reference_price الثابت عبر إعادة التموضع). fail-safe."""
        tr = getattr(self, "_monitored_tracker", None)
        if tr is None:
            return
        try:
            if self._monitored_anchor is None and self._engine is not None:
                ref = getattr(getattr(self._engine, "state", None), "reference_price", None)
                if ref is not None:
                    self._monitored_anchor = ref  # تجميد لمرّة واحدة (ثابت عبر reposition)
            cur = self._current_price
            # دحرجة السعر السابق على كل انتقال سعري فعلي فقط (يُثبَّت بين النبضات
            # المتساوية فلا تُصفَّر «نسبة التغيّر» دون انتقال).
            if cur is not None:
                if self._monitored_last is None:
                    self._monitored_last = cur
                elif cur != self._monitored_last:
                    self._monitored_prev = self._monitored_last
                    self._monitored_last = cur
            # «التغيّر» عن السعر السابق (rolling) · «التتبّع» عن المرساة المُجمّدة.
            tr.update_prices(cur, self._monitored_prev, self._monitored_anchor)
        except Exception:
            pass

    # ---- أزرار التحكّم ----
    def _on_start_clicked(self, *args):
        """يبدأ المراقبة على المحرّك المحقون بالسعر الحيّ الحقيقي (D14)."""
        engine = self._engine
        selected = self._selected
        if engine is None or selected is None:
            return
        # G1.13 (CHUNK 2): تحويل-عند-البدء — إن كان الهدف مرشّح تحويل (أمر بيع
        # مستقل غير OCO) نُحوّله إلى OCO أولًا عبر convert_cb المحقون (بالسعر الحيّ
        # D14)، ثم نُرقّيه في مكانه ونكمل مسار البدء العادي. لا نمسّ أيّ أمر على
        # Binance مباشرةً من الواجهة (P2/P3) — كل التنفيذ داخل convert_cb المحقون.
        if getattr(selected, "is_convert_candidate", False):
            if self._convert_cb is None:  # دفاعي: لا يمكن التحويل بلا callback
                self._set_last_operation(
                    "تحويل", "تعذّر التحويل — لا مُحوِّل متاح"
                )
                self._refresh_live_panel()
                return
            source = getattr(selected, "source_order", None)
            if source is None:  # دفاعي: لا نملك الأمر المصدر الكامل
                self._set_last_operation(
                    "تحويل", "تعذّر التحويل — لا أمر مصدر"
                )
                self._refresh_live_panel()
                return
            tp_text = self._pct_edits["tp_pct"].text().strip()
            sl_text = self._pct_edits["sl_pct"].text().strip()
            try:
                # convert_cb يجلب السعر الحيّ عند غياب reference_price (D14) ثم
                # يفوّض إلى ConvertExecutor.convert؛ لا شبكة في طبقة الواجهة.
                result = self._convert_cb(source, tp_text, sl_text)
            except Exception as exc:  # noqa: BLE001 — يُعرَض دون كسر الواجهة ولا بدء
                self._set_last_operation("تحويل", str(exc))
                self._refresh_live_panel()
                return
            # نجاح التحويل: نفس معيار نجاح tick إعادة التموضع — SUCCESS + معرّف جديد.
            new_id = getattr(result, "new_order_list_id", None)
            is_success = (
                getattr(result, "state", None) == ExecutionState.SUCCESS
                and new_id is not None
            )
            if not is_success:
                # ABORTED / FAILED_NEEDS_ATTENTION / بلا معرّف جديد — لا بدء ولا ترقية.
                detail = getattr(result, "reason", "") or "فشل التحويل"
                messages = getattr(result, "messages", None)
                if messages:
                    detail = "%s — %s" % (detail, " · ".join(str(m) for m in messages))
                self._set_last_operation("تحويل", detail)
                self._refresh_live_panel()
                return
            # ترقية في المكان: صار الهدف OCO حقيقيًا بمعرّف جديد — نُكمل البدء.
            selected.order_list_id = new_id
            selected.is_convert_candidate = False
            self._set_last_operation("تحويل", i18n.translate_for_current("تم التحويل إلى OCO — بدء المراقبة"))
            # G1.13: إن لم يصل سعر حيّ للشاشة بعد، نبذر المرجع من نتيجة التحويل
            # (السعر الحيّ الذي استعمله التحويل — D14، موجود على ExecutionResult).
            # بيانات محليّة فقط: لا شبكة (يحترم حارس test_ui_no_direct_network).
            ref = getattr(getattr(result, "draft", None), "reference_price", None)
            if ref is not None and self._current_price is None:
                self._current_price = ref
        reference = self._current_price
        if reference is None:  # D14: لا بدء بلا سعر حيّ حقيقي
            reference = getattr(selected, "current_price", None)
        if reference is None:
            self._set_last_operation("بدء", i18n.translate_for_current("تعذّر البدء — لا سعر حيّ بعد"))
            self._refresh_live_panel()
            return
        trigger = self._pct_edits["trigger_pct"].text().strip()
        tp = self._pct_edits["tp_pct"].text().strip()
        sl = self._pct_edits["sl_pct"].text().strip()
        try:
            engine.start(selected, trigger, tp, sl, reference)
            # G1.34: جلسة مراقبة جديدة ⇒ صفّر الحالة العرضية وبانل الأمر النشط السابق.
            self._active_order = None
            self._display_state = None
            self._set_last_operation("بدء", i18n.translate_for_current("بدأت المراقبة"))
            self.start_live_updates()
        except Exception as exc:  # noqa: BLE001 — يُعرَض دون كسر الواجهة
            self._set_last_operation("بدء", str(exc))
        self._sync_pause_resume_label()
        self._refresh_live_panel()

    def _on_pause_resume_clicked(self, *args):
        """Pause يُبقي OCO الحقيقي كما هو (P2/P3)؛ Resume يستأنف من نفس النقطة."""
        engine = self._engine
        if engine is None:
            return
        state = self._engine_state_name()
        if state == "PAUSED":
            tick = engine.resume()
            self._set_last_operation("استئناف", getattr(tick, "message", ""))
            self.start_live_updates()
        else:
            tick = engine.pause()  # لا يمسّ أي أمر على Binance
            self._set_last_operation("إيقاف مؤقت", getattr(tick, "message", ""))
            self.stop_live_updates()
        self._sync_pause_resume_label()
        self._refresh_live_panel()

    def _on_manual_exit_clicked(self, *args):
        """G1.47: يُطلق الخروج اليدوي الفوري عبر الـ callable المحقون (لا شبكة في
        الواجهة؛ التنفيذ على خيط الرَنَر). الأولوية بنيوية: بإغلاق المركز تصبح
        الوسائل الأربع idempotent بلا فعل."""
        fn = self._manual_exit_fn
        if fn is None:
            self._set_last_operation("تنفيذ الخروج الفوري", "غير متاح — لا تنفيذ محقون")
            return
        if self.runner is not None:
            self.runner.submit(fn, on_result=self._on_manual_exit_result)
        else:
            self._on_manual_exit_result(fn())  # متزامن (اختبارات)

    def _on_manual_exit_result(self, result):
        """يعرض ملخّص نتيجة الخروج اليدوي في «آخر عملية» (عرض فقط، None-safe)."""
        if isinstance(result, dict):
            action = result.get("action")
            placed = result.get("placed")
        else:
            action = getattr(result, "action", None)
            placed = getattr(result, "placed", None)
        if placed:
            message = "تمّ وضع أمر الخروج اليدوي (%s)" % (action or "PLACED")
        else:
            message = "نتيجة الخروج اليدوي: %s" % (action or "—")
        self._set_last_operation("تنفيذ الخروج الفوري", message)
        self._refresh_live_panel()

    def _on_kill_switch_clicked(self, *args):
        """Kill Switch يوقف كل المراقبة فورًا دون إلغاء أي أمر على Binance."""
        engine = self._engine
        if engine is None:
            return
        tick = engine.kill_switch()  # المحرّك لا يستدعي أي cancel
        # الرسالة يجب أن تطابق MSG_KILL_SWITCH حرفيًا.
        message = getattr(tick, "message", None) or MSG_KILL_SWITCH
        self._set_last_operation("إيقاف طارئ", message)
        self.stop_live_updates()
        self._monitored_anchor = None  # G1.45: إيقاف طارئ ⇒ أعِد تجميد السعر المرجعي
        self._monitored_prev = None    # G1.48: إيقاف طارئ ⇒ صفّر مراجع التغيّر/التتبّع
        self._monitored_last = None
        self._btc_anchor = None
        self._sync_pause_resume_label()
        self._refresh_live_panel()

    # ---- مساعدات الحالة ----
    def _engine_state(self):
        engine = self._engine
        if engine is None:
            return None
        return getattr(getattr(engine, "state", None), "state", None)

    def _engine_state_name(self):
        state = self._engine_state()
        if state is None:
            return None
        return getattr(state, "value", None) or getattr(state, "name", None) or str(state)

    def _sync_pause_resume_label(self):
        """يبدّل عنوان الزر بين Pause/Resume وفق حالة المحرّك."""
        self.pause_resume_button.setText(
            i18n.translate_for_current("استئناف")
            if self._engine_state_name() == "PAUSED"
            else i18n.translate_for_current("إيقاف مؤقت")
        )

    def _set_last_operation(self, operation, result):
        op = i18n.translate_for_current(operation)
        res = i18n.translate_for_current(result) if result else result
        self._last_operation = "%s — %s" % (op, res) if res else op

    # ---- G1.34: اشتقاق الأمر النشط بعد الملامسة (عرض فقط) ----
    def _bound_touched_for(self, price):
        """يحدّد الحدّ المَلموس (سفلي/علوي) بمقارنة السعر بحدود القوس المُدخَلة.

        يُرجع ``(label, value)`` حيث ``label`` ∈ {"السفلي","العلوي"} أو ``(None, None)``
        عند تعذّر الحسم. قراءة فقط من ``bracket_config`` — لا شبكة ولا تنفيذ.
        """
        try:
            cfg = self.bracket_config()
        except Exception:  # noqa: BLE001 — عرض فقط؛ لا يكسر النبض
            cfg = None
        if cfg is None or price is None:
            return None, None
        try:
            p = price if isinstance(price, Decimal) else Decimal(str(price))
        except (InvalidOperation, ValueError, TypeError):
            return None, None
        lower = getattr(cfg, "lower", None)
        upper = getattr(cfg, "upper", None)
        if lower is not None and p <= lower:
            return "السفلي", lower
        if upper is not None and p >= upper:
            return "العلوي", upper
        if lower is not None and upper is not None:
            return ("السفلي", lower) if abs(p - lower) <= abs(p - upper) else ("العلوي", upper)
        if lower is not None:
            return "السفلي", lower
        if upper is not None:
            return "العلوي", upper
        return None, None

    def _order_placed_message(self, list_id, price, side_label, bound_value):
        """رسالة التنقّل المطلوبة (G1.34) — تحلّ محلّ «أعيد التموضع إلى OCO …»."""
        if side_label:
            bound_txt = i18n.translate_for_current("الحد %s %s") % (
                i18n.translate_for_current(side_label), fmt(bound_value))
        else:
            bound_txt = i18n.translate_for_current("القوس")
        return (i18n.translate_for_current(
                "تم التنقل من التموضع إلى أمر جديد OCO %s بناءً على %s - السعر الحالي %s")
                % (list_id, bound_txt, fmt(price)))

    def _capture_active_order(self, tick, price):
        """يلتقط «الأمر النشط بعد الملامسة» من نتيجة النبضة (عرض فقط) ويضبط الحالة العرضية.

        يُرجع رسالة التنقّل الجاهزة للعرض. لا يمسّ المحرّك ولا أيّ أمر على Binance.
        """
        res = getattr(tick, "execution_result", None)
        list_id = getattr(res, "new_order_list_id", None) if res is not None else None
        draft = getattr(res, "draft", None) if res is not None else None
        side_label, bound_value = self._bound_touched_for(price)
        limit_price = getattr(draft, "tp_price", None) if draft is not None else None
        stop_price = getattr(draft, "stop_trigger", None) if draft is not None else None
        qty = getattr(draft, "quantity", None) if draft is not None else None
        if qty is None and self._selected is not None:
            qty = getattr(self._selected, "quantity", None)
        reason = (i18n.translate_for_current("ملامسة الحد %s") % i18n.translate_for_current(side_label)) if side_label else i18n.translate_for_current("ملامسة القوس")
        self._active_order = {
            "list_id": list_id,
            "type": "SELL OCO",
            "limit": limit_price,
            "stop": stop_price,
            "qty": qty,
            "reason": reason,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "bound_label": side_label,
            "bound_value": bound_value,
            "price": price,
        }
        self._display_state = ORDER_PLACED_STATE
        return self._order_placed_message(list_id, price, side_label, bound_value)

    # ---- اللوحة الحيّة ----
    def _computed_levels(self):
        """يحسب (next_tp, next_trigger, next_sl_limit) من النِّسب + السعر الحيّ.

        حساب نقيّ عبر pricing.compute_levels بلا شبكة؛ لا قيم قبل توفّر سعر حيّ
        حقيقي وtick_size (D14). يُرجع None عند تعذّر الحساب.
        """
        selected = self._selected
        reference = self._current_price
        if selected is None or reference is None:
            return None
        filters = getattr(selected, "filters", None)
        tick = getattr(filters, "tick_size", None) if filters is not None else None
        if tick is None:
            return None
        tp_text = self._pct_edits["tp_pct"].text().strip()
        sl_text = self._pct_edits["sl_pct"].text().strip()
        if not tp_text or not sl_text:
            return None
        try:
            tp, trigger, stop_limit = compute_levels(reference, tp_text, sl_text, tick)
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            return None
        return tp, trigger, stop_limit

    def _trigger_price(self):
        """مستوى التفعيل = reference * (1 + trigger%/100) — حساب نقيّ (لا شبكة)."""
        selected = self._selected
        reference = self._current_price
        if selected is None or reference is None:
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

    def _refresh_live_panel(self, *args):
        """يعيد ملء اللوحة الحيّة كاملةً (كل الحقول تبقى ظاهرة دائمًا)."""
        if not self._live:
            return
        selected = self._selected
        has_selection = selected is not None
        self._note.setText("" if has_selection else NO_SELECTION_NOTE)

        state_name = self._display_state or self._engine_state_name() or "IDLE"
        levels = self._computed_levels()
        trigger_price = self._trigger_price()
        # G1.34: عند وجود «أمر نشط بعد الملامسة» تُعرض قيمه في الخانات الحالية (عرض فقط).
        active = self._active_order
        if active is not None and active.get("limit") is not None:
            current_tp_val = active.get("limit")
        else:
            current_tp_val = getattr(selected, "tp", None) if selected else None
        if active is not None and active.get("stop") is not None:
            current_sl_val = active.get("stop")
        else:
            current_sl_val = getattr(selected, "stop_trigger", None) if selected else None

        # G1.13: مرشّح تحويل بلا orderListId بعد — تلميح عربي بدل None.
        if selected is None:
            order_list_display = None
        elif (getattr(selected, "is_convert_candidate", False)
              or getattr(selected, "order_list_id", None) is None):
            order_list_display = "سيُحوَّل إلى OCO"
        else:
            order_list_display = str(selected.order_list_id)
        values = {
            "symbol": getattr(selected, "symbol", None) if selected else None,
            "order_list_id": order_list_display,
            "current_price": fmt(self._current_price) if self._current_price is not None else EMPTY,
            "reference_price": self._reference_display(),
            "trigger_price": fmt(trigger_price) if trigger_price is not None else EMPTY,
            "current_tp": fmt(current_tp_val) if current_tp_val is not None else EMPTY,
            "current_sl": fmt(current_sl_val) if current_sl_val is not None else EMPTY,
            "next_tp": fmt(levels[0]) if levels else EMPTY,
            "next_sl": fmt(levels[1]) if levels else EMPTY,
            "sl_limit": fmt(levels[2]) if levels else EMPTY,
            "tick_size": self._tick_display(),
            "monitoring_state": state_name,
            "last_operation": getattr(self, "_last_operation", EMPTY) or EMPTY,
            "connection": self._connection_display(),
            "environment": self._environment or EMPTY,
        }
        for key, label in self._live.items():
            val = values.get(key)
            label.setText(EMPTY if val in (None, "") else str(val))

        # G1.13 (CHUNK 2): مرشّح التحويل صار START-able — البدء يُحوّله إلى OCO
        # أولًا (convert-on-start) ثم يبدأ المراقبة. لم يعد is_convert_candidate
        # تعطيلًا صلبًا؛ زرّ البدء يُفعَّل بنفس شرط صحّة OCO (حقول النِّسب الثلاثة).
        # التلميح يصير إرشاديًا (سيُحوَّل عند البدء) بدل منع البدء.
        if hasattr(self, "start_button"):
            is_candidate = bool(getattr(selected, "is_convert_candidate", False)) if selected else False
            self.start_button.setEnabled(True)
            if hasattr(self, "_convert_hint"):
                self._convert_hint.setText(
                    i18n.translate_for_current("سيُحوَّل إلى OCO تلقائيًا عند بدء المراقبة")
                    if is_candidate else ""
                )
                self._convert_hint.setVisible(is_candidate)

        # تلوين حالة المراقبة (D15).
        accent = PALETTE.get(_STATE_ACCENT.get(state_name.upper(), "TEXT"), PALETTE["TEXT"])
        self._live["monitoring_state"].setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % accent
        )

        # G1.34: حدّث بانل «الأمر النشط بعد الملامسة» (يبقى ظاهرًا حتى ملامسة جديدة).
        self._refresh_active_order_panel()

        # G1.45: حدّث لوحة تتبّع العملة المراقَبة (عرض فقط؛ fail-safe).
        try:
            self._refresh_monitored_tracker()
        except Exception:
            pass

    def _reference_display(self):
        engine = self._engine
        ref = None
        if engine is not None:
            ref = getattr(getattr(engine, "state", None), "reference_price", None)
        if ref is None:
            ref = self._current_price
        return fmt(ref) if ref is not None else EMPTY

    def _tick_display(self):
        selected = self._selected
        filters = getattr(selected, "filters", None) if selected else None
        tick = getattr(filters, "tick_size", None) if filters is not None else None
        return fmt(tick) if tick is not None else EMPTY

    def _connection_display(self):
        """يعرض وضع مصدر السعر (WS/REST) من المزوّد المحقون إن كشفه؛ وإلا '—'."""
        provider = self._price_provider
        mode = getattr(provider, "mode", None)
        if mode:
            return str(mode)
        controller = getattr(provider, "__self__", None)  # لو مُمرَّر كـ bound method
        mode = getattr(controller, "mode", None)
        return str(mode) if mode else EMPTY
