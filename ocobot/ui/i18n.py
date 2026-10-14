"""واجهة ثنائية اللغة (عربي/إنجليزي) — طبقة الترجمة والاتجاه.

Bilingual (Arabic/English) UI helper. Arabic is the default source language
and uses a right-to-left layout. This is a standalone module: it holds the
current language state, a canonical Arabic -> English dictionary, and helpers
to translate strings, flip layout direction, and retranslate a widget tree.

Qt-only + stdlib. Imports are kept robust so a missing optional widget class
never breaks module import.
"""

# ---------------------------------------------------------------------------
# Qt imports (via the binding-agnostic shim where possible).
# ---------------------------------------------------------------------------
try:  # core symbols needed for direction handling
    from ._qt import Qt, QApplication  # noqa: F401
except Exception:  # pragma: no cover - defensive
    Qt = None
    QApplication = None

# Determine which Qt binding the shim is using so we can import any widget
# classes it does not re-export, from the SAME binding.
try:
    from ._qt import QT_BINDING as _QT_BINDING
except Exception:  # pragma: no cover - defensive
    _QT_BINDING = None


def _import_widget(name):
    """Return a Qt widget class by name, or None if unavailable.

    Tries the shim first, then the active Qt binding's QtWidgets module.
    """
    # 1) Try the shim.
    try:
        import importlib
        shim = importlib.import_module("ocobot.ui._qt")
        cls = getattr(shim, name, None)
        if cls is not None:
            return cls
    except Exception:
        pass
    # 2) Fall back to the active binding's QtWidgets.
    for binding in ([_QT_BINDING] if _QT_BINDING else []) + ["PySide6", "PyQt6"]:
        if not binding:
            continue
        try:
            import importlib
            mod = importlib.import_module(binding + ".QtWidgets")
            cls = getattr(mod, name, None)
            if cls is not None:
                return cls
        except Exception:
            continue
    return None


QWidget = _import_widget("QWidget")
QLabel = _import_widget("QLabel")
QPushButton = _import_widget("QPushButton")
QCheckBox = _import_widget("QCheckBox")
QGroupBox = _import_widget("QGroupBox")
QLineEdit = _import_widget("QLineEdit")
QTableWidget = _import_widget("QTableWidget")
QTabWidget = _import_widget("QTabWidget")
QListWidget = _import_widget("QListWidget")
QComboBox = _import_widget("QComboBox")
QMenu = _import_widget("QMenu")


# ---------------------------------------------------------------------------
# Language state.
# ---------------------------------------------------------------------------
_LANGUAGE = "ar"


def get_language():
    """Return the current language code ("ar" or "en")."""
    return _LANGUAGE


def set_language(lang):
    """Set the current language. Only "ar"/"en" are accepted; others ignored."""
    global _LANGUAGE
    if lang in ("ar", "en"):
        _LANGUAGE = lang
    return _LANGUAGE


def toggle_language():
    """Flip "ar" <-> "en" and return the new value."""
    global _LANGUAGE
    _LANGUAGE = "en" if _LANGUAGE == "ar" else "ar"
    return _LANGUAGE


