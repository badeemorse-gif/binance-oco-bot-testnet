"""Completed-Trades read-model (G1.14) — قراءة فقط فوق سجل التدقيق JSONL.

نموذج قراءة خالص (pure read-model) يُعيد بناء «الصفقات المنتهية (CLOSED)» من
سجل التدقيق append-only (``ocobot.core.audit_log``) دون المساس به إطلاقًا. لا
يكتب هذا الموديول أي شيء في سجل التدقيق؛ عملية الإخفاء من الواجهة (dismiss)
تُخزَّن في ملف JSON منفصل تمامًا (``DismissStore``) بجانب ملف الحالة/التدقيق.

ثبات D11 (أمر واحد نشط في كل مرّة): السجل تسلسلي، لذا نُقسّم الصفقات على حدود
``monitor_start``: كل صفقة تبدأ عند ``monitor_start`` وتمتدّ حتى أول
``monitor_closed`` تالٍ (شاملًا إياه) — أو حتى ``monitor_start`` التالي إن لم
يُغلق بعد (صفقة مفتوحة تُستبعَد لأنها غير منتهية).

الدقة المالية (مطابقة لبقية المشروع): الأسعار/الكميات ``Decimal``؛ وبما أنّ
``AuditLog`` سلسل Decimal كنصوص عبر ``json.dumps(default=str)`` فإنّ الأرقام
تصل كنصوص — نُعيدها إلى ``Decimal`` عند القراءة.

مكتبة قياسية فقط (json, decimal, dataclasses, typing). لا Qt، لا شبكة، ولا أي
كتابة على القرص عدا ``DismissStore.dismiss``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

# اسم ملف الإخفاء الافتراضي — يجاور ملف الحالة/التدقيق (قرار T5: نفس المجلّد).
DEFAULT_DISMISS_FILENAME = "ocobot_completed_dismissed.json"


# ---------------------------------------------------------------------------
# مساعِدات Decimal-safe (نصّ مُسلسَل -> Decimal) — لا floats للمال إطلاقًا.
# ---------------------------------------------------------------------------
# G1.46: مجموعة قيم exit_source المسموح بها (نسبة الخروج). أي قيمة خارجها ⇒
# تُعامَل كـ MONITORING (الافتراضي). إضافة بحتة لا تمسّ منطق التداول.
_EXIT_SOURCE_ALLOWED: Set[str] = {
    "MONITORING",
    "PRICE_BRACKET",
    "BTC_FOLLOW",
    "POSITION_SAFETY_NET",
    "MANUAL_EXIT",  # G1.52: الخروج اليدوي كوسيلة إغلاق مُعترف بها.
}


def _derive_exit_source(segment: List[dict]) -> str:
    """يشتقّ exit_source من آخر علامة ``exit_source`` داخل مقطع صفقة مُغلقة.

    يمسح سجلّات المقطع ويحتفظ بآخر سجلّ ``event == "exit_source"`` ويقرأ
    ``details["source"]``. القيمة المقبولة فقط من ``_EXIT_SOURCE_ALLOWED``؛
    أي غياب/قيمة تالفة/غير معروفة ⇒ ``"MONITORING"`` (توافق خلفي، لا رفع
    استثناء). علامات متعدّدة ⇒ الأخيرة تفوز.
    """
    source = "MONITORING"
    for rec in segment:
        if rec.get("event") == "exit_source":
            det = rec.get("details", {}) or {}
            candidate = det.get("source")
            if candidate in _EXIT_SOURCE_ALLOWED:
                source = candidate
            else:
                source = "MONITORING"
    return source


def _to_dec(value: Any) -> Optional[Decimal]:
    """يستعيد ``Decimal`` من قيمة مُسلسَلة (None/'' تبقى None؛ التالف -> None)."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# السكيمة العامة (dataclasses مُنمَّطة)
# ---------------------------------------------------------------------------
@dataclass
class PositioningStep:
    """خطوة واحدة في سلسلة التموضع (أمر OCO واحد ضمن الصفقة).

    ``price`` = السعر المرجعي/السوقي عند هذه الخطوة (سعر بدء المراقبة للخطوة
    الأولى، أو سعر إعادة التموضع للخطوات التالية). الحقول الاختيارية ``None``
    تعني أنّ الواجهة ستعرض شرطة (dash).
    """

    order_list_id: int
    ts: str
    price: Optional[Decimal] = None
    stop_trigger: Optional[Decimal] = None
    stop_limit: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None


