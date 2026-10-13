# -*- coding: utf-8 -*-
"""مُنسّق حارس هبوط BTC (BTC-follow supervisor) — G1.44 / chunk_2.

وحدة **إضافية بحتة** وخارج المسار الحار:
  - تحتفظ بمخزَن حلقي محدود لعيّنات سعر BTC (ring buffer) تُغذّى من تغذية BTC
    معزولة (WS ثانٍ) عبر ``ingest(price, ts)`` — لا شبكة داخل هذه الوحدة.
  - ``tick(now)`` يستدعي ``btc_follow.evaluate`` الخالصة على نافذة العيّنات،
    ويحدّث الحالة الداخلية، ويعيد ``BtcFollowDecision``.
  - fail-safe: فقد التغذية (لا عيّنات حديثة/استثناء السحب) ⇒ المنطق الخالص يُعيد
    NOOP؛ ولا ترمي هذه الوحدة أبدًا.
  - الحارس مُعطّل افتراضيًّا (``cfg.enabled=False``) ⇒ NOOP دائمًا.

BTC مُدخَل خارجي للقراءة فقط؛ **لا يُوضع أمر هنا** (مسار التنفيذ في chunk_3).

قاعدة التحكيم (``should_btc_tighten``) خالصة أيضًا: تضمن ألّا يتعارض حارس BTC
مع (شبكة أمان المركز) و(قوس الخروج)، وأن تبقى الأولوية القصوى لشبكة الأمان.
"""
from __future__ import annotations

import time as _time
from decimal import Decimal
from typing import Callable, List, Optional

from ocobot.domain.btc_follow import (
    BtcFollowAction,
    BtcFollowConfig,
    BtcFollowDecision,
    BtcFollowState,
    BtcSample,
    evaluate,
)

_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    if value is None:
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


class BtcFollowSupervisor:
    """مُنسّق دوري بحقن تبعيات؛ يجمّع عيّنات BTC ويشغّل المنطق الخالص.

    التبعيات (كلّها محقونة):
      - ``config``: ``BtcFollowConfig`` (الافتراضي OFF).
      - ``time_fn``: مصدر الزمن (الافتراضي ``time.monotonic``) لتقليم النافذة.
      - ``price_fn``: اختياري ``Callable[[], object]`` لسحب سعر BTC الحالي من
        تغذية معزولة؛ إن أُعطي استُعمل في ``poll(now)``. محروس: أي استثناء ⇒
        تجاهل العيّنة (fail-safe).
      - ``max_samples``: حدّ أعلى لحجم المخزَن الحلقي (حماية الذاكرة/الأداء).
    """

    def __init__(
        self,
        *,
        config: Optional[BtcFollowConfig] = None,
        time_fn: Optional[Callable[[], float]] = None,
        price_fn: Optional[Callable[[], object]] = None,
        max_samples: int = 512,
    ):
        self._config = config or BtcFollowConfig()
        self._time_fn = time_fn or _time.monotonic
        self._price_fn = price_fn
        self._max_samples = max(8, int(max_samples))
        self._samples: List[BtcSample] = []
        self._state = BtcFollowState()
        self.last_decision: Optional[BtcFollowDecision] = None

    @property
    def config(self) -> BtcFollowConfig:
        return self._config

    def set_config(self, config: Optional[BtcFollowConfig]) -> None:
        self._config = config or BtcFollowConfig()

    @property
    def state(self) -> BtcFollowState:
        return self._state

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def ingest(self, price, ts: Optional[float] = None) -> None:
        """يضيف عيّنة سعر BTC إلى المخزَن الحلقي (محروس؛ لا يرمي)."""
        try:
            p = _dec(price)
        except Exception:
            return
        if p <= _ZERO:
            return
        t = float(ts) if ts is not None else float(self._time_fn())
        self._samples.append(BtcSample(ts=t, price=p))
        self._prune(t)

    def poll(self, now: Optional[float] = None) -> None:
        """يسحب سعرًا من ``price_fn`` (إن وُجد) ويضيفه. محروس (fail-safe)."""
        if self._price_fn is None:
            return
        try:
            price = self._price_fn()
        except Exception:
            return  # فقد التغذية ⇒ تجاهل؛ المنطق سيُعيد NOOP لاحقًا
        if price is None:
            return
        self.ingest(price, now)

    def _prune(self, now: float) -> None:
        # أبقِ ما يقع ضمن أفق واسع (ضعف النافذة + التأكيد + هامش) + حدّ أعلى للعدد.
        horizon = now - (
            2.0 * float(self._config.window_seconds)
            + float(self._config.confirm_seconds)
            + 1.0
        )
        if self._samples and self._samples[0].ts < horizon:
            self._samples = [s for s in self._samples if s.ts >= horizon]
        if len(self._samples) > self._max_samples:
            self._samples = self._samples[-self._max_samples:]

    def price_snapshot(self, now=None, window_seconds=None):
        """Read-only display snapshot: (last_price, prev_price, window_start_price) as Decimals or None. Never raises."""
        try:
            if not self._samples:
                return (None, None, None)
            if window_seconds is None:
                window_seconds = float(self._config.window_seconds)
            else:
                window_seconds = float(window_seconds)
            if now is None:
                now = float(self._time_fn())
            else:
                now = float(now)
            last = self._samples[-1].price
            prev = self._samples[-2].price if len(self._samples) >= 2 else None
            lo = now - window_seconds
            window_start = None
            for s in self._samples:
                if s.ts >= lo:
                    window_start = s.price
                    break
            if window_start is None:
                window_start = self._samples[0].price
            return (last, prev, window_start)
        except Exception:
            return (None, None, None)

    def tick(self, now: Optional[float] = None) -> BtcFollowDecision:
        """دورة تقييم واحدة؛ تُعيد قرار الحارس وتحدّث الحالة الداخلية."""
        t = float(now) if now is not None else float(self._time_fn())
        decision = evaluate(tuple(self._samples), self._config, self._state, t)
        self._state = decision.state
        self.last_decision = decision
        return decision

    def reset(self) -> None:
        self._samples = []
        self._state = BtcFollowState()
        self.last_decision = None


def should_btc_tighten(
    btc_decision: BtcFollowDecision,
    *,
    has_resting_protective_sell: bool,
    free_qty,
    monitored_qty,
    guardian_intervening: bool,
) -> bool:
    """قاعدة التحكيم الخالصة: هل يتصرّف حارس BTC الآن؟ (لا أثر جانبي).

    الأولوية القصوى لشبكة أمان المركز: إن كان الحارس الأساسي متدخّلًا
    (``guardian_intervening``) ⇒ لا يتصرّف حارس BTC (منع تعارض/بيع مزدوج).
    وإلا يتصرّف **فقط** عند ``TIGHTEN`` المؤكّد ووجود كمية قابلة للحماية > 0.
    القيد البنيوي النهائي (منع البيع المزدوج) يبقى في مسار التنفيذ (chunk_3):
    ``has_resting_protective_sell`` يُستعمل هناك لاختيار tighten (cancel-replace)
    عبر مسار الخروج المُختبَر بدل إضافة أمر ثانٍ.
    """
    if guardian_intervening:
        return False
    if btc_decision.action is not BtcFollowAction.TIGHTEN:
        return False
    return min(_dec(free_qty), _dec(monitored_qty)) > _ZERO
