"""مُشرِف شبكة أمان المركز (Guardian Supervisor) — G1.30 / chunk_3.

هذه الوحدة **إضافية بحتة** وخارج المسار الحار:
  - لا تمسّ ولا تعدّل ``on_price_tick`` / ``MonitoringEngine.start`` /
    ``SafeExecutor.execute`` / ``create_oco`` / أي منطق تسعير/تموضع، ولا أي
    رسالة/قيمة عربية مختومة. تقرأ الحالة فقط وتستدعي دوال موجودة.
  - بحقن تبعيات كامل ⇒ قابلة للاختبار بلا شبكة ولا Qt.

ما يفعله ``tick()`` (دوريًّا، خارج خيط الواجهة عبر الربط الإضافي):
  1. يقرأ ``MonitoringState`` الحالية (symbol, state, in_flight) عبر مزوّد الحالة
     (دالة تُرجع الـstate أو مرجع ``MonitoringEngine`` نقرأ منه ``engine.state``).
  2. يتعقّب ``naked_seconds`` داخليًّا: يسجّل لحظة أول اكتشاف للعُري (لا بيع حمائي
     قائم + كمية حرّة > 0)، ويعيد الضبط عند زوال العُري أو عند الحماية/التسليح.
  3. يبني ``GuardianSnapshot`` بقراءة ``has_resting_protective_sell`` و
     ``free_base_qty`` من العميل، و ``monitored_qty`` من الـstate/selected_oco،
     ثم يستدعي ``guardian.evaluate``.
  4. عند ``INTERVENE``: يستدعي ``place_protective_stop(dry_run=self.dry_run)`` ثم
     يوقف المراقبة عبر ``engine.kill_switch()`` (الموجودة) ثم يطلق ``alert_cb``.
     **Idempotent**: بعد التدخّل/التسليح لا يتدخّل ثانيةً لنفس العُري (علامة
     ``_armed``) حتى يزول العُري ويعاد ضبط التعقّب.
  5. عند ``WAIT``/``NOOP``: لا يفعل شيئًا.

يقتصر حصريًّا على ``symbol`` النشط في ``MonitoringState``. لا تسليم عكسي
(handoff) — مؤجّل في v1. الوضع الافتراضي آمن (``dry_run=True``) حتى تسليح
نقطة التفتيش البشرية (chunk_5).
"""
from __future__ import annotations

import time as _time
from decimal import Decimal
from typing import Any, Callable, Optional
from uuid import uuid4

from ocobot.domain.guardian import (
    GuardianAction,
    GuardianConfig,
    GuardianDecision,
    GuardianSnapshot,
    evaluate,
)
from ocobot.domain.guardian_exec import ProtectiveStopClient, place_protective_stop
from ocobot.domain.btc_follow import BtcFollowAction
from ocobot.domain.btc_follow_supervisor import should_btc_tighten

_ZERO = Decimal("0")

# الحالات التي يكون المُشرِف فيها فعّالًا (مراقبة نشطة فعلًا). خارجها لا يتدخّل.
# نستعمل القيم النصّية حتى لا نعتمد على MonitoringStateEnum في المنطق الخالص.
_ACTIVE_STATES = {
    "MONITORING_ACTIVE",
    "TRIGGERED",
    "REPOSITIONING",
    "FAILED_NEEDS_ATTENTION",
}


def _dec(value) -> Decimal:
    if value is None:
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _default_guardian_cid() -> str:
    # <=36 حرفًا (Binance-safe) على نمط reposition._default_id_factory
    return f"grd-{uuid4().hex[:20]}"