@dataclass
class CompletedTrade:
    """صفقة منتهية (CLOSED) أُعيد بناؤها من مقطع سجل التدقيق."""

    trade_key: str
    symbol: str
    reference_price: Optional[Decimal]
    opened_at: str
    closed_at: str
    close_reason: str
    exit_price: Optional[Decimal]
    side: Optional[str]
    quantity: Optional[Decimal]
    steps: List[PositioningStep] = field(default_factory=list)
    profit_usd: Optional[Decimal] = None
    profit_pct: Optional[Decimal] = None
    profit_available: bool = False
    # G1.23: معرّفات الجلسة/الصفقة المشتقّة من monitor_start — افتراضات آمنة
    # للتوافق الخلفي مع السجلّات القديمة التي تفتقر إليها.
    trade_uid: str = ""        # المعرّف الثابت لكل صفقة (8 hex) أو "" للقديم.
    session_no: int = 0        # رقم الجلسة ضمن الصفقة (0 للقديم).
    session_id: str = ""       # مفتاح العرض/الفرز: "#<trade_uid>.<session_no>".
    end_reason: str = ""       # سلسلة enum الخام من monitor_closed (أو "").
    status: str = "closed"     # "closed" للصفقات المنتهية، "live" للصفقة المفتوحة.
    # G1.46: نسبة الخروج (attribution) — أي «وسيلة» أغلقت الصفقة. إضافة بحتة.
    # تُشتَقّ من آخر علامة exit_source داخل مقطع الصفقة؛ غياب العلامة ⇒ MONITORING
    # (التوافق الخلفي مع السجلّات القديمة). للصفقة المفتوحة (LIVE) تبقى "".
    exit_source: str = "MONITORING"


# ---------------------------------------------------------------------------
# قراءة السجل (قراءة فقط، تسامح مع الأسطر الفارغة/التالفة)
# ---------------------------------------------------------------------------
def parse_audit_jsonl(path: str) -> List[dict]:
    """يقرأ سجل التدقيق JSONL ويعيد قائمة سجلّات (dict) بالترتيب الزمني.

    التسامح إلزامي: الأسطر الفارغة أو التالفة (JSON غير صالح أو ليست كائنًا)
    تُتخطّى بلا رفع استثناء. إن لم يوجد الملف تُعاد قائمة فارغة. لا يكتب شيئًا.
    """
    if not path or not os.path.exists(path):
        return []
    records: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    except OSError:
        return []
    return records


# ---------------------------------------------------------------------------
# حساب الربح (دالة خالصة)
# ---------------------------------------------------------------------------
def compute_profit(
    reference_price: Optional[Decimal],
    exit_price: Optional[Decimal],
    quantity: Optional[Decimal],
) -> Optional[Tuple[Optional[Decimal], Decimal]]:
    """يحسب (profit_usd, profit_pct) من السعر المرجعي وسعر الخروج والكمية.

    يُعيد ``None`` كليًّا إذا كان ``exit_price`` أو ``reference_price`` مفقودًا
    (المعنى: «غير متاح»). عدا ذلك:
      profit_pct = (exit - reference) / reference * 100
      profit_usd = (exit - reference) * quantity  (أو None إن غابت الكمية)

    يُعيد المرتبة بالشكل ``(profit_usd, profit_pct)``. كل الحساب على ``Decimal``.
    """
    ref = _to_dec(reference_price)
    exit_p = _to_dec(exit_price)
    if ref is None or exit_p is None:
        return None
    if ref == 0:
        return None
    delta = exit_p - ref
    profit_pct = (delta / ref) * Decimal("100")
    qty = _to_dec(quantity)
    profit_usd = (delta * qty) if qty is not None else None
    return profit_usd, profit_pct


