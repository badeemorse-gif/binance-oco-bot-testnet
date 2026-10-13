"""CLI: ``python -m ocobot [--env testnet|live] [--keys PATH] [--recv-window N]``

يُشغّل preflight ويطبع الحالة المرئية للاتصال. لا يطبع أي سر. لا ينفّذ أوامر.
افتراضيًا Testnet (A6). التحويل إلى Live = تبديل base URL + المفتاح فقط (D12)،
والتداول الحقيقي محكوم ببوابة الاعتماد البشري G1.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from ocobot import views
from ocobot.config import DEFAULT_KEYS_PATH, AppConfig
from ocobot.core.audit_log import AuditLog
from ocobot.core.connection_state import ConnectionStatus
from ocobot.core.environment import Environment
from ocobot.core.errors import BinanceApiError, KeysError, OcoBotError, TransportError
from ocobot.core.failure_matrix import humanize
from ocobot.core.keys import load_credentials
from ocobot.core.preflight import run_preflight
from ocobot.core.redaction import RedactingFilter
from ocobot.core.rest_client import SignedRestClient, build_signed_client
from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.oco_reader import OcoReader
from ocobot.core.market_feed import (
    MarketFeedError,
    PriceFeedController,
    RestPriceSource,
)
from ocobot.domain.monitoring import GuardPolicy, MonitoringEngine
from ocobot.domain.reposition import ExecutionState, SafeExecutor
from ocobot.domain.selection import Selector, build_dashboard
from ocobot.core.state_store import (
    LogLocations,
    MonitoringCheckpoint,
    PersistedState,
    SelectedOcoContext,
    StateStore,
)


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())  # لا تُسجَّل المفاتيح/التواقيع إطلاقًا (D8)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=[handler],
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocobot",
        description="OCOBot — preflight + Read & Select (M1، قراءة فقط). "
        "ضع الخيارات العامة قبل الأمر الفرعي.",
    )
    parser.add_argument(
        "--env", choices=[e.value for e in Environment], default=None,
        help="البيئة (افتراضي: OCOBOT_ENV أو testnet)",
    )
    parser.add_argument(
        "--keys", default=None,
        help=f"مسار ملف المفاتيح (افتراضي: {DEFAULT_KEYS_PATH})",
    )
    parser.add_argument(
        "--recv-window", type=int, default=None, help="recvWindow ms (<=60000)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("preflight", help="فحص الاتصال (الافتراضي)")
    sub.add_parser("orders", help="جدول أوامر OCO المفتوحة (قراءة)")
    sel = sub.add_parser("select", help="اختيار OCO بالـ orderListId وعرض هويته")
    sel.add_argument("order_list_id", type=int)
    dash = sub.add_parser("dashboard", help="لوحة القيادة (قراءة)؛ orderListId اختياري")
    dash.add_argument("order_list_id", type=int, nargs="?")

    # M2 (T3): draft = مسودّة قراءة فقط؛ activate = تنفيذ آمن (يتطلب --yes)
    drf = sub.add_parser("draft", help="مسودّة إعادة تموضع (قراءة فقط، dry-run)")
    drf.add_argument("order_list_id", type=int)
    drf.add_argument("--tp", required=True, help="نسبة TP المئوية (مثال: 4)")
    drf.add_argument("--sl", required=True, help="نسبة SL المئوية (مثال: 2)")
    drf.add_argument("--price", required=True, help="السعر المرجعي الحيّ (مُدخَل صريح، D14)")

    act = sub.add_parser("activate", help="تنفيذ إعادة التموضع الآمن (cancel+create)")
    act.add_argument("order_list_id", type=int)
    act.add_argument("--tp", required=True, help="نسبة TP المئوية")
    act.add_argument("--sl", required=True, help="نسبة SL المئوية")
    act.add_argument("--price", required=True, help="السعر المرجعي الحيّ (D14)")
    act.add_argument("--yes", action="store_true", required=True,
                     help="تأكيد صريح مطلوب للتنفيذ (بوابة اعتماد بشري)")
    act.add_argument("--audit-log", default=None, help="مسار ملف سجل التدقيق JSONL")

    # M3 (T4): monitor = مراقبة ديناميكية (dry-run افتراضيًا؛ REAL يتطلب --yes)
    mon = sub.add_parser("monitor", help="مراقبة ديناميكية للـ OCO المحدد (M3)")
    mon.add_argument("order_list_id", type=int, nargs="?",
                     help="orderListId الهدف (أو استخدم --order-list-id)")
    mon.add_argument("--order-list-id", type=int, default=None, dest="order_list_id_opt")
    mon.add_argument("--trigger", required=True, help="نسبة ارتفاع التفعيل المئوية")
    mon.add_argument("--tp", required=True, help="نسبة TP المئوية")
    mon.add_argument("--sl", required=True, help="نسبة SL المئوية")
    mon.add_argument("--tolerance", default="0.1", help="نطاق السحب الصغير المسموح (%)")
    mon.add_argument("--guard", default="1.0", help="حدّ الحركة المعاكسة (%)")
    mon.add_argument("--price", default=None,
                     help="سعر مرجعي بذرة يُستخدم فقط إن تعذّر جلب سعر حيّ (D14)")
    mon.add_argument("--guard-policy", choices=[p.value for p in GuardPolicy],
                     default=GuardPolicy.HALT_NOTIFY.value,
                     help="سلوك الحارس عند الحركة المعاكسة")
    mon.add_argument("--max-ticks", type=int, default=10,
                     help="حدّ أقصى لعدد الـ ticks (يمنع التعليق)")
    mon.add_argument("--yes", action="store_true",
                     help="السماح بإعادة تموضع حقيقية (الافتراضي dry-run)")
    mon.add_argument("--audit-log", default=None, help="مسار ملف سجل التدقيق JSONL")
    mon.add_argument("--state-file", default=None,
                     help="مسار ملف checkpoint للاسترداد (افتراضي: OCOBOT_STATE_FILE أو cwd/ocobot_state.json)")
    return parser


def _resolve_audit_path(args) -> str:
    explicit = getattr(args, "audit_log", None)
    if explicit:
        return explicit
    return os.environ.get(
        "OCOBOT_AUDIT_LOG", os.path.join(os.getcwd(), "ocobot_audit.jsonl")
    )


def _resolve_state_path(args) -> str:
    explicit = getattr(args, "state_file", None)
    if explicit:
        return explicit
    return os.environ.get(
        "OCOBOT_STATE_FILE", os.path.join(os.getcwd(), "ocobot_state.json")
    )


def _build_config(args) -> AppConfig:
    cfg = AppConfig.from_env_vars()
    if args.env:
        cfg = cfg.for_env(args.env)
    if args.keys:
        cfg.keys_path = args.keys
    if args.recv_window:
        cfg.recv_window = max(1, min(int(args.recv_window), 60000))
    return cfg


def _live_notice(cfg: AppConfig) -> None:
    if cfg.env == Environment.LIVE:
        print(
            "\u26a0\ufe0f  تنبيه: البيئة LIVE. أوامر M1 قراءة فقط (لا تنفيذ). "
            "التداول الحقيقي محكوم ببوابة الاعتماد البشري G1."
        )


def _client_with_keys(cfg: AppConfig) -> SignedRestClient:
    """يبني SignedRestClient بعد تحميل المفاتيح؛ يرفع KeysError عند غيابها."""
    creds = load_credentials(cfg.keys_path, cfg.env)
    return build_signed_client(cfg, creds)


def _cmd_preflight(cfg: AppConfig) -> int:
    try:
        state = run_preflight(cfg)
    except Exception as exc:  # مظلّة أمان: لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    print(state.to_display())
    return 0 if state.status == ConnectionStatus.CONNECTED else 1


def _cmd_orders(cfg: AppConfig) -> int:
    try:
        reader = OcoReader(_client_with_keys(cfg))
        ocos = reader.list_open_ocos()
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    print(views.render_orders_table(ocos))
    return 0


def _cmd_select(cfg: AppConfig, order_list_id: int) -> int:
    try:
        client = _client_with_keys(cfg)
        selector = Selector(OcoReader(client), ExchangeInfoService(client))
        selected = selector.select(order_list_id)
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    print(views.render_selected_oco(selected))
    return 0


def _cmd_dashboard(cfg: AppConfig, order_list_id) -> int:
    selected = None
    connection = "\u2014"
    try:
        client = _client_with_keys(cfg)
        try:  # اتصال غير موقّع لإظهار الحالة (لا يحتاج صحة المفاتيح)
            client.sync_time()
            connection = "OK"
        except (TransportError, BinanceApiError):
            connection = "خطأ اتصال"
        if order_list_id is not None:
            selector = Selector(OcoReader(client), ExchangeInfoService(client))
            selected = selector.select(order_list_id)
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    snap = build_dashboard(selected, environment=cfg.env.value, connection=connection)
    print(views.render_dashboard(snap, has_selection=selected is not None))
    return 0


def _build_executor(client, audit=None) -> SafeExecutor:
    return SafeExecutor(client, OcoReader(client), ExchangeInfoService(client),
                        audit=audit)


def _build_feed(cfg: AppConfig, client, symbol: str) -> PriceFeedController:
    """يبني feed سعري: WS مفضّل + سقوط REST (D14). WS يُنشأ كسولًا هنا."""
    from ocobot.core.market_feed import MarketWebSocketSource
    rest = RestPriceSource(client)
    ws = None
    try:
        ws = MarketWebSocketSource(cfg.ws_base(), symbol)
        ws.connect()
    except MarketFeedError:
        ws = None  # سنعتمد على REST
    return PriceFeedController(ws, rest, symbol)


def _cmd_draft(cfg: AppConfig, order_list_id: int, tp, sl, price) -> int:
    try:
        client = _client_with_keys(cfg)
        executor = _build_executor(client)
        result = executor.execute(order_list_id, tp, sl, price, dry_run=True)
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    if result.draft is None:
        print(f"\u26d4 {result.reason or 'تعذّر بناء المسودّة.'}")
        return 1
    print(views.render_draft(result.draft, result.gate))
    return 0 if (result.gate is not None and result.gate.ok) else 1


def _cmd_activate(cfg: AppConfig, args) -> int:
    order_list_id, tp, sl, price, yes = (
        args.order_list_id, args.tp, args.sl, args.price, args.yes
    )
    if not yes:
        print(
            "\u26a0\ufe0f  Activate يتطلّب التأكيد الصريح --yes. "
            "أعرض المسودّة (dry-run) بدلًا من التنفيذ."
        )
        return _cmd_draft(cfg, order_list_id, tp, sl, price)
    try:
        client = _client_with_keys(cfg)
        audit = AuditLog(_resolve_audit_path(args))
        executor = _build_executor(client, audit=audit)
        result = executor.execute(order_list_id, tp, sl, price, dry_run=False)
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
    print(views.render_execution(result))
    print(f"سجل التدقيق: {audit.path}")
    return 0 if result.state == ExecutionState.SUCCESS else 1


def _make_checkpoint_sink(store, selected, checkpoint_path, audit_path):
    """يبني مغرفة حفظ الـ checkpoint (T8): تُستدعى بالـ MonitoringState الحالية.

    تبني ``PersistedState`` من (MonitoringCheckpoint.from_state +
    SelectedOcoContext.from_model + LogLocations) وتحفظها عبر ``store.save(...)``.
    لا ترفع استثناءً أبدًا (الكتابة الذرّية + التنقية داخل StateStore؛ و_persist
    في المحرّك يبتلع الأخطاء أصلًا). لا أسرار (redaction إلزامي داخل StateStore).
    """
    def _sink(state):
        try:
            persisted = PersistedState(
                monitoring=MonitoringCheckpoint.from_state(state),
                selected_oco=SelectedOcoContext.from_model(selected),
                logs=LogLocations(
                    checkpoint_path=checkpoint_path,
                    audit_log_path=audit_path,
                ),
            )
            store.save(persisted)
        except Exception:
            pass  # persistence must never break monitoring
    return _sink


def _cmd_monitor(cfg: AppConfig, args) -> int:
    from decimal import Decimal

    order_list_id = args.order_list_id or args.order_list_id_opt
    if order_list_id is None:
        print("\u26d4 يجب تحديد orderListId (كوسيط أو عبر --order-list-id).")
        return 1
    dry_run = not args.yes
    resumed = False
    try:
        from .domain.recovery import recover, RecoveryDecision

        client = _client_with_keys(cfg)
        audit_path = _resolve_audit_path(args)
        state_path = _resolve_state_path(args)
        audit = AuditLog(audit_path)
        store = StateStore(checkpoint_path=state_path, audit_log_path=audit_path)
        reader = OcoReader(client)
        selector = Selector(reader, ExchangeInfoService(client))

        # T8: قبل أي بدء جديد، جرّب الاسترداد من آخر checkpoint (مطابقة REST أولًا).
        result = recover(store, reader)

        if result.decision is RecoveryDecision.HALT_EXTERNALLY_CLOSED:
            # الأمر المحفوظ أُغلق/غير موجود خارجيًا ⇒ إيقاف بلا أي Cancel/Create.
            alert = result.alert or humanize(Exception())
            print(f"\u26d4 {alert}")
            return 0

        if result.decision is RecoveryDecision.RESUME:
            # أعِد تأسيس الـ OCO المختار عبر target_order_list_id (بعد نجاح مطابقة REST).
            selected = selector.select(result.state.target_order_list_id)
            checkpoint_sink = _make_checkpoint_sink(store, selected, state_path, audit_path)
            executor = _build_executor(client, audit=audit)
            engine = MonitoringEngine(
                executor,
                guard_policy=GuardPolicy(args.guard_policy),
                dry_run=dry_run,
                audit=audit,
                checkpoint_sink=checkpoint_sink,
            )
            engine.resume_from_state(selected, result.state)
            # feed لاستكمال حلقة الأسعار من نفس الرمز المحفوظ.
            feed = _build_feed(cfg, client, selected.symbol)
            resumed = True
        else:
            # NOTHING_TO_RESUME ⇒ بدء نظيف كالمعتاد.
            selected = selector.select(order_list_id)
            # D14: جلب سعر حيّ حقيقي؛ لا نستخدم --price إلا إذا تعذّر الحيّ
            feed = _build_feed(cfg, client, selected.symbol)
            try:
                reference_price = feed.get_price()
            except MarketFeedError:
                if args.price is None:
                    print("\u26d4 تعذّر جلب سعر حيّ ولا يوجد --price بذرة.")
                    return 1
                reference_price = Decimal(str(args.price))
            checkpoint_sink = _make_checkpoint_sink(store, selected, state_path, audit_path)
            executor = _build_executor(client, audit=audit)
            engine = MonitoringEngine(
                executor,
                guard_policy=GuardPolicy(args.guard_policy),
                dry_run=dry_run,
                audit=audit,
                checkpoint_sink=checkpoint_sink,
            )
            engine.start(
                selected, args.trigger, args.tp, args.sl, reference_price,
                tolerance_pct=Decimal(str(args.tolerance)),
                guard_pct=Decimal(str(args.guard)),
            )
    except KeysError as exc:
        print(f"\u26d4 {exc}")
        return 1
    except (BinanceApiError, TransportError, OcoBotError) as exc:
        print(f"\u26d4 {humanize(exc)}")
        return 1
    except Exception as exc:  # لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1

    mode = "REAL (--yes)" if not dry_run else "DRY-RUN (افتراضي)"
    if resumed:
        print("\u21bb استُؤنفت المراقبة من الحالة المحفوظة (checkpoint).")
    print(f"بدأت المراقبة الديناميكية — الوضع: {mode}")
    if feed.alert:
        print(f"\u26a0\ufe0f  {feed.alert}")
    print(views.render_monitoring(engine.state))

    # حلقة ticks محدودة (تمنع التعليق): كل tick سعر حيّ جديد
    for _ in range(max(1, int(args.max_ticks))):
        if not engine.state.enabled:
            break
        try:
            price = feed.get_price()
        except MarketFeedError as exc:
            print(f"\u26a0\ufe0f  {humanize(exc)}")
            break
        tick = engine.on_price_tick(price)
        print(f"  tick @ {price}: {tick.event} — {tick.message}")

    print(views.render_monitoring(engine.state))
    print(f"سجل التدقيق: {audit.path}")
    return 0


_COMMANDS = {
    "preflight": lambda cfg, args: _cmd_preflight(cfg),
    "orders": lambda cfg, args: _cmd_orders(cfg),
    "select": lambda cfg, args: _cmd_select(cfg, args.order_list_id),
    "dashboard": lambda cfg, args: _cmd_dashboard(cfg, args.order_list_id),
    "draft": lambda cfg, args: _cmd_draft(cfg, args.order_list_id, args.tp, args.sl, args.price),
    "activate": lambda cfg, args: _cmd_activate(cfg, args),
    "monitor": lambda cfg, args: _cmd_monitor(cfg, args),
}


def main(argv=None) -> int:
    # اطبع عربي بأمان على Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    cfg = _build_config(args)
    _live_notice(cfg)

    command = args.command or "preflight"
    try:
        if command == "monitor":
            return _cmd_monitor(cfg, args)
        return _COMMANDS[command](cfg, args)
    except Exception as exc:  # مظلّة أمان نهائية: لا استثناء خام للمستخدم (T7)
        print(f"\u26d4 {humanize(exc)}")
        return 1