# ---------------------------------------------------------------------------
# Translation dictionaries.
# ---------------------------------------------------------------------------
AR_TO_EN = {
    # G1.50: لوحة انزلاق BTC بنافذة متحرّكة (§1.5 ثنائية اللغة).
    "تتبّع انزلاق BTC (نافذة متحرّكة)": "BTC Slippage (Rolling Window)",
    "سعر BTC الحيّ": "BTC Live Price",
    "ذروة النافذة": "Window Peak",
    "انزلاق النافذة %": "Window Slippage %",
    "طور الحارس": "Guard Phase",
    "خامل": "Idle",
    "مُسلّح": "Armed",
    # G1.49 chunk_5: بارامترات سياسة تنفيذ الخروج الموحّدة (§1.5 ثنائية اللغة).
    "سياسة تنفيذ الخروج الموحّدة": "Unified Exit Policy",
    "نطاق العبور %": "Cross Band %",
    "خطوة الملاحقة %": "Chase Step %",
    "محاولات الملاحقة": "Chase Attempts",
    "مهلة الملاحقة ث": "Chase Interval s",
    "إزاحة ستوب الحارس %": "Guard Stop Offset %",
    # G1.46: بطاقة نتيجة الصفقة أسفل الوسيلة المنفِّذة (§1.5 ثنائية اللغة).
    "نتيجة الصفقة": "Deal Result",
    "الدخول": "Entry",
    "الخروج": "Exit",
    "الجانب": "Side",
    "الربح/الخسارة": "Profit/Loss",
    "متصل": "Connected",
    "غير متصل": "Disconnected",
    "جارٍ الاتصال": "Connecting",
    "خطأ اتصال": "Connection Error",
    "قطع الاتصال": "Disconnect",
    "اتصال": "Connect",
    "جارٍ الاتصال...": "Connecting...",
    "تم الاتصال بنجاح.": "Connected successfully.",
    "فشل الاتصال.": "Connection failed.",
    "لم يتم تفعيل الاتصال بعد.": "Connection not activated yet.",
    "الاتصال بالحساب": "Account Connection",
    "مفتاح API": "API Key",
    "المفتاح السري": "Secret Key",
    "لم يتم اختيار ملف": "No file selected",
    "فتح ملف": "Open File",
    "اختر ملف المفاتيح": "Choose keys file",
    "لوحة التحكم": "Dashboard",
    "الأوامر المفتوحة": "Open Orders",
    "تفاصيل وتعديل": "Details & Edit",
    "تفاصيل الأمر والتعديل اليدوي": "Order Details & Manual Edit",
    "المراقبة الديناميكية": "Dynamic Monitoring",
    "التنفيذ الآمن": "Safe Execution",
    "الصفقات المنتهية": "Completed Trades",
    "وضع العرض": "Demo Mode",
    "الاتصال": "Connection",
    "إدارة أوامر OCO": "OCO Orders Management",
    "الـ OCO المختار": "Selected OCO",
    "الرمز": "Symbol",
    "السعر الحالي": "Current Price",
    "جني الأرباح الحالي": "Current TP",
    "مُشغِّل وقف الخسارة الحالي": "Current SL Trigger",
    "السعر المرجعي": "Reference Price",
    "المُشغِّل التالي": "Next Trigger",
    "حالة المراقبة": "Monitoring State",
    "آخر إعادة تموضع": "Last Reposition",
    "البيئة": "Environment",
    "أوامر OCO المفتوحة على Binance": "Open OCO Orders on Binance",
    "↻ تحديث الأوامر": "↻ Refresh Orders",
    "كل أوامر البيع": "All Sell Orders",
    "معرّف قائمة الأوامر": "Order List ID",
    "الحالة": "Status",
    "الكمية": "Qty",
    "سعر البيع / جني الأرباح": "Sell Price / TP",
    "مُشغِّل الإيقاف": "Stop Trigger",
    "سعر الحد بعد التفعيل": "Limit Price After Trigger",
    "المفتاح غير موجود": "Key not found",
    "تفاصيل الأمر المحدد": "Selected Order Details",
    "تعديل الأمر": "Edit Order",
    "تفعيل التعديل": "Enable Edit",
    "نسبة جني الأرباح %": "TP %",
    "نسبة وقف الخسارة %": "SL %",
    "جني الأرباح": "Take Profit",
    "حد الإيقاف": "Stop Limit",
    "معرّفات الأطراف": "Leg IDs",
    "تأكيد": "Confirm",
    "🔒 مقفولة": "🔒 Locked",
    "للعرض فقط": "Read-only",
    "السعر الحالي:": "Current Price:",
    "أعلى إيقاف متاح:": "Max Available Stop:",
    "أقصى إيقاف متاح": "Max Available Stop",
    "قواعد المراقبة": "Monitoring Rules",
    "تفعيل": "Enable",
    "بدء": "Start",
    "إيقاف مؤقت": "Pause",
    "إيقاف طارئ": "Kill Switch",
    # G1.47: زرّ الخروج اليدوي الفوري + تلميحه (§1.5 ثنائية اللغة).
    "تنفيذ الخروج الفوري": "Execute Immediate Exit",
    "خروج يدوي فوري بأفضل سعر لحظي — أولوية عُليا على الوسائل الأربع (Testnet)": "Immediate manual exit at best live price — top priority over the four means (Testnet)",
    "استئناف": "Resume",
    "مراقبة": "Monitoring",
    "تحويل": "Convert",
    "اللوحة الحيّة": "Live Panel",
    "وقف الخسارة الحالي": "Current SL",
    "آخر عملية والنتيجة": "Last Operation + Result",
    "نسبة ارتفاع مُشغِّل إعادة التموضع %": "Reposition Trigger Rise %",
    "نسبة بُعد جني الأرباح فوق الحالي %": "TP Distance Above Current %",
    "نسبة بُعد وقف الخسارة تحت الحالي %": "SL Distance Below Current %",
    "سعر التفعيل": "Trigger Price",
    "جني الأرباح التالي": "Next TP",
    "وقف الخسارة التالي": "Next SL",
    "حد وقف الخسارة": "SL Limit",
    "حجم الخطوة السعرية": "Tick Size",
    "سيُحوَّل إلى OCO": "Will convert to OCO",
    "وضع DEMO — محاكاة، لا كتابة حقيقية على Binance": "DEMO Mode — simulation, no real writes to Binance",
    "قواعد العرض (محاكاة)": "Demo Rules (simulation)",
    "بدء العرض": "Start Demo",
    "خطوة": "Step",
    "تشغيل تلقائي": "Auto Run",
    "إيقاف تلقائي": "Auto Stop",
    "الطور": "Phase",
    "آخر عملية محاكاة": "Last Simulated Operation",
    "أمر محدَّد": "Selected Order",
    "المراقبة نشطة": "Monitoring Active",
    "مُفعَّل": "Enabled",
    "إعادة تموضع": "Reposition",
    "نجاح": "Success",
    "أُلغي": "Cancelled",
    "فشل — تدخّل يدوي": "Failed — Manual Intervention",
    "مفتاح الحالات": "Status Key",
    "النافذة العارية": "Naked Window",
    "قائمة الصفقات المنتهية": "Completed Trades List",
    "الصفقة": "Trade",
    "مسح الصفقة المحددة": "Clear Selected Trade",
    "تفاصيل الصفقة": "Trade Details",
    "لا توجد صفقات منتهية بعد.": "No completed trades yet.",
    "غير متاح": "N/A",
    "التاريخ والوقت": "Date & Time",
    "السعر المرجعي / الدخول": "Reference / Entry Price",
    "سعر الإيقاف": "Stop Price",
    "سعر البيع": "Sell Price",
    "الربح ($)": "Profit ($)",
    "الربح (%)": "Profit (%)",
    # --- G1.28: UI-layer residual English keys (additive only) -------------
    # Sidebar — composite nav labels ("icon  nav_label"), copied verbatim.
    "▦  لوحة التحكم": "▦  Dashboard",
    "▤  الأوامر المفتوحة": "▤  Open Orders",
    "✎  تفاصيل وتعديل": "✎  Details & Edit",
    "◎  المراقبة الديناميكية": "◎  Dynamic Monitoring",
    "⚡  التنفيذ الآمن": "⚡  Safe Execution",
    "▶  وضع العرض": "▶  Demo Mode",
    "⇄  الاتصال": "⇄  Connection",
    "✔  الصفقات المنتهية": "✔  Completed Trades",
    "✉  تنبيهات Telegram": "✉  Telegram Alerts",
    # Connection screen — multi-line hint (concatenated literals).
    "أدخل مفتاح API والمفتاح السري يدويًا، أو اختر ملف txt يحوي المفاتيح. اترك الحقول فارغة لاستخدام المسار الافتراضي كخيار احتياطي.": "Enter the API key and secret key manually, or choose a txt file containing the keys. Leave the fields empty to use the default path as a fallback.",
    # Dashboard / monitoring / selected-OCO — no-selection note.
    "لم يُختَر أمر": "No order selected",
    # Open Orders — selection safety note.
    "الاختيار يعمل فقط على الـ orderListId المحدد — لا يُمَس أي أمر آخر حتى لو لنفس العملة.": "Selection applies only to the chosen orderListId — no other order is touched, even for the same symbol.",
    # Selected & Edit — confirm text, old/new heading, and dynamic statuses.
    "تفعيل إعادة التموضع: سيُلغى الأمر الحالي ثم يُنشأ البديل. متابعة؟": "Activate reposition: the current order will be cancelled and the replacement created. Continue?",
    "القيمة القديمة ↔ القيمة الجديدة": "Old Value ↔ New Value",
    "سيُحوَّل إلى OCO — يلزم التحويل أولًا": "Will convert to OCO — conversion required first",
    "✓ تم التفعيل — الأمر الجديد:": "✓ Activated — new order:",
    "✓ تم التفعيل بنجاح": "✓ Activated successfully",
    "✓ الترتيب الصارم سليم: حد الإيقاف < المُشغِّل < السعر المرجعي < جني الأرباح": "✓ Strict order is valid: Stop Limit < Trigger < Reference Price < Take Profit",
    "✗ مخالفة الترتيب الصارم: يلزم حد الإيقاف < المُشغِّل < السعر المرجعي < جني الأرباح": "✗ Strict order violated: requires Stop Limit < Trigger < Reference Price < Take Profit",
    # Dynamic Monitoring — _set_last_operation phrases.
    "تم التحويل إلى OCO — بدء المراقبة": "Converted to OCO — starting monitoring",
    "تعذّر البدء — لا سعر حيّ بعد": "Cannot start — no live price yet",
    "بدأت المراقبة": "Monitoring started",
    # Safe Execution — 7 step titles.
    "① إعادة التحقق من الأمر المحدد": "① Re-verify the selected order",
    "② جلب أحدث سعر صالح + الكمية المتبقية": "② Fetch latest valid price + remaining quantity",
    "③ إعادة حساب المستويات (tick/step + ترتيب صارم)": "③ Recompute levels (tick/step + strict order)",
    "④ 🛡️ بوابة تحقّق مسبق قبل الإلغاء (Pre-Cancel Validation Gate)": "④ 🛡️ Pre-Cancel Validation Gate",
    "⑤ إلغاء الأمر المحدد فقط": "⑤ Cancel the selected order only",
    "⑥ إنشاء الأمر البديل": "⑥ Create the replacement order",
    "⑦ تأكيد orderListId الجديد": "⑦ Confirm the new orderListId",
    # Safe Execution — failure headline + dynamic final statuses.
    "FAILED_NEEDS_ATTENTION — يتطلب تدخّلًا يدويًا. لا توجد إعادة محاولة تلقائية.": "FAILED_NEEDS_ATTENTION — requires manual intervention. There is no automatic retry.",
    "✓ نجاح — الأمر الجديد:": "✓ Success — new order:",
    "✓ نجاح": "✓ Success",
    "⊘ أُلغي الإجراء — الأمر الأصلي سليم.": "⊘ Action aborted — the original order is intact.",
    # Demo Mode — headings + dynamic phrases.
    "وضع العرض (Demo)": "Demo Mode (Demo)",
    "اللوحة الحيّة (محاكاة)": "Live Panel (Simulation)",
    "محاكاة نشطة (لا كتابة حقيقية)": "Simulation active (no real writes)",
    "تجاوز مستوى التفعيل": "Trigger level crossed",
    "مرجع جديد (بلا أمر حقيقي)": "New reference (no real order)",
    "محاكاة تفعيل": "Simulated trigger",
    "محاكاة إعادة تموضع": "Simulated reposition",
    # Completed Trades — section/title + end-reason labels.
    "تفاصيل سلسلة التموضع": "Reposition Chain Details",
    "تفاصيل التموضع": "Reposition Details",
    "اكتملت (جني ربح)": "Completed (Take Profit)",
    "اكتملت (وقف خسارة)": "Completed (Stop Loss)",
    "موقوفة (يدوي)": "Stopped (Manual)",
    "موقوفة (قطع اتصال)": "Stopped (Disconnected)",
    "موقوفة (أخرى)": "Stopped (Other)",
    # Alerts / Telegram — static widget text.
    "تنبيهات Telegram": "Telegram Alerts",
    "حساب البوت": "Bot Account",
    "توكِن البوت من @BotFather": "Bot token from @BotFather",
    "إضافة البوت": "Add Bot",
    "حذف البوت": "Remove Bot",
    "المستلمون": "Recipients",
    "chat_id (رقم؛ قد يبدأ بـ -)": "chat_id (number; may start with -)",
    "إضافة مستلم": "Add Recipient",
    "حذف المحدد": "Remove Selected",
    "تفعيل التنبيهات": "Enable Alerts",
    "إرسال رسالة اختبارية": "Send Test Message",
    "(بوت مُضاف)": "(bot added)",
    "إرشادات الإعداد:\n1) أنشئ بوتًا عبر @BotFather في Telegram واحصل على التوكِن (token)؛ أرسل /newbot واتبع الخطوات، ثم انسخ التوكِن.\n2) لكي يحصل المستلم على chat_id الخاص به: يبدأ محادثة مع البوت بالضغط Start، ثم يستخدم مساعدًا مثل @userinfobot أو عبر getUpdates للحصول على chat_id.\n3) خطوات الإضافة هنا: الصق التوكِن واضغط «إضافة البوت»، ثم أضِف chat_id لكل مستلم عبر «إضافة مستلم»، فعِّل التنبيهات، وأرسل رسالة اختبارية للتأكّد.": "Setup instructions:\n1) Create a bot via @BotFather in Telegram and obtain the token; send /newbot, follow the steps, then copy the token.\n2) For a recipient to get their chat_id: they start a chat with the bot by pressing Start, then use a helper such as @userinfobot or getUpdates to obtain the chat_id.\n3) Steps to add here: paste the token and press «Add Bot», then add a chat_id for each recipient via «Add Recipient», enable alerts, and send a test message to confirm.",
    # Alerts / Telegram — dynamic status + reason strings.
    "البوت: %s": "Bot: %s",
    "لا يوجد بوت مُضاف بعد.": "No bot added yet.",
    "جارٍ التحقّق من التوكِن عبر getMe…": "Verifying the token via getMe…",
    "فشل التحقّق من البوت.": "Bot verification failed.",
    "تعذّر الإرسال (لا منفّذ خلفي).": "Cannot send (no backend executor).",
    "أضِف البوت أولًا.": "Add the bot first.",
    "أضِف مستلمًا واحدًا على الأقل.": "Add at least one recipient.",
    "جارٍ إرسال رسالة اختبارية…": "Sending a test message…",
    "فشل الإرسال الاختباري: %s": "Test send failed: %s",
    "رُفض التوكِن": "Token rejected",
    "تعذّر الاتصال بـ Telegram": "Could not connect to Telegram",
    "فشل الإرسال": "Send failed",
    "الصق توكِن البوت أولًا": "Paste the bot token first",
    "تعذّر التحقّق (لا منفّذ خلفي)": "Cannot verify (no backend executor)",
    "تعذّر الحفظ": "Could not save",
    "صيغة chat_id غير صحيحة": "Invalid chat_id format",
    "تم الإرسال بنجاح إلى %s مستلم.": "Sent successfully to %s recipient(s).",
    "معرّف الأمر الجديد": "New Order ID",
    "النوع": "Type",
    "سعر الليمت": "Limit Price",
    "سعر الوقف": "Stop Price",
    "سبب التفعيل": "Trigger Reason",
    "وقت التفعيل": "Trigger Time",
    "قوس الخروج بالسعر": "Price Exit Bracket",
    "تفعيل قوس الخروج": "Enable Exit Bracket",
    "حدّ علوي": "Upper Bound",
    "سعر علوي": "Upper Price",
    "حدّ سفلي": "Lower Bound",
    "سعر سفلي": "Lower Price",
    "انزلاق علوي %": "Upper Slippage %",
    "زناد سفلي %": "Lower Trigger %",
    "أرضية %": "Floor %",
    "الأمر النشط بعد الملامسة": "Active Order After Touch",
    "شبكة أمان المركز": "Position Safety Net",
    "وضع الحارس": "Guardian Mode",
    "⚠ الحدّ السفلي يجب أن يكون أقلّ من العلوي.": "⚠ The lower bound must be less than the upper bound.",
    "⚠ السعر الحالي خارج الحدّين.": "⚠ The current price is outside the two bounds.",
    "تعذّر التحويل — لا مُحوِّل متاح": "Conversion unavailable — no converter available",
    "تعذّر التحويل — لا أمر مصدر": "Conversion unavailable — no source order",
    "فشل التحويل": "Conversion failed",
    "السفلي": "Lower",
    "العلوي": "Upper",
    "القوس": "Bracket",
    "الحد %s %s": "Bound %s %s",
    "ملامسة الحد %s": "Bound touch %s",
    "ملامسة القوس": "Bracket touch",
    "تم التنقل من التموضع إلى أمر جديد OCO %s بناءً على %s - السعر الحالي %s": "Moved from repositioning to a new OCO order %s based on %s - current price %s",
    "سيُحوَّل إلى OCO تلقائيًا عند بدء المراقبة": "Will convert to OCO automatically when monitoring starts",
    "الحارس: مطفأ": "Guardian: Off",
    "الحارس: نائم (يراقب)": "Guardian: Sleeping (watching)",
    "الحارس: رصد عُري…": "Guardian: Naked detected…",
    "الحارس: تدخّل ✓": "Guardian: Intervened ✓",
    "حارس هبوط BTC": "BTC Drop Guard",
    "وضع حارس BTC": "BTC Guard Mode",
    "حارس BTC: —": "BTC Guard: —",
    "حارس BTC: مطفأ": "BTC Guard: Off",
    "حارس BTC: نائم (يراقب)": "BTC Guard: Sleeping (watching)",
    "حارس BTC: رصد هبوط…": "BTC Guard: Drop detected…",
    "حارس BTC: تدخّل ✓": "BTC Guard: Intervened ✓",
    "الحارس: —": "Guardian: —",
    "مطفأ": "Off",
    "تدخّل": "Intervene",
    "الوضع: ": "Mode: ",
    "حارس هبوط BTC على ": "BTC Drop Guard on ",
    "نُفّذ خروج دفاعي (تضييق) عبر مسار الخروج المُختبَر.": "A defensive exit (tighten) was executed via the tested exit path.",
    "وضع مراقبة (Observe/dry_run): اقتراح تضييق دون تنفيذ.": "Observe mode (dry_run): tighten suggested without execution.",
    "تعذّر تنفيذ التضييق؛ لا تغيير.": "Could not execute the tighten; no change.",
    "سعر حيّ": "Live Price",
    "سعر سابق": "Previous Price",
    "نسبة التغيّر": "Change %",
    "نسبة التتبّع": "Tracking %",
    "تتبّع العملة المراقَبة": "Monitored Coin Tracking",
    "آخر إجراء: ": "Last action: ",
    "كمية ": "Qty ",
    "سعر ": "Price ",
    "ملفات نصية (*.txt);;كل الملفات (*)": "Text files (*.txt);;All files (*)",
    "فشل الاتصال: %s": "Connection failed: %s",
    "حذف": "Delete",
    "⚠️ نافذة عارية: المركز بلا حماية أثناء الإلغاء ثم الإنشاء": "⚠️ Naked window: the position is unprotected during cancel-then-create",
    # G1.54: لوحة الربحية الاحترافية في شاشة 08_completed_trades (§1.5 ثنائية اللغة).
    "ملخّص الربحية": "Profitability Summary",
    "ترتيب الأوضاع (حسب التوقّع)": "Modes Ranking (by Expectancy)",
    "منحنى الربح/الخسارة التراكمي": "Cumulative P&L Curve",
    "توزيع الصفقات": "Trades Distribution",
    "كل الأوضاع": "All Modes",
    "لا بيانات ربحية بعد.": "No profitability data yet.",
    "معدّل الربح": "Win Rate",
    "متوسط العائد": "Avg Return",
    "الصافي": "Net",
    "التوقّع/صفقة": "Expectancy/Trade",
    "متوسط الانزلاق": "Avg Slippage",
    "عدد الصفقات": "Trades",
    "رابحة": "Wins",
    "خاسرة": "Losses",
    # تسميات أوضاع الخروج (exit_source) المعروضة في بطاقات اللوحة.
    "المراقبة الديناميكية": "Dynamic Monitoring",
    "قوس السعر": "Price Bracket",
    "تتبّع BTC": "BTC Follow",
    "شبكة أمان المركز": "Position Safety Net",
    "خروج يدوي": "Manual Exit",
}