# ---------------------------------------------------------------------------
# تقطيع السجل إلى مقاطع صفقات (segment) على حدود monitor_start
# ---------------------------------------------------------------------------
def _segment_records(records: List[dict]) -> List[List[dict]]:
    """يُقسّم السجلّات الزمنية إلى مقاطع، كل مقطع يبدأ بـ ``monitor_start``.

    أي سجلّات تسبق أوّل ``monitor_start`` تُهمَل. يُفتح مقطع عند كل
    ``monitor_start``؛ وإن ظهر ``monitor_start`` جديد قبل إغلاق المقطع الحالي
    يُغلق السابق (يبقى غير منتهٍ) ويُفتح الجديد.
    """
    segments: List[List[dict]] = []
    current: Optional[List[dict]] = None
    for rec in records:
        event = rec.get("event")
        if event == "monitor_start":
            if current is not None:
                segments.append(current)
            current = [rec]
        elif current is not None:
            current.append(rec)
    if current is not None:
        segments.append(current)
    return segments


def _build_steps(
    segment: List[dict], start_details: dict, start_ts: str
) -> List[PositioningStep]:
    """يبني قائمة ``PositioningStep`` مرتّبة لسلسلة التموضع داخل مقطع صفقة."""
    steps: List[PositioningStep] = []

    initial_id = start_details.get("order_list_id")

    # الخطوة الأولى (الأمر الابتدائي): السعر = سعر بدء المراقبة.
    # المستويات من أقرب draft_built بنفس order_list_id إن وُجد، وإلا None.
    initial_draft = None
    for rec in segment:
        if rec.get("event") == "draft_built":
            det = rec.get("details", {}) or {}
            if det.get("order_list_id") == initial_id:
                initial_draft = det  # أقرب (آخر) draft بنفس المعرّف
    if initial_id is not None:
        steps.append(
            PositioningStep(
                order_list_id=initial_id,
                ts=start_ts,
                price=_to_dec(start_details.get("reference_price")),
                stop_trigger=_to_dec((initial_draft or {}).get("stop_trigger")),
                stop_limit=_to_dec((initial_draft or {}).get("stop_limit")),
                sell_price=_to_dec((initial_draft or {}).get("tp_price")),
            )
        )

    # اجمع سجلّات repositioned لمطابقة السعر/الوقت لكل خطوة إعادة تموضع.
    repositioned = [
        r for r in segment if r.get("event") == "repositioned"
    ]
    repositioned_queue = list(repositioned)

    for rec in segment:
        if rec.get("event") != "reposition_success":
            continue
        det = rec.get("details", {}) or {}
        new_id = det.get("new_order_list_id")

        # مطابقة سجلّ repositioned: أولًا بالـ new_target == new_id، وإلا بالترتيب.
        match = None
        for rep in repositioned_queue:
            rdet = rep.get("details", {}) or {}
            if rdet.get("new_target") == new_id:
                match = rep
                break
        if match is None and repositioned_queue:
            match = repositioned_queue[0]
        if match is not None:
            repositioned_queue.remove(match)

        step_ts = (match or rec).get("ts", rec.get("ts", ""))
        rep_price = _to_dec(((match or {}).get("details", {}) or {}).get("price"))

        steps.append(
            PositioningStep(
                order_list_id=new_id,
                ts=step_ts,
                price=rep_price,
                stop_trigger=_to_dec(det.get("stop_trigger")),
                stop_limit=_to_dec(det.get("stop_limit")),
                sell_price=_to_dec(det.get("tp_price")),
            )
        )
    return steps


