"""State Store (T5 / M4a) — persistence foundation with atomic write + safe read.

============================================================================
قرار صيغة التخزين (يحسم open_question "صيغة التخزين — تُحسم داخل T5"):
----------------------------------------------------------------------------
- **الافتراضي المعتمد = JSON ذرّي للـ checkpoint + JSONL append-only للـ audit**
  (سجل التدقيق موجود بالفعل في ``ocobot.core.audit_log`` — لا يُعاد بناؤه هنا).
- **لماذا JSON للـ checkpoint؟** مكتبة قياسية فقط (بلا اعتماد خارجي — يطابق قيد
  المشروع stdlib-only)، مقروء بشريًا للتدقيق/التصحيح، والكاتب واحد (single-writer)
  بتكرار كتابة منخفض (عند كل انتقال حالة فقط). الكتابة الذرّية عبر
  temp→fsync→``os.replace`` تُعطي "الكل أو لا شيء" فلا يُترَك ملف نصف-مكتوب أبدًا.
- **البديل المدروس = SQLite (وسبب تأجيله):** SQLite جزء من المكتبة القياسية أيضًا،
  لكنه يُدخِل تعقيدًا وطبقة قفل (locking/WAL/transactions) لا يحتاجها حِمل عمل
  ذو كاتب واحد وتكرار منخفض. لا نكسب ذرّية إضافية تفوق temp→rename لملف صغير،
  ونخسر قابلية القراءة البشرية للـ checkpoint. لذلك **أُجِّل** ويمكن إعادة النظر
  فيه لاحقًا فقط عند ظهور كتّاب متزامنين (concurrent writers) أو سجلّ تاريخي عالي
  التردد. هذا القرار متّسق مع D8 (لا أسرار في أي ملف)، D10 (idempotency/تحقّق قبل
  الاستئناف الأعمى — يبنى فوقه T8)، وD14 (السعر الحيّ حقيقي — نُخزّن آخر سعر فقط
  كـ checkpoint، لا نختلق سعرًا).

============================================================================
النطاق (T5 فقط):
----------------------------------------------------------------------------
هذا الموديول يوفّر طبقة التخزين وحدها. لا يربط نفسه بمحرّك المراقبة أو الـ CLI
(ذلك مهمة T8 — Runtime Recovery). لا يعدّل ``monitoring.py`` / ``models.py`` /
``audit_log.py`` / ``failure_matrix.py``.

السكيمة (schema) الموثّقة تغطّي:
  1. ``MonitoringCheckpoint``: كل حقول ``MonitoringState`` اللازمة لاستئناف المراقبة
     بعد تعطّل (state enum، reference/trigger/tp/sl، latched، in_flight،
     target_order_list_id، tolerance/guard، last_price، last_reposition، cursor،
     symbol، enabled).
  2. ``SelectedOcoContext``: هوية ``SelectedOCO`` (orderListId، symbol، الكمية
     المقفولة، الأسعار الثلاثة، legIds، status، filters) لإعادة تأسيس السياق.
  3. ``LogLocations``: مسارات ملف checkpoint وملف الـ audit JSONL.

الأمان (D8): لا تُكتب أي مفاتيح/أسرار/تواقيع/توكِنات إطلاقًا. حتى لو ظهر حقل كهذا
عبر خطأ برمجي مستقبلي، يُنقّى (redact) قبل الكتابة عبر ``_strip_secrets`` —
باتّباع نفس نهج ``ocobot.core.keys`` / ``ocobot.core.redaction``.

الدقة المالية: كل الأسعار/الكميات ``Decimal``؛ تُسلسَل كنصوص (str) لا floats
(لتفادي فقد الدقة على المال)، وتُستعاد ``Decimal`` عند القراءة.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# نسخة سكيمة الملف — تُزاد عند أي تغيير غير متوافق في البنية المخزّنة.
SCHEMA_VERSION = 1

# أسماء الحقول التي يُمنع كتابتها إطلاقًا (D8) — تطابق نهج الإخفاء القائم.
# أي مفتاح يحتوي إحدى هذه العلامات (case-insensitive) يُزال قبل الكتابة.
_SECRET_MARKERS = (
    "secret",
    "apikey",
    "api_key",
    "signature",
    "token",
    "password",
    "passphrase",
    "private",
    "credential",
)

_REDACTED = "***"


class StateStoreError(Exception):
    """خطأ استرجاع محدَّد وحيد لهذا الموديول (recoverable).

    يُرفَع فقط عند فشل قراءة/تفسير غير قابل للتعافي عندما يطلب المتصل صراحةً
    رفع استثناء (``strict=True``). في الوضع الافتراضي (``strict=False``) تُعيد
    القراءة الآمنة ``None`` بدل رفع أي استثناء خام على المتصل.
    """


# ---------------------------------------------------------------------------
# مساعِدات Decimal-safe (Decimal <-> str) — لا floats للمال إطلاقًا.
# ---------------------------------------------------------------------------
def _dec_to_str(value: Optional[Decimal]) -> Optional[str]:
    """يُسلسِل Decimal كنصّ للحفاظ على الدقة (None تبقى None)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # str(Decimal) لا يفقد الدقة ولا يُقرّب — عكس float.
        return str(value)
    # مدخل غير متوقّع: طبّعه عبر Decimal(str(x)) بدل float.
    return str(Decimal(str(value)))


