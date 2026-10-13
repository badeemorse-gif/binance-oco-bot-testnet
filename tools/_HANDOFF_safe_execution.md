# HANDOFF — بناء ocobot/ui/safe_execution.py (شاشة "التنفيذ الآمن")

آخر تحديث: أثناء تنفيذ مهمة إنشاء ملف واحد فقط.

## الهدف (لا يتغير)
إنشاء ملف واحد **فقط** على القرص: `ocobot/ui/safe_execution.py` داخل المشروع `D:\oco`.
- يعرّف `class SafeExecutionScreen(QWidget)`.
- **ممنوع تعديل أي ملف آخر. ممنوع تشغيل الاختبارات.**
- **NETWORK GUARD:** يجب ألا يحتوي الملف على أيٍّ من هذه السلاسل حرفيًا:
  `urllib` , `socket` , `SignedRestClient` , `.signed_request(` , `.public_request(`
  (لا شبكة إطلاقًا — الشاشة تعرض فقط بيانات تُمرَّر إليها).
- المُنشئ متسامح: `def __init__(self, parent=None, **kwargs)` كي يبنيها ContentRouter بلا خدمات.

## ما أنجزته حتى الآن (تم قراءته والتأكد منه)
تمت قراءة الملفات المرجعية التالية بالكامل:

### 1) ocobot/ui/_qt.py — نمط استيراد Qt
- يُستورد كل شيء من `._qt` (shim يفضّل PySide6 ثم PyQt6).
- المتاح ويهمّنا: `Qt, QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
  QPushButton, QSizePolicy, QScrollArea`.
- استخدم `Qt.LayoutDirection.RightToLeft` و `QSizePolicy.Policy.Expanding` (نمط enum الكامل، PySide6/PyQt6 معًا).

### 2) ocobot/ui/theme.py — PALETTE (D15) — المفاتيح المتاحة بالضبط:
`BG, SIDEBAR, CARD, CARD_ALT, BORDER, TEXT, TEXT_SOFT, MUTED, BLUE, TEAL, GREEN, RED, AMBER`
- استيراد: `from .theme import PALETTE`

### 3) ocobot/ui/open_orders.py — قالب الشاشة (نفس الأسلوب المطلوب)
- `from ._qt import (Qt, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, ...)`
- `from .theme import PALETTE`
- `class OpenOrdersScreen(QWidget):` ثم `def __init__(self, parent=None, runner=None, ...)`:
  - `super().__init__(parent)`
  - `self.screen_key = "02_open_orders"`
  - `self.setObjectName("Screen_02_open_orders")`
  - `self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)`
  - `root = QVBoxLayout(self); root.setContentsMargins(26,22,26,22); root.setSpacing(16)`
  - العنوان: `QLabel(...)`، `setObjectName("ScreenHeading")`,
    `setStyleSheet("color:%s;font-size:20px;font-weight:700;" % PALETTE["TEXT"])`
  - بطاقات = `QFrame` بستايل `background:%s;border:1px solid %s;border-radius:12px;` من PALETTE.

### 4) ocobot/ui/selected_oco.py — النصوص والحالات (مرجع أساسي)
- `NAKED_WINDOW_TEXT = "⚠️ نافذة عارية: المركز بلا حماية أثناء الإلغاء ثم الإنشاء"`  ← **يمكن استيراده**:
  `from .selected_oco import NAKED_WINDOW_TEXT` (نظيف). إن تعذّر، انسخ السلسلة حرفيًا.
- ثوابت الحالة (سلاسل):
  `_STATE_SUCCESS = "SUCCESS"` , `_STATE_ABORTED = "ABORTED"` , `_STATE_FAILED = "FAILED_NEEDS_ATTENTION"`
- `_on_activate_result(self, result)` يستقبل كائن نتيجة تنفيذ ويقرأ منه:
  - `state = getattr(result, "state", None)` ثم
    `state_name = getattr(state,"value",None) or getattr(state,"name",None) or state`
  - `new_id = getattr(result, "new_order_list_id", None)`  (يظهر في رسالة النجاح)
  - عند غير النجاح: `humanize(result)` من `ocobot.core.failure_matrix`.