def build_completed_trades(records: List[dict]) -> List[CompletedTrade]:
    """يبني قائمة ``CompletedTrade`` من سجلّات التدقيق الزمنية.

    يُستبعَد أي مقطع لم يصل إلى ``monitor_closed`` (صفقة مفتوحة/غير منتهية).
    الترتيب المُعاد: الأحدث أولًا (newest-first) — المقطع الأخير زمنيًّا أولًا.

    G1.23: يُدرَج أي مقطع يحوي ``monitor_closed`` بغضّ النظر عن ``end_reason``
    (completed_tp / completed_sl / stopped_manual / stopped_disconnect /
    stopped_other) — لا يُشترط وجود تعبئة خروج أو ربح؛ الجلسات المُوقَفة قد
    تبقى بلا exit_price/profit (profit_available=False) وتعرضها الواجهة NA.
    """
    trades: List[CompletedTrade] = []
    for segment in _segment_records(records):
        start = segment[0]
        if start.get("event") != "monitor_start":
            continue
        start_details = start.get("details", {}) or {}
        start_ts = start.get("ts", "")

        # G1.23: معرّفات الصفقة/الجلسة من monitor_start (قد تغيب في القديم).
        trade_uid = start_details.get("trade_uid") or ""
        session_no_raw = start_details.get("session_no")
        try:
            session_no = int(session_no_raw) if session_no_raw is not None else 0
        except (TypeError, ValueError):
            session_no = 0
        # session_id يُبنى فقط عند توفّر trade_uid (غير فارغ)؛ وإلا "".
        session_id = ("#%s.%d" % (trade_uid, session_no)) if trade_uid else ""

        # لا بد من وجود monitor_closed داخل المقطع لاعتباره منتهيًا.
        closed = None
        for rec in segment:
            if rec.get("event") == "monitor_closed":
                closed = rec
                break
        if closed is None:
            # صفقة مفتوحة (لا monitor_closed) -> أدرِجها كصفقة LIVE بدل استبعادها.
            # نبني الإدخال من البيانات المتاحة في هذه النقطة من الحلقة
            # (monitor_start + آخر قيم إعادة التموضع) تمامًا كما يفعل المسار
            # المُغلق، لكن دون سعر/سبب خروج وبعلامة status="live".
            live_steps = _build_steps(segment, start_details, start_ts)

            live_quantity: Optional[Decimal] = None
            for rec in segment:
                if rec.get("event") == "draft_built":
                    det = rec.get("details", {}) or {}
                    q = _to_dec(det.get("quantity"))
                    if q is not None:
                        live_quantity = q

            live_side: Optional[str] = None
            for rec in segment:
                if rec.get("event") == "trade_closed_fill":
                    det = rec.get("details", {}) or {}
                    live_side = det.get("side")

            live_reference_price = _to_dec(start_details.get("reference_price"))
            live_initial_id = start_details.get("order_list_id")
            live_trade_key = str(live_initial_id) + "@" + start_ts

            live_profit = compute_profit(live_reference_price, None, live_quantity)
            if live_profit is None:
                live_profit_usd, live_profit_pct = None, None
            else:
                live_profit_usd, live_profit_pct = live_profit

            trades.append(
                CompletedTrade(
                    trade_key=live_trade_key,
                    symbol=start_details.get("symbol", ""),
                    reference_price=live_reference_price,
                    opened_at=start_ts,
                    closed_at="",
                    close_reason="",
                    exit_price=None,
                    side=live_side,
                    quantity=live_quantity,
                    steps=live_steps,
                    profit_usd=live_profit_usd,
                    profit_pct=live_profit_pct,
                    profit_available=False,
                    trade_uid=trade_uid,
                    session_no=session_no,
                    session_id=session_id,
                    end_reason="live",
                    status="live",
                    exit_source="",  # G1.46: لا خروج بعد ⇒ لا نسبة خروج.
                )
            )
            continue  # صفقة مفتوحة أُدرجت كـ LIVE -> تابِع المقطع التالي
        # G1.23: وجود monitor_closed وحده كافٍ للإدراج مهما كان end_reason —
        # لا نشترط TP/SL ولا تعبئة خروج.

        closed_details = closed.get("details", {}) or {}

        steps = _build_steps(segment, start_details, start_ts)

        # الكمية = آخر draft_built.quantity معروف داخل المقطع (إن وُجد).
        quantity: Optional[Decimal] = None
        for rec in segment:
            if rec.get("event") == "draft_built":
                det = rec.get("details", {}) or {}
                q = _to_dec(det.get("quantity"))
                if q is not None:
                    quantity = q

        # trade_closed_fill (اختياري، أُضيف لاحقًا): يوفّر سعر/جانب الخروج الحقيقي.
        # G1.52: نُفضّل آخر تعبئة جانبها SELL (الأوامر المستقلّة g=-1 تُلتقط أيضًا)؛
        # وإن لم توجد أي تعبئة SELL نرجع إلى آخر trade_closed_fill (توافق خلفي).
        # الإسناد يبقى بعضوية المقطع فقط (لا مطابقة order_list_id). أوامر OCO
        # جانبها SELL أصلًا فلا يتغيّر سلوكها.
        exit_price: Optional[Decimal] = None
        side: Optional[str] = None
        last_any_fill: Optional[dict] = None
        last_sell_fill: Optional[dict] = None
        for rec in segment:
            if rec.get("event") == "trade_closed_fill":
                det = rec.get("details", {}) or {}
                last_any_fill = det
                if det.get("side") == "SELL":
                    last_sell_fill = det
        chosen_fill = last_sell_fill if last_sell_fill is not None else last_any_fill
        if chosen_fill is not None:
            exit_price = _to_dec(chosen_fill.get("fill_price"))
            side = chosen_fill.get("side")

        reference_price = _to_dec(start_details.get("reference_price"))
        initial_id = start_details.get("order_list_id")
        trade_key = str(initial_id) + "@" + start_ts

        # G1.23: end_reason الخام من monitor_closed (قد يغيب في بعض المسارات).
        end_reason = closed_details.get("end_reason", "") or ""

        profit = compute_profit(reference_price, exit_price, quantity)
        if profit is None:
            profit_usd, profit_pct = None, None
            profit_available = False
        else:
            profit_usd, profit_pct = profit
            profit_available = True

        trades.append(
            CompletedTrade(
                trade_key=trade_key,
                symbol=start_details.get("symbol", ""),
                reference_price=reference_price,
                opened_at=start_ts,
                closed_at=closed.get("ts", ""),
                close_reason=closed_details.get("reason", ""),
                exit_price=exit_price,
                side=side,
                quantity=quantity,
                steps=steps,
                profit_usd=profit_usd,
                profit_pct=profit_pct,
                profit_available=profit_available,
                trade_uid=trade_uid,
                session_no=session_no,
                session_id=session_id,
                end_reason=end_reason,
                exit_source=_derive_exit_source(segment),  # G1.46
            )
        )

    trades.reverse()  # الأحدث أولًا
    return trades