def _str_to_dec(value: Any) -> Optional[Decimal]:
    """يستعيد Decimal من نصّ مُسلسَل (None/'' تبقى None)."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _is_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _strip_secrets(obj: Any) -> Any:
    """يُنقّي أي مفتاح يشبه سرًّا/توقيعًا/توكِنًا (D8) بشكل تعاودي (recursive).

    لا يُفترَض أن تحمل السكيمة أي أسرار أصلًا؛ هذه بوابة أمان دفاعية تضمن أنه
    حتى لو سُرِّب حقل سرّي إلى الحمولة عبر خطأ مستقبلي، لن يُكتَب خامًا إلى القرص.
    """
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, val in obj.items():
            if _is_secret_key(key):
                cleaned[key] = _REDACTED
            else:
                cleaned[key] = _strip_secrets(val)
        return cleaned
    if isinstance(obj, (list, tuple)):
        return [_strip_secrets(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# السكيمة الموثّقة (dataclasses + schema_version)
# ---------------------------------------------------------------------------
@dataclass
class SymbolFiltersSchema:
    """صورة قابلة للتخزين من ``SymbolFilters`` (Decimal كنصوص، D8)."""

    symbol: str = ""
    tick_size: Optional[Decimal] = None
    step_size: Optional[Decimal] = None
    min_qty: Optional[Decimal] = None
    min_notional: Optional[Decimal] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "tickSize": _dec_to_str(self.tick_size),
            "stepSize": _dec_to_str(self.step_size),
            "minQty": _dec_to_str(self.min_qty),
            "minNotional": _dec_to_str(self.min_notional),
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["SymbolFiltersSchema"]:
        if not data:
            return None
        return cls(
            symbol=data.get("symbol", ""),
            tick_size=_str_to_dec(data.get("tickSize")),
            step_size=_str_to_dec(data.get("stepSize")),
            min_qty=_str_to_dec(data.get("minQty")),
            min_notional=_str_to_dec(data.get("minNotional")),
            updated_at=data.get("updatedAt"),
        )

    @classmethod
    def from_model(cls, filters) -> Optional["SymbolFiltersSchema"]:
        """يبني من ``ocobot.domain.models.SymbolFilters`` (بلا استيراده هنا)."""
        if filters is None:
            return None
        return cls(
            symbol=getattr(filters, "symbol", ""),
            tick_size=getattr(filters, "tick_size", None),
            step_size=getattr(filters, "step_size", None),
            min_qty=getattr(filters, "min_qty", None),
            min_notional=getattr(filters, "min_notional", None),
            updated_at=getattr(filters, "updated_at", None),
        )


@dataclass
class SelectedOcoContext:
    """سياق الـ OCO المختار (P1/D7/D1) اللازم لإعادة تأسيس Live context.

    يطابق حقول ``ocobot.domain.models.SelectedOCO`` الهُوِيّة: orderListId،
    symbol، الكمية المقفولة، الأسعار الثلاثة (tp / stop_trigger / stop_limit)،
    legIds، status، quantity_locked، والفلاتر. ``current_price`` لا يُخزَّن هنا
    لأنه سعر حيّ (D14) — يُلتقَط في checkpoint المراقبة كـ ``last_price``.
    """

    order_list_id: Optional[int] = None
    symbol: str = ""
    quantity: Optional[Decimal] = None
    tp: Optional[Decimal] = None
    stop_trigger: Optional[Decimal] = None
    stop_limit: Optional[Decimal] = None
    leg_ids: List[int] = field(default_factory=list)
    status: str = ""
    quantity_locked: bool = True
    filters: Optional[SymbolFiltersSchema] = None

    def to_dict(self) -> dict:
        return {
            "orderListId": self.order_list_id,
            "symbol": self.symbol,
            "quantity": _dec_to_str(self.quantity),
            "tp": _dec_to_str(self.tp),
            "stopTrigger": _dec_to_str(self.stop_trigger),
            "stopLimit": _dec_to_str(self.stop_limit),
            "legIds": list(self.leg_ids),
            "status": self.status,
            "quantityLocked": self.quantity_locked,
            "filters": self.filters.to_dict() if self.filters else None,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["SelectedOcoContext"]:
        if not data:
            return None
        return cls(
            order_list_id=data.get("orderListId"),
            symbol=data.get("symbol", ""),
            quantity=_str_to_dec(data.get("quantity")),
            tp=_str_to_dec(data.get("tp")),
            stop_trigger=_str_to_dec(data.get("stopTrigger")),
            stop_limit=_str_to_dec(data.get("stopLimit")),
            leg_ids=list(data.get("legIds") or []),
            status=data.get("status", ""),
            quantity_locked=bool(data.get("quantityLocked", True)),
            filters=SymbolFiltersSchema.from_dict(data.get("filters")),
        )

    @classmethod
    def from_model(cls, selected) -> Optional["SelectedOcoContext"]:
        """يبني من ``ocobot.domain.models.SelectedOCO`` (بلا استيراده هنا)."""
        if selected is None:
            return None
        return cls(
            order_list_id=getattr(selected, "order_list_id", None),
            symbol=getattr(selected, "symbol", ""),
            quantity=getattr(selected, "quantity", None),
            tp=getattr(selected, "tp", None),
            stop_trigger=getattr(selected, "stop_trigger", None),
            stop_limit=getattr(selected, "stop_limit", None),
            leg_ids=list(getattr(selected, "leg_ids", []) or []),
            status=getattr(selected, "status", ""),
            quantity_locked=bool(getattr(selected, "quantity_locked", True)),
            filters=SymbolFiltersSchema.from_model(getattr(selected, "filters", None)),
        )


@dataclass
class MonitoringCheckpoint:
    """checkpoint حالة المراقبة — كل حقول ``MonitoringState`` اللازمة للاستئناف.

    الحقول تطابق ``ocobot.domain.monitoring.MonitoringState`` واحدًا لواحد:
      - ``enabled``: هل المراقبة نشطة.
      - ``state``: قيمة ``MonitoringStateEnum`` (تُخزَّن كنصّ enum value).
      - ``symbol``: رمز العملة قيد المراقبة.
      - ``reference_price``: السعر المرجعي الحيّ (D14) لحساب مستوى التفعيل.
      - ``trigger_pct`` / ``tp_pct`` / ``sl_pct``: نِسب المستخدم (D6).
      - ``latched``: Trigger Latching — يبقى بعد تجاوز مستوى التفعيل.
      - ``in_flight``: One-Replacement-In-Flight — دورة قيد التنفيذ.
      - ``target_order_list_id``: orderListId الجاري (يتحدّث عند Rollover).
      - ``tolerance_pct`` / ``guard_pct``: سياسة السماحية/الحارس.
      - ``last_price``: أحدث سعر صالح (Latest Price Principle).
      - ``last_reposition``: ملخّص آخر إعادة تموضع (dict آمن — بلا أسرار).
      - ``cursor``: عدد عمليات إعادة التموضع المكتملة.
    الأرقام Decimal تُخزَّن كنصوص (str) والـ enum كقيمته النصّية.
    """

    enabled: bool = False
    state: str = "DISCONNECTED"
    symbol: str = ""
    reference_price: Optional[Decimal] = None
    trigger_pct: Optional[Decimal] = None
    tp_pct: Optional[Decimal] = None
    sl_pct: Optional[Decimal] = None
    latched: bool = False
    in_flight: bool = False
    target_order_list_id: Optional[int] = None
    tolerance_pct: Optional[Decimal] = None
    guard_pct: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    last_reposition: Optional[dict] = None
    cursor: int = 0
    trade_uid: str = ""
    session_no: int = 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "state": self.state,
            "symbol": self.symbol,
            "referencePrice": _dec_to_str(self.reference_price),
            "triggerPct": _dec_to_str(self.trigger_pct),
            "tpPct": _dec_to_str(self.tp_pct),
            "slPct": _dec_to_str(self.sl_pct),
            "latched": self.latched,
            "inFlight": self.in_flight,
            "targetOrderListId": self.target_order_list_id,
            "tolerancePct": _dec_to_str(self.tolerance_pct),
            "guardPct": _dec_to_str(self.guard_pct),
            "lastPrice": _dec_to_str(self.last_price),
            "lastReposition": self.last_reposition,
            "cursor": self.cursor,
            "tradeUid": self.trade_uid,
            "sessionNo": self.session_no,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["MonitoringCheckpoint"]:
        if not data:
            return None
        return cls(
            enabled=bool(data.get("enabled", False)),
            state=data.get("state", "DISCONNECTED"),
            symbol=data.get("symbol", ""),
            reference_price=_str_to_dec(data.get("referencePrice")),
            trigger_pct=_str_to_dec(data.get("triggerPct")),
            tp_pct=_str_to_dec(data.get("tpPct")),
            sl_pct=_str_to_dec(data.get("slPct")),
            latched=bool(data.get("latched", False)),
            in_flight=bool(data.get("inFlight", False)),
            target_order_list_id=data.get("targetOrderListId"),
            tolerance_pct=_str_to_dec(data.get("tolerancePct")),
            guard_pct=_str_to_dec(data.get("guardPct")),
            last_price=_str_to_dec(data.get("lastPrice")),
            last_reposition=data.get("lastReposition"),
            cursor=int(data.get("cursor", 0) or 0),
            trade_uid=data.get("tradeUid", ""),
            session_no=int(data.get("sessionNo", 0) or 0),
        )

    @classmethod
    def from_state(cls, state) -> "MonitoringCheckpoint":
        """يبني من ``ocobot.domain.monitoring.MonitoringState`` (بلا استيراده).

        يقبل قيمة ``state`` كـ enum (فيأخذ ``.value``) أو كنصّ.
        """
        raw_state = getattr(state, "state", "DISCONNECTED")
        state_value = getattr(raw_state, "value", raw_state)
        return cls(
            enabled=bool(getattr(state, "enabled", False)),
            state=str(state_value),
            symbol=getattr(state, "symbol", ""),
            reference_price=getattr(state, "reference_price", None),
            trigger_pct=getattr(state, "trigger_pct", None),
            tp_pct=getattr(state, "tp_pct", None),
            sl_pct=getattr(state, "sl_pct", None),
            latched=bool(getattr(state, "latched", False)),
            in_flight=bool(getattr(state, "in_flight", False)),
            target_order_list_id=getattr(state, "target_order_list_id", None),
            tolerance_pct=getattr(state, "tolerance_pct", None),
            guard_pct=getattr(state, "guard_pct", None),
            last_price=getattr(state, "last_price", None),
            last_reposition=getattr(state, "last_reposition", None),
            cursor=int(getattr(state, "cursor", 0) or 0),
            trade_uid=getattr(state, "trade_uid", ""),
            session_no=int(getattr(state, "session_no", 0) or 0),
        )


@dataclass
class LogLocations:
    """مواقع ملفات السجل — checkpoint (JSON) + audit (JSONL)."""

    checkpoint_path: Optional[str] = None
    audit_log_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "checkpointPath": self.checkpoint_path,
            "auditLogPath": self.audit_log_path,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "LogLocations":
        if not data:
            return cls()
        return cls(
            checkpoint_path=data.get("checkpointPath"),
            audit_log_path=data.get("auditLogPath"),
        )


@dataclass
class PersistedState:
    """الحمولة الكاملة المخزّنة في ملف checkpoint واحد (schema_version + محتوى)."""

    schema_version: int = SCHEMA_VERSION
    monitoring: Optional[MonitoringCheckpoint] = None
    selected_oco: Optional[SelectedOcoContext] = None
    logs: LogLocations = field(default_factory=LogLocations)
    saved_at: Optional[str] = None

    def to_dict(self) -> dict:
        payload = {
            "schemaVersion": self.schema_version,
            "monitoring": self.monitoring.to_dict() if self.monitoring else None,
            "selectedOco": self.selected_oco.to_dict() if self.selected_oco else None,
            "logs": self.logs.to_dict() if self.logs else LogLocations().to_dict(),
            "savedAt": self.saved_at,
        }
        # بوابة أمان D8: لا أسرار على القرص مهما كان مصدر الحمولة.
        return _strip_secrets(payload)

    @classmethod
    def from_dict(cls, data: dict) -> "PersistedState":
        if not isinstance(data, dict):
            raise StateStoreError("persisted state must be a JSON object")
        return cls(
            schema_version=int(data.get("schemaVersion", SCHEMA_VERSION) or SCHEMA_VERSION),
            monitoring=MonitoringCheckpoint.from_dict(data.get("monitoring")),
            selected_oco=SelectedOcoContext.from_dict(data.get("selectedOco")),
            logs=LogLocations.from_dict(data.get("logs")),
            saved_at=data.get("savedAt"),
        )


# ---------------------------------------------------------------------------
# طبقة التخزين: كتابة ذرّية + قراءة آمنة
# ---------------------------------------------------------------------------
class StateStore:
    """طبقة تخزين وحيدة: كتابة ذرّية (temp→fsync→rename) + قراءة آمنة.

    الكاتب واحد وتردّد الكتابة منخفض (عند كل انتقال حالة). التصميم يضمن:
      - لا يُترَك ملف نصف-مكتوب/تالف أبدًا؛ التعطّل وسط الكتابة يُبقي الملف
        الجيّد السابق سليمًا تمامًا.
      - القراءة الآمنة: ملف مفقود ⇒ ``None``؛ JSON تالف/مقطوع ⇒ ``None`` (أو
        ``StateStoreError`` عند ``strict=True``) لا استثناء خام على المتصل.
      - لا أسرار على القرص (D8) عبر ``_strip_secrets`` قبل كل كتابة.
    """

    def __init__(self, checkpoint_path: str, *, ensure_dir: bool = True,
                 audit_log_path: Optional[str] = None):
        if not checkpoint_path:
            raise ValueError("checkpoint path is required")
        self.checkpoint_path = checkpoint_path
        self.audit_log_path = audit_log_path
        if ensure_dir:
            parent = os.path.dirname(os.path.abspath(checkpoint_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

    # ---- write ----
    def _atomic_write_bytes(self, data: bytes) -> None:
        """يكتب ``data`` ذرّيًا إلى ``checkpoint_path``.

        الخطوات: ملف مؤقّت في نفس المجلد ⇒ write ⇒ flush ⇒ ``os.fsync`` ⇒
        ``os.replace`` (rename ذرّي) ⇒ fsync للمجلد حيث يدعمه النظام. عند أي
        فشل يُنظَّف الملف المؤقّت ولا يُمَسّ الملف الهدف السابق.
        """
        target = self.checkpoint_path
        directory = os.path.dirname(os.path.abspath(target)) or "."
        fd, tmp_path = tempfile.mkstemp(
            prefix=".{}.".format(os.path.basename(target)),
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())  # اضمن وصول البايتات للقرص قبل rename
            # rename ذرّي: إمّا الملف الجديد كاملًا أو القديم كاملًا — لا وسط بينهما.
            os.replace(tmp_path, target)
            tmp_path = None  # نجح الاستبدال — لا تنظيف بعده
            self._fsync_dir(directory)
        finally:
            # تنظيف الملف المؤقّت عند أي فشل (تعطّل قبل/أثناء replace).
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        """fsync لدليل الحاوية لتثبيت إدخال الـ rename (حيث يدعمه النظام).

        على أنظمة (مثل Windows) لا تدعم فتح/مزامنة الدليل، نتجاهل بهدوء.
        """
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    def save(self, state: PersistedState) -> PersistedState:
        """يحفظ ``PersistedState`` ذرّيًا كـ JSON (Decimal كنصوص، بلا أسرار).

        يملأ ``logs`` تلقائيًا بمسارات المتجر إن لم تُضبَط، ويعيد الحمولة
        المكتوبة (بعد التنقية) للاطلاع/الاختبار.
        """
        # اضمن أن مواقع السجل تعكس مسارات هذا المتجر.
        if state.logs is None:
            state.logs = LogLocations()
        if not state.logs.checkpoint_path:
            state.logs.checkpoint_path = self.checkpoint_path
        if not state.logs.audit_log_path and self.audit_log_path:
            state.logs.audit_log_path = self.audit_log_path

        payload = state.to_dict()  # يتضمّن _strip_secrets
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        self._atomic_write_bytes(text.encode("utf-8"))
        return PersistedState.from_dict(payload)

    # ---- read ----
    def load(self, *, strict: bool = False) -> Optional[PersistedState]:
        """قراءة آمنة: ملف مفقود ⇒ None؛ JSON تالف ⇒ None (أو خطأ عند strict).

        لا يُسرَّب أي استثناء خام للمتصل في الوضع الافتراضي — لا يتعطّل التطبيق
        بسبب ملف سيّئ (بما في ذلك بايتات غير قابلة للفكّ كـ UTF-8).
        """
        try:
            with open(self.checkpoint_path, "rb") as handle:
                raw_bytes = handle.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            if strict:
                raise StateStoreError(f"cannot read checkpoint: {exc}") from exc
            return None

        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            if strict:
                raise StateStoreError(f"corrupt checkpoint bytes: {exc}") from exc
            return None

        if not raw.strip():
            # ملف فارغ/مقطوع تمامًا — عامله كغياب.
            if strict:
                raise StateStoreError("checkpoint file is empty")
            return None

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            if strict:
                raise StateStoreError(f"corrupt checkpoint JSON: {exc}") from exc
            return None

        try:
            return PersistedState.from_dict(data)
        except StateStoreError:
            if strict:
                raise
            return None
        except Exception as exc:  # noqa: BLE001 — حصانة أخيرة ضد أي بنية غير متوقّعة
            if strict:
                raise StateStoreError(f"invalid checkpoint structure: {exc}") from exc
            return None

    def clear(self) -> None:
        """يحذف ملف الـ checkpoint إن وُجد (لا خطأ إن كان غائبًا)."""
        try:
            os.remove(self.checkpoint_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass


__all__ = [
    "SCHEMA_VERSION",
    "StateStore",
    "StateStoreError",
    "PersistedState",
    "MonitoringCheckpoint",
    "SelectedOcoContext",
    "SymbolFiltersSchema",
    "LogLocations",
]