- شارة "النافذة العارية" بلون AMBER: تُظهر بين التأكيد والحالة النهائية، وتُخفى في الحالة النهائية.

### 5) ocobot/core/failure_matrix.py — دلالات الحالة النهائية
- `FAILED_NEEDS_ATTENTION = "FAILED_NEEDS_ATTENTION"` (تطابق `ExecutionState.FAILED_NEEDS_ATTENTION` قيمةً).
- `_is_failed_needs_attention(err)`: يعتبرها فشلًا إذا:
  - كانت السلسلة نفسها، أو
  - `getattr(err,"state",None)` قيمته (أو `.value`) == `FAILED_NEEDS_ATTENTION`, أو
  - `getattr(err,"value",None) == FAILED_NEEDS_ATTENTION`.
- `MSG_FAILED_NEEDS_ATTENTION` يذكر: "تمّ إلغاء الأمر المحدّد، لكن إنشاء البديل فشل — لا توجد إعادة محاولة تلقائية (No Blind Retry). تدخّل يدوي مطلوب. (D9)"
- **إذًا الدلالة المؤكدة:** FAILED_NEEDS_ATTENTION == Cancel ✓ + Create ✗.

### حقول ExecutionResult المستنتجة (من selected_oco + failure_matrix):
- `state` : Enum أو سلسلة، قيمته أحد: `SUCCESS` / `ABORTED` / `FAILED_NEEDS_ATTENTION`
  (تُقرأ عبر `getattr(state,"value",None) or getattr(state,"name",None) or state`).
- `new_order_list_id` : معرّف قائمة الأوامر الجديدة (موجود عند النجاح؛ None خلاف ذلك).
## ✅ ExecutionResult مؤكّد — الموقع: ocobot/domain/reposition.py
`from ocobot.domain.reposition import ExecutionResult, ExecutionState, ExecutionStep`
(البحث النصّي searchInFiles/ripgrep معطّل بخطأ `spawn ripgrep ENOENT` — استُخدم readFile مباشرة.)

### enum ExecutionState (str, Enum) — القيم بالضبط:
`IDLE, COMPUTING, GATE_PASSED, REPOSITIONING, SUCCESS, ABORTED, FAILED_NEEDS_ATTENTION`

### @dataclass ExecutionStep — الحقول:
`key: str` , `label: str` , `status: str  # pending/done/failed/skipped/naked` , `detail: str = ""` , `naked_window: bool = False`

### @dataclass ExecutionResult — الحقول بالضبط:
- `state: ExecutionState`
- `steps: List[ExecutionStep]`
- `draft: Optional[RepositionDraft] = None`
- `cancelled_order_list_id: Optional[int] = None`   ← orderListId المُلغى (Cancel ✓)
- `new_order_list_id: Optional[int] = None`          ← orderListId الجديد (Create ✓)، None عند فشل الإنشاء
- `reason: str = ""`
- `messages: List[str] = field(default_factory=list)`
- `gate: Optional[GateResult] = None`

### مفاتيح الخطوات السبع من execute() (نفس ترتيب RTL المطلوب):
`verify` ① , `price` ② , `recalc` ③ , `gate` ④ , `cancel` ⑤ (naked_window=True) , `create` ⑥ (naked_window=True) , `confirm` ⑦
- قيم status الفعلية المستخدمة: `pending`, `done`, `failed`, `skipped`.
- خطوتا cancel/create تحملان `naked_window=True`.

### دلالة cancel-succeeded-but-create-failed مؤكّدة:
`state == ExecutionState.FAILED_NEEDS_ATTENTION`  و  `cancelled_order_list_id` موجود  و  `new_order_list_id is None`.
→ اعرض orderListId (المُلغى) + "Cancel ✓ · Create ✗".