# ---------------------------------------------------------------------------
# مخزن الإخفاء (dismiss) — ملف JSON منفصل، لا يمسّ سجل التدقيق إطلاقًا
# ---------------------------------------------------------------------------
class DismissStore:
    """مخزن مفاتيح الصفقات المُخفاة من الواجهة (منفصل عن سجل التدقيق).

    يُخزَّن كملف JSON يحوي قائمة مفاتيح. متسامح مع الملف المفقود/التالف (يُعامَل
    كمجموعة فارغة). الكتابة الوحيدة في هذا الموديول تحدث هنا عبر ``dismiss``.
    """

    def __init__(self, path: str):
        if not path:
            raise ValueError("dismiss store path is required")
        self.path = path

    def load(self) -> Set[str]:
        """يقرأ مجموعة المفاتيح المُخفاة (مجموعة فارغة إن غاب/تلف الملف)."""
        if not os.path.exists(self.path):
            return set()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return set()
        if isinstance(data, list):
            return {str(key) for key in data}
        return set()

    def is_dismissed(self, key: str) -> bool:
        """هل المفتاح مُخفًى؟"""
        return str(key) in self.load()

    def dismiss(self, key: str) -> Set[str]:
        """يُضيف مفتاحًا ويُثبّته في ملف الإخفاء (JSON). يعيد المجموعة بعد الإضافة."""
        keys = self.load()
        keys.add(str(key))
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(sorted(keys), handle, ensure_ascii=False)
        return keys


def default_dismiss_path(audit_path: str) -> str:
    """مسار ملف الإخفاء الافتراضي: نفس مجلّد ملف التدقيق/الحالة."""
    parent = os.path.dirname(os.path.abspath(audit_path)) if audit_path else os.getcwd()
    return os.path.join(parent, DEFAULT_DISMISS_FILENAME)


def load_completed_trades(
    audit_path: str, dismiss_path: Optional[str] = None
) -> List[CompletedTrade]:
    """يقرأ + يبني + يُرشّح الصفقات المُخفاة.

    يعتمد على ``parse_audit_jsonl`` ثم ``build_completed_trades``، ثم يُسقط أي
    صفقة مفتاحها موجود في ``DismissStore``. مسار الإخفاء الافتراضي يجاور ملف
    التدقيق إن لم يُمرَّر صراحةً.
    """
    records = parse_audit_jsonl(audit_path)
    trades = build_completed_trades(records)
    store = DismissStore(dismiss_path or default_dismiss_path(audit_path))
    dismissed = store.load()
    if not dismissed:
        return trades
    return [t for t in trades if t.trade_key not in dismissed]


