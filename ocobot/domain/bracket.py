"""قوس الخروج بالسعر (Price Exit Bracket) — G1.32b (منطق خالص، بلا Qt/شبكة).

يحوي:
  - ``BracketConfig``: ``{enabled, lower, upper}`` حدّان سعريّان (أسعار لا نِسب).
  - ``validate_bracket(lower, upper, current)``: منطق تحقّق خالص (سفلي < الحالي <
    علوي؛ تحذير ``inverted`` لو ``lower >= upper``).
  - ``BracketMonitor``: مُراقِب خفيف يفحص كل tick؛ عند لمس/تجاوز الحدّ العلوي لأعلى
    أو السفلي لأسفل يستدعي **مُنفّذ خروج محقون** (DI) **مرّة واحدة فقط** (latch) —
    تنسيق خروج-واحد مع الحارس (بعد الخروج الرصيد صفر ⇒ الحارس NOOP بنيويًّا).

لا تمسّ هذه الوحدة المسار الحار (on_price_tick / MonitoringEngine.start /
SafeExecutor.execute / reposition / create_oco) ولا تستورده؛ المُنفّذ محقون فتبقى
قابلة للاختبار بالكامل بلا أيّ شبكة فعلية.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional

from ocobot.domain.market_exit import EXIT_LOWER, EXIT_UPPER


def _dec_or_none(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if s == "":
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


# G1.33: حدّ أقصى محارَس لأرضية الفلاش-كراش (٪) — لا نسمح بتعطيل الحماية بقيمة عبثية.
FLOOR_MAX_PCT = Decimal("50")

# G1.49: افتراض wick-debounce — عدد التِكّات المتتالية على الجهة نفسها قبل الإطلاق
#        (يمنع لمس القوس الكاذب على شمعة/wick لحظية). قابل للضبط من الواجهة (chunk_5).
DEFAULT_DEBOUNCE_TICKS = 2


def _int_or_none(value):
    v = _dec_or_none(value)
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


@dataclass
class BracketConfig:
    """إعداد القوس الحيّ المقروء من الواجهة.

    الحدّان (``lower``/``upper``) أسعار. نِسب التسعير (G1.33) اختيارية: ``None`` ⇒
    تُستعمل افتراضيات ``plan_market_exit`` القديمة (slip=0.1، emergency_sl=1،
    price_floor=8، gap=1) فلا ينكسر أيّ سلوك قائم.
    """

    enabled: bool = False
    lower: Optional[Decimal] = None
    upper: Optional[Decimal] = None
    slip_pct: Optional[Decimal] = None       # G1.33: انزلاق الخروج العلوي (LIMIT)
    sl_pct: Optional[Decimal] = None         # G1.33: زناد الخروج السفلي (STOP_LOSS_LIMIT)
    floor_pct: Optional[Decimal] = None      # G1.33: أرضية الفلاش-كراش (محارَسة بسقف)
    gap_ticks: Optional[int] = None          # G1.33: فجوة التك بين الزناد والحدّ

    @classmethod
    def from_inputs(cls, enabled, lower, upper, slip_pct=None, sl_pct=None,
                    floor_pct=None, gap_ticks=None) -> "BracketConfig":
        return cls(
            enabled=bool(enabled),
            lower=_dec_or_none(lower),
            upper=_dec_or_none(upper),
            slip_pct=_dec_or_none(slip_pct),
            sl_pct=_dec_or_none(sl_pct),
            floor_pct=_dec_or_none(floor_pct),
            gap_ticks=_int_or_none(gap_ticks),
        )

    def pricing_kwargs(self) -> Dict[str, Any]:
        """معاملات التسعير **المضبوطة فقط** لتمريرها إلى ``execute_market_exit``.

        الفارغ/غير الصالح/السالب يُحذف ⇒ تُستعمل الافتراضيات القديمة. أرضية
        الفلاش-كراش تُقَصّ على ``FLOOR_MAX_PCT`` (سقف محارَس لا يُعطّل الحماية).
        """
        out: Dict[str, Any] = {}
        if self.slip_pct is not None and self.slip_pct > 0:
            out["slip_pct"] = self.slip_pct
        if self.sl_pct is not None and self.sl_pct > 0:
            out["emergency_sl_pct"] = self.sl_pct
        if self.floor_pct is not None and self.floor_pct > 0:
            out["price_floor_pct"] = min(self.floor_pct, FLOOR_MAX_PCT)
        if self.gap_ticks is not None and self.gap_ticks >= 1:
            out["gap_ticks"] = self.gap_ticks
        return out


def validate_bracket(lower, upper, current=None) -> Dict[str, Any]:
    """تحقّق خالص من حدّي القوس. يُعيد ``valid``/``inverted``/``in_range``/``reason``."""
    lo = _dec_or_none(lower)
    up = _dec_or_none(upper)
    cur = _dec_or_none(current)
    res: Dict[str, Any] = {
        "valid": False, "inverted": False, "in_range": None,
        "reason": None, "lower": lo, "upper": up,
    }
    if lo is None and up is None:
        res["reason"] = "no_bounds"
        return res
    if lo is not None and up is not None and lo >= up:
        res["inverted"] = True
        res["reason"] = "inverted_bounds"
        return res
    res["valid"] = True
    if cur is not None and lo is not None and up is not None:
        res["in_range"] = bool(lo < cur < up)
        if not res["in_range"]:
            res["reason"] = "current_outside_bounds"
    return res


class BracketMonitor:
    """مُراقِب قوس خفيف، خروج-واحد (latch). لا شبكة؛ مُنفّذ الخروج محقون (DI).

    - ``exit_executor(exit_side, price) -> dict``: يُنفّذ الخروج ويعيد نتيجة.
    - ``config_getter() -> BracketConfig``: يقرأ إعداد القوس الحيّ من الواجهة.
    - ``on_event(exit_side, price, result)`` (اختياري): للتنبيه/التسجيل.

    الـ latch يُضبط **قبل** استدعاء المُنفّذ فيُمنع أيّ إطلاق ثانٍ (خروج-واحد).
    """

    def __init__(self, *, exit_executor: Callable, config_getter: Callable,
                 on_event: Optional[Callable] = None,
                 bid_getter: Optional[Callable] = None,
                 debounce_ticks: int = DEFAULT_DEBOUNCE_TICKS,
                 debounce_ms: Optional[Any] = None,
                 clock: Optional[Callable] = None):
        self._exit = exit_executor
        self._config_getter = config_getter
        self._on_event = on_event
        # G1.49: ترسية الخروج على أفضل BID حيّ لحظة الإطلاق (لا على tick قديم/wick).
        self._bid_getter = bid_getter
        # G1.49: wick-debounce — اشتراط ثبات الاختراق قبل الإطلاق: تِكّتان متتاليتان
        #        على الجهة نفسها (افتراضيًّا) أو نافذة زمنية ``debounce_ms`` عند توفّر
        #        ``clock`` ⇒ لمسة wick لحظية منفردة لا تُطلق خروجًا كاذبًا.
        self._debounce_ticks = int(debounce_ticks) if debounce_ticks else 1
        self._debounce_ms = _dec_or_none(debounce_ms)
        self._clock = clock
        self._fired = False
        self.last_result = None
        self._pending_side = None
        self._pending_count = 0
        self._pending_since = None

    @property
    def fired(self) -> bool:
        return self._fired

    def reset(self) -> None:
        self._fired = False
        self.last_result = None
        self._clear_pending()

    def _clear_pending(self) -> None:
        """صفّر عدّاد ثبات الاختراق (يُستدعى عند العودة داخل القوس أو بعد الإطلاق)."""
        self._pending_side = None
        self._pending_count = 0
        self._pending_since = None

    def _breach_confirmed(self) -> bool:
        """هل ثبت الاختراق كفايةً للإطلاق؟ (تِكّات متتالية «أو» نافذة زمنية)."""
        if self._debounce_ticks <= 1:
            return True
        if self._pending_count >= self._debounce_ticks:
            return True
        # نافذة زمنية اختيارية (debounce_ms) عند توفّر clock — «أو» مع عدّ التِكّات.
        if (self._debounce_ms is not None and self._clock is not None
                and self._pending_since is not None and self._pending_count >= 1):
            try:
                elapsed_ms = (float(self._clock()) - float(self._pending_since)) * 1000.0
            except Exception:  # pragma: no cover - دفاعي
                return False
            if elapsed_ms >= float(self._debounce_ms):
                return True
        return False

    def check(self, price) -> Dict[str, Any]:
        if self._fired:
            return {"action": "ALREADY_FIRED"}
        cfg = self._config_getter() if self._config_getter else None
        if cfg is None or not getattr(cfg, "enabled", False):
            self._clear_pending()
            return {"action": "DISABLED"}
        p = _dec_or_none(price)
        if p is None:
            return {"action": "NO_PRICE"}
        lo = getattr(cfg, "lower", None)
        up = getattr(cfg, "upper", None)
        exit_side = None
        if up is not None and p >= up:
            exit_side = EXIT_UPPER
        elif lo is not None and p <= lo:
            exit_side = EXIT_LOWER
        if exit_side is None:
            # عاد السعر داخل القوس ⇒ أيّ اختراق سابق كان wick ⇒ صفّر عدّاد الثبات.
            self._clear_pending()
            return {"action": "WITHIN_BRACKET", "price": p}
        # اختراق حدّ: راكِم ثبات الاختراق على الجهة نفسها (wick-debounce).
        if exit_side != self._pending_side:
            self._pending_side = exit_side
            self._pending_count = 1
            self._pending_since = None
            if self._clock is not None:
                try:
                    self._pending_since = self._clock()
                except Exception:  # pragma: no cover - دفاعي
                    self._pending_since = None
        else:
            self._pending_count += 1
        if not self._breach_confirmed():
            # اختراق غير مُثبَت بعد ⇒ «مُسلَّح» بلا إطلاق (ينتظر تأكيدًا أو يرتدّ).
            return {"action": "ARMED", "exit_side": exit_side,
                    "price": p, "count": self._pending_count}
        # ثبت الاختراق ⇒ خروج واحد. ارسِ المرجع على أفضل BID حيّ لحظة الإطلاق
        # (لا على tick قديم/wick)، واضبط الـ latch قبل الاستدعاء (منع تكرار).
        ref = p
        if self._bid_getter is not None:
            try:
                live = _dec_or_none(self._bid_getter())
            except Exception:  # pragma: no cover - دفاعي
                live = None
            if live is not None:
                ref = live
        self._fired = True
        self._clear_pending()
        result = self._exit(exit_side, ref)
        self.last_result = result
        if self._on_event is not None:
            try:
                self._on_event(exit_side, ref, result)
            except Exception:  # pragma: no cover - دفاعي
                pass
        return {"action": "EXIT_TRIGGERED", "exit_side": exit_side,
                "price": ref, "trigger_price": p, "result": result}
