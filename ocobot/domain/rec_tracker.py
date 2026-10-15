"""وحدة تحكّم الوضع المتتبّع لمُرشِّح النِّسب (G1.56 · c7).

وحدة domain خالصة (بلا Qt، بلا شبكة): تحكم متى يُعتمَد اقتراح جديد من
recommender بثلاثة أوضاع + ضوابط ضدّ «مطاردة» النسب:
  - **Off**: يتجاهل كل الاقتراحات.
  - **Observe** (الافتراضي): يحسب/يعرض فقط، لا يعتمد أي تغيير (صفر مخاطر).
  - **Live**: يعتمد الاقتراح بشروط: hysteresis (أدنى تغيّر مُعتبَر)،
    تهدئة زمنية بين الاعتمادات، وسقف عدد تغييرات لكل جلسة.

«الاعتماد» هنا يعني إنتاج اقتراح مُوافَق عليه + قيد تدقيق؛ لا تلمس هذه الوحدة
الـhot_path ولا دورة التموضع (ذلك خارج نطاق G1.56): التأثير الفعلي — إن وُصِّل
لاحقًا — يكون في **دورة التموضع التالية فقط**، لا على الأمر القائم لحظيًا.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, List, Optional

MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_LIVE = "live"
_MODES = (MODE_OFF, MODE_OBSERVE, MODE_LIVE)


@dataclass
class TrackerParams:
    min_delta_pct: float = 0.2          # hysteresis: أدنى تغيّر مطلق في أي نسبة
    cooldown_s: float = 60.0            # أدنى زمن بين اعتمادين (Live)
    max_changes_per_session: int = 20   # سقف الاعتمادات في الجلسة


@dataclass
class TrackerDecision:
    applied: bool
    mode: str
    reason: str          # first|applied|observe|off|cooldown|hysteresis|session_cap
    recommendation: Optional[object]


def _f(d) -> float:
    if d is None:
        return 0.0
    return float(d) if not isinstance(d, Decimal) else float(d)


def max_delta_pct(a, b) -> float:
    """أكبر فرق مطلق بين نسبتَي اقتراحين (tp/sl/trigger)."""
    if a is None or b is None:
        return float("inf")
    return max(
        abs(_f(a.tp_pct) - _f(b.tp_pct)),
        abs(_f(a.sl_pct) - _f(b.sl_pct)),
        abs(_f(a.trigger_pct) - _f(b.trigger_pct)),
    )


class RecommendationTracker:
    def __init__(self, mode: str = MODE_OBSERVE,
                 params: Optional[TrackerParams] = None,
                 clock: Optional[Callable[[], float]] = None,
                 audit: Optional[Callable[[dict], None]] = None):
        self._p = params or TrackerParams()
        self._clock = clock or time.monotonic
        self._audit_cb = audit
        self._last_applied = None
        self._last_applied_ts: Optional[float] = None
        self._last_observed = None
        self._changes = 0
        self.audit_log: List[dict] = []
        if mode not in _MODES:
            raise ValueError(f"وضع متتبّع غير مدعوم: {mode}")
        self._mode = mode  # القيمة الابتدائية بلا تدقيق (التدقيق للتغييرات اللاحقة)

    # ---- mode ----
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in _MODES:
            raise ValueError(f"وضع متتبّع غير مدعوم: {mode}")
        changed = getattr(self, "_mode", None) != mode
        self._mode = mode
        if changed:
            self._emit_audit({"event": "mode_change", "mode": mode,
                              "ts": self._clock()})

    @property
    def changes_count(self) -> int:
        return self._changes

    @property
    def last_applied(self):
        return self._last_applied

    @property
    def last_observed(self):
        return self._last_observed

    def reset_session(self) -> None:
        self._changes = 0
        self._last_applied = None
        self._last_applied_ts = None

    # ---- core ----
    def offer(self, rec, now: Optional[float] = None) -> TrackerDecision:
        """يقدّم اقتراحًا جديدًا؛ يُعيد قرارًا هل يُعتمَد (Live) أم لا."""
        now = self._clock() if now is None else now

        if self._mode == MODE_OFF:
            return self._decide(False, "off", rec, now)

        if self._mode == MODE_OBSERVE:
            self._last_observed = rec
            return self._decide(False, "observe", rec, now)

        # Live
        if rec is None:
            return self._decide(False, "off", rec, now)
        if self._last_applied is None:
            return self._apply(rec, now, "first")
        if self._last_applied_ts is not None and \
                (now - self._last_applied_ts) < self._p.cooldown_s:
            return self._decide(False, "cooldown", rec, now)
        if max_delta_pct(rec, self._last_applied) < self._p.min_delta_pct:
            return self._decide(False, "hysteresis", rec, now)
        if self._changes >= self._p.max_changes_per_session:
            return self._decide(False, "session_cap", rec, now)
        return self._apply(rec, now, "applied")

    # ---- helpers ----
    def _apply(self, rec, now, reason) -> TrackerDecision:
        self._last_applied = rec
        self._last_applied_ts = now
        self._changes += 1
        dec = TrackerDecision(True, self._mode, reason, rec)
        self._emit_audit(self._audit_record(dec, now))
        return dec

    def _decide(self, applied, reason, rec, now) -> TrackerDecision:
        dec = TrackerDecision(applied, self._mode, reason, rec)
        if reason in ("observe",) or applied:
            self._emit_audit(self._audit_record(dec, now))
        return dec

    def _audit_record(self, dec: TrackerDecision, now) -> dict:
        rec = dec.recommendation
        return {
            "event": "tracker_offer",
            "mode": dec.mode,
            "reason": dec.reason,
            "applied": dec.applied,
            "ts": now,
            "changes": self._changes,
            "tpPct": None if rec is None else str(rec.tp_pct),
            "slPct": None if rec is None else str(rec.sl_pct),
            "triggerPct": None if rec is None else str(rec.trigger_pct),
        }

    def _emit_audit(self, record: dict) -> None:
        self.audit_log.append(record)
        if callable(self._audit_cb):
            try:
                self._audit_cb(record)
            except Exception:
                pass