EN_TO_AR = {v: k for k, v in AR_TO_EN.items()}


# ---------------------------------------------------------------------------
# Translation helpers.
# ---------------------------------------------------------------------------
def translate(text):
    """Translate ``text`` for the current language.

    ``text`` may be the Arabic source literal or an already-translated English
    string; it is first normalised back to its canonical Arabic form.
    """
    canonical_ar = EN_TO_AR.get(text, text)
    if get_language() == "en":
        return AR_TO_EN.get(canonical_ar, canonical_ar)
    return canonical_ar


def translate_for_current(text):
    """Translate the Arabic source literal for the current language."""
    return translate(text)


def toggle_label():
    """Return the label for the language-toggle control."""
    return "EN" if get_language() == "ar" else "ع"


# ---------------------------------------------------------------------------
# Layout direction.
# ---------------------------------------------------------------------------
def _layout_direction():
    """Return the Qt layout-direction value for the current language."""
    right_to_left = get_language() == "ar"
    if Qt is None:
        # Fallback integers matching Qt's enum (RTL=1, LTR=0).
        return 1 if right_to_left else 0
    # Prefer the Qt6-style scoped enum, fall back to the flat attribute.
    try:
        return Qt.LayoutDirection.RightToLeft if right_to_left else Qt.LayoutDirection.LeftToRight
    except AttributeError:
        return Qt.RightToLeft if right_to_left else Qt.LeftToRight


