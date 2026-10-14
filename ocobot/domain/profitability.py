"""مُجمِّع ربحية خالص لكل وضع خروج (G1.53) — قراءة فقط، بلا أي أثر جانبي.

دالة **خالصة** (pure) تُجمّع الصفقات المنتهية (CLOSED) حسب «وسيلة الخروج»
(``exit_source``: MONITORING / PRICE_BRACKET / BTC_FOLLOW / POSITION_SAFETY_NET /
MANUAL_EXIT) وتُنتج لكل وضع مقاييس ربحية احترافية. تُعاد استخدام مُخرجات
``ocobot.domain.completed_trades.build_completed_trades`` كما هي (قراءة فقط) — لا
يمسّ هذا الموديول سجل التدقيق ولا يكتب أي شيء على القرص ولا يستورد Qt/شبكة.

الدقة المالية (مطابقة لبقية المشروع): كل الحساب على ``Decimal`` حصراً — لا
``float`` للمال إطلاقًا. القيم الواصلة كنصوص (من سجل التدقيق المُسلسَل عبر
``json.dumps(default=str)``) تُعاد إلى ``Decimal`` عند القراءة.

تعريف المقاييس لكل وضع (موثّق صراحةً، متّسق مع عقد G1.53):
  - ``n``            = عدد الصفقات المنتهية المنسوبة للوضع.
  - ``win_rate``     = |profit_pct > 0| / n × 100  (نسبة الرابحات من كل صفقات
                       الوضع؛ الصفقة بلا ربح متاح لا تُحتسب رابحة).
  - ``avg_return_pct`` = متوسّط ``profit_pct`` على الصفقات التي تتوفّر لها نسبة
                       ربح فقط (mean على المتاح)؛ ``None`` إن لم تتوفّر أي نسبة.
  - ``net_usd``      = مجموع ``profit_usd`` المتاح (صفر إن لم يتوفّر شيء).
  - ``expectancy``   = net_usd / n  (العائد المتوقّع للصفقة الواحدة؛ ``None`` إن n=0).

وعند توفّر telemetry تنفيذ الخروج (``exit_execution`` من G1.53/chunk_2) تُضاف:
  - ``avg_slippage_pct`` = متوسّط ``slippage_pct`` على سجلّات التنفيذ الحقيقية
                       (``dry_run == False``) للوضع؛ ``None`` إن لا سجلّات.
  - ``floor_rate``   = |reached_floor| / n_exec × 100 على السجلّات الحقيقية.
  - ``n_exec``       = عدد سجلّات التنفيذ الحقيقية المنسوبة للوضع.
سجلّات ``dry_run == True`` (معاينات) تُستبعَد كليًّا من تجميع الـtelemetry.

مكتبة قياسية فقط (decimal, dataclasses, typing). لا Qt، لا شبكة، لا كتابة قرص.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


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


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """قارئ محايد للنوع: يدعم dataclass/كائنًا بسمات أو ``dict`` (للاختبار)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_bool(value: Any) -> bool:
    """تحويل متسامح إلى منطقي (يدعم القيم المُسلسَلة 'true'/'false'/'1'/'0')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


# ---------------------------------------------------------------------------
# سكيمة النتيجة (dataclass مُنمَّطة) — قيم Decimal أو None (لا floats)
# ---------------------------------------------------------------------------
@dataclass
class ModeProfitability:
    """مقاييس ربحية وضع خروج واحد (قيم ``Decimal`` أو ``None``)."""

    mode: str
    n: int
    win_rate: Decimal
    avg_return_pct: Optional[Decimal]
    net_usd: Decimal
    expectancy: Optional[Decimal]
    # تُملأ فقط عند توفّر telemetry تنفيذ حقيقي (dry_run == False) لهذا الوضع.
    n_exec: int = 0
    avg_slippage_pct: Optional[Decimal] = None
    floor_rate: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# قارئ telemetry تنفيذ الخروج (خالص) — من سجلّات تدقيق مُحلَّلة مسبقًا
# ---------------------------------------------------------------------------
# الحقول الرقمية في سجلّ exit_execution التي تُعاد إلى Decimal عند القراءة.
_EXEC_DECIMAL_FIELDS = (
    "requested_price", "filled_price", "live_bid", "slippage_pct",
    "band_pct", "floor_price", "qty", "commission",
)


def net_pnl(gross_usd: Any, commission_usd: Any) -> Optional[Decimal]:
    """G1.53/chunk_3: صافي PnL = الإجمالي − العمولة (Decimal)، لو متاح.

    دالة **خالصة**. ``None`` إن غاب ``gross_usd``. تُعامَل العمولة الغائبة كصفر.
    تحذير: الطرح صحيح فقط إذا كانت العمولة بعملة الاقتباس نفسها (USD-like)؛ لا
    يُجري هذا الموديول أي تحويل عملات — المسؤولية على المُستدعي.
    """
    gross = _to_dec(gross_usd)
    if gross is None:
        return None
    comm = _to_dec(commission_usd) or _ZERO
    return gross - comm


def extract_exit_executions(records: List[dict]) -> List[dict]:
    """يستخرج سجلّات ``exit_execution`` من سجلّات التدقيق الزمنية (قراءة فقط).

    لكل سجلّ ``event == "exit_execution"`` يُعيد نسخة من ``details`` مع تحويل
    الحقول الرقمية إلى ``Decimal`` و``reached_floor``/``dry_run`` إلى منطقي.
    متسامح تمامًا: أي سجلّ غير مطابق/تالف يُتجاهَل بلا رفع استثناء.
    """
    out: List[dict] = []
    for rec in records or []:
        if not isinstance(rec, dict) or rec.get("event") != "exit_execution":
            continue
        det = rec.get("details", {}) or {}
        if not isinstance(det, dict):
            continue
        norm: Dict[str, Any] = dict(det)
        for key in _EXEC_DECIMAL_FIELDS:
            if key in norm:
                norm[key] = _to_dec(norm.get(key))
        norm["reached_floor"] = _as_bool(det.get("reached_floor"))
        norm["dry_run"] = _as_bool(det.get("dry_run"))
        norm["source"] = det.get("source") or ""
        out.append(norm)
    return out


# ---------------------------------------------------------------------------
# المُجمِّع الخالص
# ---------------------------------------------------------------------------
def profitability_by_mode(
    trades: List[Any],
    exit_executions: Optional[List[dict]] = None,
) -> Dict[str, ModeProfitability]:
    """يُجمّع الصفقات المنتهية حسب ``exit_source`` ويُعيد مقاييس كل وضع.

    ``trades``: قائمة ``CompletedTrade`` (أو dict مكافئ للاختبار). تُستبعَد
    الصفقة المفتوحة (``status == "live"``) وأي عنصر بلا ``exit_source``.
    ``exit_executions`` (اختياري): سجلّات telemetry مُطبَّعة (من
    ``extract_exit_executions``) أو details خام؛ تُستعمل سجلّاتها الحقيقية فقط
    (``dry_run == False``) لحساب ``avg_slippage_pct`` و``floor_rate`` لكل وضع.

    يُعيد قاموسًا ``{mode: ModeProfitability}`` لكل وضع ظهرت له صفقة منتهية.
    كل الحساب على ``Decimal``. دالة خالصة بلا أي أثر جانبي.
    """
    # تجميع الصفقات المنتهية حسب الوضع.
    by_mode_trades: Dict[str, List[Any]] = {}
    for t in trades or []:
        if str(_get(t, "status", "closed")) == "live":
            continue
        mode = _get(t, "exit_source", "") or ""
        if not mode:
            continue
        by_mode_trades.setdefault(mode, []).append(t)

    # تطبيع telemetry وتجميعها حسب المصدر (السجلّات الحقيقية فقط).
    execs_by_mode: Dict[str, List[dict]] = {}
    if exit_executions:
        for rec in exit_executions:
            if not isinstance(rec, dict):
                continue
            # يقبل إمّا سجلّ مُطبَّع من extract_exit_executions أو details خام.
            if _as_bool(rec.get("dry_run")):
                continue
            source = rec.get("source") or ""
            if not source:
                continue
            execs_by_mode.setdefault(source, []).append(rec)

    result: Dict[str, ModeProfitability] = {}
    for mode, mode_trades in by_mode_trades.items():
        n = len(mode_trades)
        returns: List[Decimal] = []
        usds: List[Decimal] = []
        wins = 0
        for t in mode_trades:
            pct = _to_dec(_get(t, "profit_pct"))
            if pct is not None:
                returns.append(pct)
                if pct > _ZERO:
                    wins += 1
            usd = _to_dec(_get(t, "profit_usd"))
            if usd is not None:
                usds.append(usd)

        win_rate = (Decimal(wins) / Decimal(n) * _HUNDRED) if n else _ZERO
        avg_return_pct = (sum(returns, _ZERO) / Decimal(len(returns))) if returns else None
        net_usd = sum(usds, _ZERO)
        expectancy = (net_usd / Decimal(n)) if n else None

        stats = ModeProfitability(
            mode=mode,
            n=n,
            win_rate=win_rate,
            avg_return_pct=avg_return_pct,
            net_usd=net_usd,
            expectancy=expectancy,
        )

        # إضافة مقاييس الـtelemetry إن توفّرت سجلّات تنفيذ حقيقية لهذا الوضع.
        mode_execs = execs_by_mode.get(mode, [])
        if mode_execs:
            slips: List[Decimal] = []
            floor_hits = 0
            for rec in mode_execs:
                slip = _to_dec(rec.get("slippage_pct"))
                if slip is not None:
                    slips.append(slip)
                if _as_bool(rec.get("reached_floor")):
                    floor_hits += 1
            n_exec = len(mode_execs)
            stats.n_exec = n_exec
            stats.avg_slippage_pct = (sum(slips, _ZERO) / Decimal(len(slips))) if slips else None
            stats.floor_rate = (Decimal(floor_hits) / Decimal(n_exec) * _HUNDRED) if n_exec else None

        result[mode] = stats

    return result