# ---------------------------------------------------------------------------
# مُسجّل الإغلاق (fill recorder) — مصنع callable للحقن عبر on_order_event
# ---------------------------------------------------------------------------
def build_fill_recorder(audit_log, next_callback=None):
    """يبني ``callable(event: dict)`` يُسجّل إغلاق الصفقة (FILLED) append-only.

    يُعيد دالّة صالحة لتمريرها إلى المعامل القائم ``on_order_event`` في باني
    ``UserDataStreamConsumer``. تكتب الدالّة حدثًا إضافيًا باسم
    ``trade_closed_fill`` عبر ``AuditLog.record`` فقط حين يكون الحدث تقرير
    تنفيذ (``e == "executionReport"``) بحالة نهائية (``X == "FILLED"``)، ثم
    تُنادي ``next_callback`` دائمًا (إن وُجد) للحفاظ على أي معالِج قائم.

    السلامة (مطابقة لنمط ``_record`` في المشروع): كامل الجسم ملفوف بـ
    ``try/except`` يبتلع كل الاستثناءات، فلا يُمكن لهذه الدالّة أن تُعطّل تيار
    بيانات المستخدم إطلاقًا. مكتبة قياسية فقط، بلا Qt وبلا شبكة، والكتابة
    append-only حصريًّا عبر ``AuditLog.record``.

    G1.52: يُشترط أيضًا ``S == "SELL"`` (تعبئات الدخول BUY ليست إغلاقًا)، ولا
    نُرشّح بـ ``g`` فالأوامر المستقلّة (``g == -1``) تُلتقط. أُضيف للحقول
    ``order_id`` (i) و``client_order_id`` (c).

    مطابقة الحقول (executionReport):
      g -> order_list_id, s -> symbol, L -> fill_price, S -> side,
      z -> quantity, X -> status, i -> order_id, c -> client_order_id.

    للتفعيل عند توفّر نقطة تجميع تُنشئ UserDataStreamConsumer: مرّر
    on_order_event=build_fill_recorder(audit, prior_on_order_event) إلى الباني.
    يكتب حدثًا إضافيًا append-only باسم trade_closed_fill دون تعديل منطق
    المستهلك أو المحرّك.
    """

    def _recorder(event: dict) -> None:
        try:
            if (
                event.get("e") == "executionReport"
                and event.get("X") == "FILLED"
                and event.get("S") == "SELL"  # G1.52: تعبئات الدخول BUY ليست إغلاقًا.
            ):
                # G1.52: لا نُرشّح بـ g — الأوامر المستقلّة (g=-1) تُلتقط كذلك.
                audit_log.record(
                    "trade_closed_fill",
                    {
                        "order_list_id": event.get("g"),
                        "symbol": event.get("s"),
                        "fill_price": event.get("L"),
                        "side": event.get("S"),
                        "quantity": event.get("z"),
                        "status": event.get("X"),
                        "order_id": event.get("i"),
                        "client_order_id": event.get("c"),
                    },
                )
            if next_callback is not None:
                next_callback(event)
        except Exception:
            # نمط السلامة: لا نرفع شيئًا كي لا نُعطّل تيار بيانات المستخدم.
            try:
                if next_callback is not None:
                    next_callback(event)
            except Exception:
                pass

    return _recorder


def make_exit_source_recorder(audit_log):
    """G1.52: يبني ``callable(source)`` يُسجّل حدث ``exit_source`` في سجل التدقيق.

    يُحقَن (opt-in) في وسائل الخروج الأربع (قوس السعر/شبكة أمان المركز/حارس هبوط
    BTC/الخروج اليدوي) ليكتب مصدر الخروج append-only لحظة الإطلاق، فيلتقطه
    ``_derive_exit_source`` ضمن مقطع الصفقة وتُنسب للوسيلة الصحيحة بدل MONITORING.
    يسجّل فقط المصادر المسموح بها (``_EXIT_SOURCE_ALLOWED``)؛ محروس بالكامل (لا
    يرمي)، وبلا أثر عند ``audit_log is None`` (توافق/لا انحدار). مكتبة قياسية فقط.
    """

    def _note(source) -> None:
        try:
            if audit_log is not None and source in _EXIT_SOURCE_ALLOWED:
                audit_log.record("exit_source", {"source": source})
        except Exception:
            pass

    return _note