def apply_direction(app, window):
    """Apply the current language's layout direction to app and window."""
    direction = _layout_direction()
    for obj in (app, window):
        if obj is not None and hasattr(obj, "setLayoutDirection"):
            try:
                obj.setLayoutDirection(direction)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Widget-tree retranslation.
# ---------------------------------------------------------------------------
def retranslate_widget_tree(root):
    """Walk the widget tree under ``root`` and retranslate visible text."""
    if root is None:
        return

    if QWidget is not None and hasattr(root, "findChildren"):
        try:
            widgets = [root] + list(root.findChildren(QWidget))
        except Exception:
            widgets = [root]
    else:
        widgets = [root]

    for w in widgets:
        try:
            if QLineEdit is not None and isinstance(w, QLineEdit):
                if hasattr(w, "placeholderText") and hasattr(w, "setPlaceholderText"):
                    w.setPlaceholderText(translate(w.placeholderText()))
                # Do NOT touch the editable text content.
            elif QGroupBox is not None and isinstance(w, QGroupBox):
                w.setTitle(translate(w.title()))
            elif (
                (QLabel is not None and isinstance(w, QLabel))
                or (QPushButton is not None and isinstance(w, QPushButton))
                or (QCheckBox is not None and isinstance(w, QCheckBox))
            ):
                w.setText(translate(w.text()))

            if QTabWidget is not None and isinstance(w, QTabWidget):
                for i in range(w.count()):
                    w.setTabText(i, translate(w.tabText(i)))

            if QTableWidget is not None and isinstance(w, QTableWidget):
                for c in range(w.columnCount()):
                    item = w.horizontalHeaderItem(c)
                    if item is not None:
                        item.setText(translate(item.text()))
                for r in range(w.rowCount()):
                    vitem = w.verticalHeaderItem(r)
                    if vitem is not None:
                        vitem.setText(translate(vitem.text()))
                # Data cells w.item(r, c) are data (symbols/ids/numbers), not chrome -> never translated.

            if QListWidget is not None and isinstance(w, QListWidget):
                for _i in range(w.count()):
                    _it = w.item(_i)
                    if _it is not None:
                        _it.setText(translate(_it.text()))

            if QComboBox is not None and isinstance(w, QComboBox):
                # G1.44 / chunk_4: مُبدِّلا وضع الحارسين (شبكة الأمان + هبوط BTC)
                # يحملان نفس أوضاع مطفأ/مراقبة/تدخّل؛ عناصرها تُترجَم هنا كبقية
                # عناصر QComboBox بلا استثناء خاصّ (نفس retranslate القائم).
                for _i in range(w.count()):
                    w.setItemText(_i, translate(w.itemText(_i)))

            if QMenu is not None and isinstance(w, QMenu):
                w.setTitle(translate(w.title()))

            _acts = getattr(w, "actions", None)
            if callable(_acts):
                for _act in (_acts() or []):
                    if _act is not None and not _act.isSeparator():
                        _act.setText(translate(_act.text()))

            _retr = getattr(w, "retranslate_i18n", None)
            if callable(_retr):
                _retr()
        except Exception:
            # One misbehaving widget must never break the whole pass.
            continue

    if hasattr(root, "windowTitle") and hasattr(root, "setWindowTitle"):
        try:
            root.setWindowTitle(translate(root.windowTitle()))
        except Exception:
            pass