### خريطة show_result المقترحة (اقرأ الخطوات مباشرة من result.steps إن وُجدت):
- الأفضل: `for s in result.steps: by_key[s.key].set_status(s.status)` (status يأتي جاهزًا من المحرّك).
  اربط status المحرّك → علامة الشاشة: done→done, failed→failed, skipped→(aborted إن كانت الحالة ABORTED وإلا wait), pending→wait/current.
- الحالة النهائية من `result.state`: SUCCESS / ABORTED / FAILED_NEEDS_ATTENTION.
- إن لم يكن للـ result سمة steps (تسامحًا): اشتق الحالات من state + new_order_list_id + cancelled_order_list_id.
- تسامح: استخدم getattr(result, "state", None) ثم `getattr(state,"value",None) or getattr(state,"name",None) or state` (نفس نمط selected_oco._on_activate_result) لأن state قد يكون Enum أو سلسلة.

## ✅ اكتملت المهمة
- تم إنشاء `ocobot/ui/safe_execution.py` على القرص وأُعيدت قراءته.
- يعرّف `class SafeExecutionScreen(QWidget)` (سطر 165) + `_StepRow(QFrame)`.
- `__init__(self, parent=None, **kwargs)` (سطر 172) — بلا خدمات/شبكة.
- `reset(self)` (سطر 301) و `show_result(self, result, *, selected=None)` (سطر 310).
- تحقّق NETWORK GUARD: كل السلاسل المحظورة = 0 ظهور
  (urllib=0, socket=0, SignedRestClient=0, .signed_request(=0, .public_request(=0).
- لم يُعدَّل أي ملف آخر عدا هذا الملف الجديد وملف الهاندأوف هذا. لم تُشغَّل أي اختبارات.

## ثم اكتب الملف (createFile: ocobot/ui/safe_execution.py) — المتطلبات:
- عنوان عمودي "التنفيذ الآمن" + **7 خطوات ذرّية بترتيب RTL صارم** (تصميم §3.6 F):
  1. ① إعادة التحقق من الأمر المحدد
  2. ② جلب أحدث سعر صالح + الكمية المتبقية
  3. ③ إعادة حساب المستويات (tick/step + ترتيب صارم)
  4. ④ 🛡️ بوابة تحقّق مسبق قبل الإلغاء (Pre-Cancel Validation Gate)
  5. ⑤ إلغاء الأمر المحدد فقط
  6. ⑥ إنشاء الأمر البديل
  7. ⑦ تأكيد orderListId الجديد
  - كل خطوة صف فيه علامة حالة: done / current / wait / failed / aborted.
- مفتاح الحالات (مفتاح الحالات) يسرد: Connected / Selected / Monitoring Active / Triggered /
  Repositioning / Success / Aborted / FAILED_NEEDS_ATTENTION.
- شارة "النافذة العارية" (NAKED_WINDOW_TEXT) مؤكَّدة بصريًا عندما تكون ⑤–⑥ current/pending.
- بطاقة FAILED_NEEDS_ATTENTION (مخفية افتراضيًا) تنص بالنص الحرفي:
  "FAILED_NEEDS_ATTENTION — يتطلب تدخّلًا يدويًا. لا توجد إعادة محاولة تلقائية."
  وتُظهر orderListId + تفصيل بنمط "Cancel ✓ · Create ✗" عند cancel-succeeded-but-create-failed.
- `def show_result(self, result, *, selected=None) -> None`: تشتق حالات الخطوات والحالة النهائية
  من حقول ExecutionResult الحقيقية (اربط new_order_list_id بشكل صحيح).
- `def reset(self) -> None` (أو حالة افتراضية في __init__): كل الخطوات "wait" وإخفاء بطاقة الفشل.
- `def __init__(self, parent=None, **kwargs)` — بلا أي متطلب شبكي.
- نمط استيراد Qt عبر `._qt` (مثل open_orders.py).

## بعد الكتابة
- أعد قراءة `ocobot/ui/safe_execution.py` وتأكد من وجوده وتعريفه `class SafeExecutionScreen`.
- قرّر أن أيًّا من السلاسل المحظورة غير موجودة في الملف.
- المهمة مكتملة فقط عندما يكون الملف على القرص فيه `class SafeExecutionScreen`.