class GuardianSupervisor:
    """مُشرِف دوري بحقن تبعيات؛ يقرأ الحالة ويشعل الحارس عند العُري الممتدّ.

    التبعيات (كلّها محقونة):
      - ``state_provider``: callable يُرجع ``MonitoringState`` الحالية، **أو** مرجع
        ``MonitoringEngine`` (نقرأ منه ``engine.state`` و ``engine.selected_oco``
        و ``engine.kill_switch()`` فقط — قراءة + دوال موجودة).
      - ``client``: ``ProtectiveStopClient`` (المحوّل) لقراءة الأوامر/الرصيد ووضع
        وقف واحد. لا إلغاء إطلاقًا.
      - ``alert_cb``: ``Callable[[str], None]`` لإطلاق تنبيه بشري.
      - ``time_fn``: ``Callable[[], float]`` لقياس ``naked_seconds`` (قابل للحقن
        في الاختبارات؛ الافتراضي ``time.monotonic``).
      - ``config``: ``GuardianConfig`` (العتبة + نسبة الوقف الطارئ).
      - ``dry_run``: افتراضيًّا ``True`` (آمن). الوضع الحيّ يُسلَّح في chunk_5.
      - ``base_asset_fn``: ``Callable[[str], Optional[str]]`` لاستنتاج الأصل
        الأساسي من الرمز (للرصيد الحرّ). إن أعاد ``None`` ⇒ لا كمية حرّة ⇒ NOOP آمن.
      - ``engine``: مرجع ``MonitoringEngine`` اختياري لإيقاف المراقبة؛ إن غاب
        واستُنتج من ``state_provider`` كمحرّك استُعمل ذلك.
    """

    def __init__(
        self,
        *,
        state_provider: Callable[[], Any],
        client: ProtectiveStopClient,
        alert_cb: Callable[[str], None],
        time_fn: Optional[Callable[[], float]] = None,
        config: Optional[GuardianConfig] = None,
        dry_run: bool = True,
        base_asset_fn: Optional[Callable[[str], Optional[str]]] = None,
        engine: Any = None,
        reference_price_fn: Optional[Callable[[Any], Any]] = None,
        filters_fn: Optional[Callable[[str], Any]] = None,
        cid_factory: Optional[Callable[[], str]] = None,
        notifier: Optional[Callable[[dict], None]] = None,
        btc_follow: Any = None,
        btc_exit_fn: Optional[Callable[..., Any]] = None,
        btc_alert_cb: Optional[Callable[[str], None]] = None,
        btc_notifier: Optional[Callable[[dict], None]] = None,
        stop_limit_offset_pct=None,
        price_floor_pct=None,
        exit_source_sink=None,
    ):
        self._state_provider = state_provider
        self._client = client
        self._alert_cb = alert_cb
        # G1.37 (emit-only): مُطلِق تنبيه ثريّ على التدخّل الفعلي (PLACED) فقط.
        #        callable يُنتَج عبر make_guardian_notifier؛ محروس ولا يرمي أبدًا.
        self._notifier = notifier
        self._time_fn = time_fn or _time.monotonic
        self._config = config or GuardianConfig()
        self.dry_run = bool(dry_run)
        self._base_asset_fn = base_asset_fn
        self._engine = engine
        self._reference_price_fn = reference_price_fn
        self._filters_fn = filters_fn
        self._cid_factory = cid_factory or _default_guardian_cid
        # G1.49: إزاحة/أرضية STOP_LOSS_LIMIT للحارس (وتُطبَّق أيضًا على مسار شبكة الأمان المشترك). None ⇒ سلوك قديم.
        self._stop_limit_offset_pct = stop_limit_offset_pct
        self._price_floor_pct = price_floor_pct
        # G1.52: مُسجِّل مصدر الخروج (opt-in) — يكتب exit_source في سجل التدقيق
        # لحظة التدخّل، فيلتقطه نموذج الصفقات المنتهية. default None ⇒ لا أثر.
        self._exit_source_sink = exit_source_sink

        # G1.44: BTC-follow guard (optional, additive, OFF by default).
        self._btc_follow = btc_follow
        self._btc_exit_fn = btc_exit_fn
        self._btc_alert_cb = btc_alert_cb
        # G1.57 (emit-only): مُطلِق تنبيه Telegram ثريّ لحارس هبوط BTC على التدخّل
        #        الفعلي (PLACED) فقط — مرآة لخطّاف self._notifier؛ محروس ولا يرمي.
        self._btc_notifier = btc_notifier
        self._btc_armed = False
        self.last_btc_decision = None
        self.last_btc_result = None

        # G1.44 / chunk_4: بوّابات تشغيل مستقلّة (إضافية، متوافقة خلفيًّا).
        #   - ``_btc_enabled`` (الافتراضي True) ⇒ عند False يصبح حارس BTC NOOP تامًّا.
        #   - ``_btc_dry_run`` (الافتراضي None) ⇒ تجاوز اختياري لوضع التنفيذ الحيّ
        #     لحارس BTC بمعزل عن ``self.dry_run`` العامّ؛ None ⇒ اتبع ``self.dry_run``.
        #   - ``_guardian_enabled`` (الافتراضي True) ⇒ عند False نحسب قرار/لقطة
        #     شبكة الأمان (ليبقى التحكيم ``guardian_intervening`` صحيحًا لأولوية BTC)
        #     لكن نتخطّى التدخّل الفعلي (place_protective_stop/kill).
        # الافتراضيات تُبقي سلوك chunk_3 وG1.30/G1.31 دون تغيير.
        self._btc_enabled = True
        self._btc_dry_run = None
        self._guardian_enabled = True

        # حالة التعقّب الداخلية (لا تمسّ أي حالة في المحرّك):
        self._naked_since: Optional[float] = None  # لحظة أول اكتشاف للعُري
        self._armed = False  # هل سُلّح/تدخّل الحارس لهذا العُري؟ (idempotent)
        self.last_decision: Optional[GuardianDecision] = None
        self.last_result: Optional[dict] = None

    # ---- helpers (قراءة فقط) ----------------------------------------------
    def _resolve_state(self):
        """يحسم ``MonitoringState`` من المزوّد (state مباشرة أو عبر engine.state)."""
        provided = self._state_provider() if callable(self._state_provider) else self._state_provider
        if provided is None:
            return None, None
        # إن كان كائن محرّك (له .state) فاقرأ منه
        state = getattr(provided, "state", None)
        if state is not None and hasattr(state, "symbol"):
            engine = provided
            return state, engine
        # وإلا فالمزوّد أعاد MonitoringState نفسها
        return provided, (self._engine)

    def _monitored_qty(self, state, engine) -> Decimal:
        """الكمية المُراقَبة = كمية الـ selected_oco المقفولة (D7) إن توفّرت."""
        selected = None
        if engine is not None:
            selected = getattr(engine, "selected_oco", None)
        if selected is None:
            selected = getattr(state, "selected_oco", None)
        qty = getattr(selected, "quantity", None)
        return _dec(qty)

    def _reference_price(self, state):
        if self._reference_price_fn is not None:
            try:
                return self._reference_price_fn(state)
            except Exception:
                return None
        # آخر سعر صالح يُفضَّل، وإلا السعر المرجعي (D14 — لا اختلاق).
        last = getattr(state, "last_price", None)
        if last is not None:
            return last
        return getattr(state, "reference_price", None)

    def _reset_tracking(self):
        self._naked_since = None
        self._armed = False
        # G1.44 / chunk_4: زوال المراقبة النشطة يعيد ضبط تسليح حارس BTC أيضًا.
        self._btc_armed = False

    # ---- الدورة الرئيسة -----------------------------------------------------
    def tick(self) -> Optional[GuardianDecision]:
        """دورة إشراف واحدة. تُعيد القرار (أو ``None`` إن لم تكن المراقبة نشطة).

        لا ترمي أبدًا سلوكًا كاسرًا للمسار الحار؛ أي نقص تبعية ⇒ قرار NOOP آمن.
        """
        state, engine = self._resolve_state()
        if state is None:
            self._naked_since = None
            self._armed = False
            return None

        enabled = bool(getattr(state, "enabled", False))
        state_name = str(getattr(getattr(state, "state", None), "value", getattr(state, "state", "")))
        symbol = getattr(state, "symbol", "") or ""

        # فعّال فقط أثناء المراقبة النشطة لعملة محدّدة؛ خلاف ذلك خامل وآمن.
        if not symbol or not enabled or state_name not in _ACTIVE_STATES:
            self._naked_since = None
            self._armed = False
            return None

        in_flight = bool(getattr(state, "in_flight", False))

        # قراءة الحماية القائمة + الرصيد الحرّ عبر العميل (محوّل الوساطة).
        has_resting = bool(self._client.get_open_sell_orders(symbol))

        base_asset = self._base_asset_fn(symbol) if self._base_asset_fn else None
        free_qty = _ZERO
        if base_asset:
            try:
                free_qty = _dec(self._client.get_free_asset_qty(base_asset))
            except Exception:
                free_qty = _ZERO

        monitored_qty = self._monitored_qty(state, engine)

        # تعقّب naked_seconds: العُري = لا بيع حمائي قائم + كمية حرّة قابلة للحماية.
        now = float(self._time_fn())
        is_naked = (not has_resting) and (min(free_qty, monitored_qty) > _ZERO)
        if not is_naked:
            # زال العُري (أو أصبح محميًّا) ⇒ أعد ضبط تعقّب شبكة الأمان وتسليحها.
            # ملاحظة: لا نلمس تسليح حارس BTC هنا؛ فحارس BTC قد يتصرّف حتى عند
            # وجود بيع حمائي قائم (تضييق عبر مسار الخروج) ويُدار تسليحه داخليًّا.
            self._naked_since = None
            self._armed = False
            naked_seconds = 0.0
        else:
            if self._naked_since is None:
                self._naked_since = now
            naked_seconds = max(0.0, now - self._naked_since)

        snap = GuardianSnapshot(
            symbol=symbol,
            state=state_name,
            in_flight=in_flight,
            naked_seconds=naked_seconds,
            has_resting_protective_sell=has_resting,
            free_base_qty=free_qty,
            monitored_qty=monitored_qty,
        )
        decision = evaluate(snap, self._config)
        self.last_decision = decision

        guardian_intervening = False
        if decision.action is GuardianAction.INTERVENE:
            # G1.44 / chunk_4: شبكة الأمان قد تكون مُعطّلة مستقلًّا؛ عندها نحسب
            # القرار (تمّ أعلاه) لكن نتخطّى التدخّل الفعلي. مع ذلك يبقى التحكيم
            # ``guardian_intervening`` صحيحًا لأولوية BTC (تُكبح BTC إن تدخّلت
            # شبكة الأمان منطقيًّا)، حفاظًا على test_guardian_priority_blocks_btc.
            guardian_intervening = True
            if self._guardian_enabled:
                # Idempotent: لا تتدخّل مرّتين لنفس العُري.
                if self._armed:
                    return decision
                self._intervene(symbol, base_asset, state, engine, decision)
                self._armed = True
                return decision

        # G1.44: BTC-follow guard (additive, guarded).
        if self._btc_follow is not None:
            try:
                self._btc_tick(symbol, base_asset, state, engine, decision,
                               has_resting, free_qty, monitored_qty, now,
                               guardian_intervening)
            except Exception:
                pass
        return decision

    def _intervene(self, symbol, base_asset, state, engine, decision: GuardianDecision):
        """تنفيذ التدخّل: وضع وقف حمائي واحد ⇒ إيقاف المراقبة ⇒ تنبيه."""
        reference_price = self._reference_price(state)
        filters = self._filters_fn(symbol) if self._filters_fn else getattr(state, "filters", None)
        if filters is None:
            filters = getattr(getattr(engine, "selected_oco", None), "filters", None)

        result = None
        try:
            result = place_protective_stop(
                self._client,
                symbol=symbol,
                base_asset=base_asset or "",
                reference_price=reference_price,
                qty=decision.protective_qty,
                emergency_sl_pct=self._config.emergency_sl_pct,
                filters=filters,
                client_order_id=self._cid_factory(),
                stop_limit_offset_pct=self._stop_limit_offset_pct,
                price_floor_pct=self._price_floor_pct,
                dry_run=self.dry_run,
            )
        except Exception as exc:  # لا نكسر دورة الإشراف أبدًا
            result = {"action": "ERROR", "placed": False, "error": str(exc)}
        self.last_result = result

        # إيقاف المراقبة بأمان عبر الدالة الموجودة (لا إلغاء لأي أمر على Binance).
        stop_engine = engine if engine is not None else self._engine
        # G1.46: وسم مصدر الخروج (شبكة أمان المركز) قبل الإيقاف — إضافة بحتة لا تمسّ المنطق.
        if stop_engine is not None and hasattr(stop_engine, "note_exit_source"):
            try:
                stop_engine.note_exit_source("POSITION_SAFETY_NET")
            except Exception:
                pass
        # G1.52: جَسر مصدر الخروج إلى سجل التدقيق (opt-in) ليُنسب في نموذج الصفقات المنتهية.
        if self._exit_source_sink is not None:
            try:
                self._exit_source_sink("POSITION_SAFETY_NET")
            except Exception:
                pass
        if stop_engine is not None and hasattr(stop_engine, "kill_switch"):
            try:
                stop_engine.kill_switch()
            except Exception:
                pass  # إيقاف المراقبة محاولة best-effort؛ لا يكسر الإشراف

        # تنبيه بشري (عربي). محروس حتى لا يرمي.
        try:
            self._alert_cb(self._build_alert(symbol, decision, result))
        except Exception:
            pass

        # G1.37 (emit-only): تنبيه Telegram ثريّ — فقط على تدخّل فعلي (PLACED).
        #        بعد alert_cb تمامًا؛ لا يمسّ المنطق المختوم؛ محروس ولا يرمي أبدًا.
        if (
            self._notifier is not None
            and isinstance(result, dict)
            and result.get("action") == "PLACED"
        ):
            try:
                self._notifier({
                    "symbol": symbol,
                    "reason": getattr(decision, "reason", None),
                    "result": result,
                    "reference_price": reference_price,
                    "emergency_sl_pct": getattr(self._config, "emergency_sl_pct", None),
                    "naked_seconds": getattr(decision, "naked_seconds", None),
                })
            except Exception:
                pass

    @staticmethod
    def _build_alert(symbol, decision: GuardianDecision, result) -> str:
        action = (result or {}).get("action", "")
        placed = bool((result or {}).get("placed", False))
        if placed:
            tail = "وُضع وقف حمائي واحد وأُوقفت المراقبة."
        elif action == "DRY_RUN":
            tail = "وضع آمن (dry_run): خُطّط وقف حمائي دون وضع فعلي، وأُوقفت المراقبة."
        elif action == "ABORT_PROTECTED":
            tail = "تبيّن وجود بيع حمائي قائم عند التنفيذ — لم يُوضع شيء (لا بيع مزدوج)."
        elif action == "ABORT_NO_FREE_QTY":
            tail = "لا رصيد حرّ قابل للحماية عند التنفيذ — لم يُوضع شيء."
        else:
            tail = "تعذّر وضع الوقف الحمائي؛ أُوقفت المراقبة احترازيًّا."
        return (
            f"شبكة أمان المركز: مركز عارٍ على {symbol} "
            f"({decision.reason}). {tail}"
        )

    # ---- G1.44 / chunk_4: ضبط بوّابات التشغيل المستقلّة (إضافي) -----------
    def set_btc_runtime(self, *, enabled: bool, dry_run: bool) -> None:
        """يضبط تشغيل حارس BTC المستقلّ (OFF ⇒ enabled=False؛ Observe ⇒ dry_run=True)."""
        self._btc_enabled = bool(enabled)
        self._btc_dry_run = bool(dry_run)

    def set_guardian_runtime(self, *, enabled: bool, dry_run: bool) -> None:
        """يضبط تشغيل شبكة أمان المركز المستقلّ (OFF ⇒ enabled=False)."""
        self._guardian_enabled = bool(enabled)
        self.dry_run = bool(dry_run)

    # ---- G1.44: BTC-follow guard action (additive, guarded) --------------
    def _btc_tick(self, symbol, base_asset, state, engine, decision,
                  has_resting, free_qty, monitored_qty, now,
                  guardian_intervening=False):
        # G1.44 / chunk_4: بوّابة التفعيل المستقلّة — OFF ⇒ NOOP تامّ (لا قرار ولا تنفيذ).
        if not self._btc_enabled:
            self._btc_armed = False
            return
        btc_decision = self._btc_follow.tick(now)
        self.last_btc_decision = btc_decision
        if getattr(btc_decision, "action", None) is not BtcFollowAction.TIGHTEN:
            self._btc_armed = False
            return
        if self._btc_armed:
            return
        if not should_btc_tighten(
            btc_decision,
            has_resting_protective_sell=has_resting,
            free_qty=free_qty,
            monitored_qty=monitored_qty,
            guardian_intervening=guardian_intervening,
        ):
            return
        # G1.44 / chunk_4: بوّابة التنفيذ الحيّ المستقلّة. التجاوز الصريح
        # (``_btc_dry_run``) يفصل حارس BTC عن ``self.dry_run`` العامّ؛ None ⇒ اتبعه.
        btc_live = (not self._btc_dry_run) if self._btc_dry_run is not None else (not self.dry_run)
        result = None
        if self._btc_exit_fn is not None and btc_live:
            # G1.46: وسم مصدر الخروج (حارس هبوط BTC) قبل تنفيذ الخروج — إضافة بحتة.
            if engine is not None and hasattr(engine, "note_exit_source"):
                try:
                    engine.note_exit_source("BTC_FOLLOW")
                except Exception:
                    pass
            # G1.52: جَسر مصدر الخروج إلى سجل التدقيق (opt-in).
            if self._exit_source_sink is not None:
                try:
                    self._exit_source_sink("BTC_FOLLOW")
                except Exception:
                    pass
            try:
                result = self._btc_exit_fn(
                    symbol=symbol, base_asset=base_asset or "",
                    btc_decision=btc_decision, state=state, engine=engine,
                )
            except Exception as exc:
                result = {"action": "ERROR", "placed": False, "error": str(exc)}
        else:
            # G1.44 / chunk_4: Observe (أو غياب منفّذ خروج) ⇒ معاينة جافّة بلا تنفيذ.
            result = {"action": "DRY_RUN", "placed": False,
                      "drop_pct": str(getattr(btc_decision, "drop_pct", ""))}
        self.last_btc_result = result
        self._btc_armed = True
        # G1.57 (emit-only): تنبيه Telegram ثريّ لحارس هبوط BTC — فقط على تدخّل
        #        فعلي (PLACED). مرآة لكتلة self._notifier في _intervene؛ لا يمسّ
        #        المنطق المختوم؛ محروس ولا يرمي أبدًا.
        if (
            self._btc_notifier is not None
            and isinstance(result, dict)
            and result.get("action") == "PLACED"
        ):
            try:
                self._btc_notifier({
                    "symbol": symbol,
                    "drop_pct": getattr(btc_decision, "drop_pct", None),
                    "reason": "BTC drop confirmed",
                    "result": result,
                    "reference_price": (getattr(state, "reference_price", None)
                                        or getattr(state, "last_price", None)),
                })
            except Exception:
                pass
        cb = self._btc_alert_cb or self._alert_cb
        if cb is not None:
            try:
                cb(self._build_btc_alert(symbol, btc_decision, result))
            except Exception:
                pass

    @staticmethod
    def _build_btc_alert(symbol, btc_decision, result):
        action = (result or {}).get("action", "")
        placed = bool((result or {}).get("placed", False))
        drop = getattr(btc_decision, "drop_pct", "")
        if placed:
            tail = "نُفّذ خروج دفاعي (تضييق) عبر مسار الخروج المُختبَر."
        elif action == "DRY_RUN":
            tail = "وضع مراقبة (Observe/dry_run): اقتراح تضييق دون تنفيذ."
        else:
            tail = "تعذّر تنفيذ التضييق؛ لا تغيير."
        # G1.44 / chunk_4: البادئة ونصّ الذيل كلاهما له مدخل AR_TO_EN في i18n.
        return "حارس هبوط BTC على " + str(symbol) + ": انحدار مؤكّد (~" + str(drop) + "%). " + tail
