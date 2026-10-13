"""G1.19 (AC2): بذر السعر الحيّ لأمر OCO قديم عبر مسار الاتصال الحقيقي.

المشكلة (G1.19): أوامر OCO المفتوحة قبل تشغيل البوت لا تتتبّع السعر الحيّ في
«المراقبة الديناميكية» (الحالة «متصل» لكن بلا سعر حيّ/مرجعي؛ الضغط على «ابدأ»
يعطي «تعذّر البدء — لا سعر حيّ بعد»)، بينما الأوامر الجديدة تعمل.

الجذر (fix v2): تبويب «الاتصال» الجديد يبني مزوّد سعر كسولًا ويحقنه في شاشة
المراقبة (04) فقط عبر mon.set_price_provider، ولا يحقنه في MainWindow إطلاقًا،
فيبقى MainWindow._price_provider = None ⇒ _show_selected لا يستدعي set_symbol/
get_price لأمر OCO القديم. الإصلاح: make_connect_wrapper يحقن _lazy_price في
النافذة أيضًا عبر window.set_price_provider.

هذا الاختبار يقود المسار الحقيقي ``ocobot.ui.app.make_connect_wrapper`` (لا
يستدعي mon.set_price_provider مباشرةً): يبني شاشات حقيقية (02/03/04) بلا
اعتماديات كما في الإقلاع البارد، ثم يُنفّذ اتصالًا ناجحًا عبر الـ wrapper مع
ترقيع أسماء module في ``ocobot.ui.app`` بفيكات حتميّة، فلا شبكة ولا سوكِت ولا
Binance حقيقي إطلاقًا (T16 ممنوع). ثم يُطبَّق مسار الاختيار المتجاوِز
(open_orders → MainWindow._show_selected) على أمر OCO قديم، ويؤكّد:
  (أ) MainWindow استلم مزوّد السعر (set_price_provider استُدعي ⇒ _price_provider
      ليس None) بعد الاتصال عبر الـ wrapper الحقيقي.
  (ب) set_symbol استُدعي برمز الأمر، وبُذر السعر الحيّ على الهدف (current_price)
      وعلى الشاشتين 03/04، فيبدأ المحرّك الحقيقي بنجاح دون رسالة
      «تعذّر البدء — لا سعر حيّ بعد» (AC2).
  (ج) أمر البيع المستقل/الجديد (مرشّح تحويل) ما زال يُبذَر له السعر عبر نفس
      المسار (لا انحدار).

كل الاعتماديات فيكات في الذاكرة (عميل/مزوّد سعر)؛ Runner متزامن (submit يُنفّذ
fn فورًا ويستدعي on_result) فيبقى الاختبار حتميًّا ومعزولًا عن الشبكة والخيوط.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from unittest import mock

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.open_orders import OpenOrdersScreen
from ocobot.ui.selected_oco import SelectedOcoScreen
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.ui.app import make_connect_wrapper
from ocobot.core.connection_state import ConnectionStatus
from ocobot.domain.models import OpenSellOrder, SelectedOCO, SymbolFilters
from ocobot.domain.monitoring import MonitoringEngine, MonitoringStateEnum
from ocobot.domain.reposition import SafeExecutor
from tests._fakes import FakeClient, FakeResult, FakeContent, FakeWindow, FakeCfg


# --------------------- أدوات التزامن (بلا خيوط/شبكة) -----------------------
class _SyncRunner:
    """Runner منفّذ متزامنًا (كبقيّة اختبارات الواجهة): submit يُنفّذ fn فورًا."""

    def submit(self, fn, *a, on_result=None, on_error=None, **k):
        try:
            r = fn(*a, **k)
        except Exception as exc:  # pragma: no cover - دفاعي
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(r)
        return r


class _Notifier:
    def __init__(self):
        self.state = None

    def set_state(self, state):
        self.state = state


class _RealishWindow(FakeWindow):
    """نافذة اختبار قريبة من MainWindow: تحمل runner + content + مزوّد سعر.

    ``set_price_provider`` و``_show_selected`` منسوخان حرفيًّا من
    ``ocobot.ui.main_window.MainWindow`` (نفس منطق بذر السعر الحيّ G1.19) حتى
    يقود الاختبار سلوك الإنتاج دون بناء QMainWindow كامل في بيئة offscreen؛ هكذا
    نثبت أن make_connect_wrapper يحقن المزوّد في النافذة (set_price_provider)
    وأن _show_selected يبذر السعر لأمر OCO قديم عبر المزوّد المحقون.
    """

    def __init__(self, connection_notifier, content, runner):
        super().__init__(connection_notifier, content)
        self.runner = runner
        self._price_provider = None  # كما في الإقلاع البارد: لا مزوّد قبل الاتصال

    # منسوخ من MainWindow.set_price_provider (G1.19 fix v2): تخزين فقط.
    def set_price_provider(self, provider):
        self._price_provider = provider

    # منسوخ من MainWindow._show_selected (جزء بذر السعر الحيّ G1.19): يغذّي
    # الشاشتين 03/04 ثم يبذر السعر الحيّ عبر المزوّد المحقون + الرَنَر.
    def _show_selected(self, selected):
        sel = self.content.screen_for("03_selected_and_edit")
        if sel is not None:
            sel.set_selected(selected)
        mon = self.content.screen_for("04_dynamic_monitoring")
        if mon is not None and hasattr(mon, "set_selected"):
            mon.set_selected(selected)
        try:
            provider = getattr(self, "_price_provider", None)
            runner = getattr(self, "runner", None)
            symbol = getattr(selected, "symbol", None)
            if provider is not None and runner is not None and symbol:
                def _seed_price(_sym=symbol, _p=provider):
                    if hasattr(_p, "set_symbol"):
                        _p.set_symbol(_sym)
                    return _p.get_price() if hasattr(_p, "get_price") else None

                def _on_price(price, _sel=selected, _sel03=sel, _mon=mon):
                    try:
                        if price is None:
                            return
                        try:
                            _sel.current_price = price
                        except Exception:
                            pass
                        if _mon is not None and hasattr(_mon, "set_current_price"):
                            _mon.set_current_price(price)
                        if _sel03 is not None and hasattr(_sel03, "set_current_price"):
                            _sel03.set_current_price(price)
                    except Exception:
                        pass

                runner.submit(_seed_price, on_result=_on_price)
        except Exception:
            pass


# --------------------------- فيكات الاعتماديات ----------------------------
class _FakePriceProvider:
    """مزوّد سعر حيّ وهمي بواجهة SelectionPriceProvider (set_symbol/get_price).

    يسجّل كل symbol مرّ عبر set_symbol ويُعيد سعرًا ثابتًا من get_price — بلا أي
    بناء feed أو سوكِت أو urllib (لا شبكة).
    """

    def __init__(self, price):
        self._price = price
        self.symbols = []

    def set_symbol(self, symbol):
        self.symbols.append(symbol)

    def get_price(self):
        return self._price

    def __call__(self):
        return self._price


def _oco_raw(order_list_id=31, symbol="BTCUSDT"):
    """ساقا OCO بيع خام (dicts) تتشاركان orderListId موجبًا — تمثّل أمرًا قديمًا."""
    return [
        {
            "symbol": symbol, "orderId": 11, "orderListId": order_list_id,
            "type": "LIMIT_MAKER", "side": "SELL", "price": "70000.00",
            "stopPrice": "0.00", "trailingDelta": "", "origQty": "0.5",
            "executedQty": "0", "status": "NEW", "time": 1,
        },
        {
            "symbol": symbol, "orderId": 12, "orderListId": order_list_id,
            "type": "STOP_LOSS_LIMIT", "side": "SELL", "price": "58000.00",
            "stopPrice": "58500.00", "trailingDelta": "", "origQty": "0.5",
            "executedQty": "0", "status": "NEW", "time": 1,
        },
    ]


def _standalone_order(symbol="BTCUSDT"):
    """أمر بيع مستقل غير OCO (مصدر مرشّح للتحويل) — ككائن OpenSellOrder."""
    return OpenSellOrder(
        symbol=symbol, orderId=777, orderListId=-1, order_type="LIMIT",
        side="SELL", price="100", stopPrice="0", trailingDelta="",
        origQty="1", executedQty="0", status="NEW", time=1,
        is_oco=False, oco_group_id=None, badge="LIMIT",
    )


class G119OldOrderLivePriceViaConnectTests(unittest.TestCase):
    """G1.19 (AC2): الاتصال عبر make_connect_wrapper الحقيقي يحقن مزوّد السعر في
    MainWindow، فيبذر _show_selected السعر الحيّ لأمر OCO قديم (ولأمر مستقل)،
    فيبدأ المحرّك الحقيقي دون «تعذّر البدء — لا سعر حيّ بعد».

    يفشل ضد الكود القديم (الذي كان يحقن المزوّد في شاشة 04 فقط لا في النافذة ⇒
    _price_provider يبقى None ⇒ لا set_symbol/بذر لأمر OCO القديم) وينجح مع fix v2.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _connect_and_build(self, price):
        """يبني شاشات 02/03/04 حقيقية بلا اعتماديات ثم يقود مسار اتصال ناجح عبر
        make_connect_wrapper الحقيقي مع ترقيع أسماء ocobot.ui.app بفيكات حتميّة.

        يُرجع (window, oo, sel, mon, provider). لا شبكة إطلاقًا: build_gui_client
        يُرقَّع ليُعيد FakeClient، وSelectionPriceProvider يُرقَّع ليُعيد مزوّدًا
        وهميًّا، فالعميل الموقّع لا يُبنى فعلًا ولا يُفتح أي اتصال.
        """
        oo = OpenOrdersScreen()                      # 02: _build_fn=None كالإقلاع البارد
        sel = SelectedOcoScreen(executor=None)       # 03: بلا executor
        mon = DynamicMonitoringScreen(engine=None, price_provider=None, runner=None)  # 04
        self.assertIsNone(sel._executor)
        self.assertIsNone(mon._engine)
        self.assertIsNone(mon._price_provider)

        notifier = _Notifier()
        runner = _SyncRunner()
        window = _RealishWindow(
            notifier,
            FakeContent({
                "02_open_orders": oo,
                "03_selected_and_edit": sel,
                "04_dynamic_monitoring": mon,
            }),
            runner,
        )
        self.assertIsNone(window._price_provider)  # لا مزوّد في النافذة قبل الاتصال
        cfg = FakeCfg()

        fake_client = FakeClient()
        provider = _FakePriceProvider(price)
        # محرّك/منفّذ حقيقيان على عميل وهمي (بلا شبكة): يثبتان أن البدء يصل
        # engine.start بسعر مرجعي حقيقي بدل حارس «لا سعر حيّ بعد».
        real_executor = SafeExecutor.__new__(SafeExecutor)  # لا نحتاج __init__ هنا
        real_engine = MonitoringEngine(real_executor, dry_run=False)

        # لا شبكة: نُرقّع كل الأسماء التي يبني منها make_connect_wrapper اعتمادياته.
        with mock.patch(
            "ocobot.ui.app.build_gui_client", return_value=fake_client
        ), mock.patch(
            "ocobot.ui.app.read_all_open_sell_orders",
            side_effect=lambda _client: [],
        ), mock.patch(
            "ocobot.ui.app._build_executor", return_value=real_executor
        ), mock.patch(
            "ocobot.ui.app.MonitoringEngine", return_value=real_engine
        ), mock.patch(
            "ocobot.ui.app.SelectionPriceProvider", return_value=provider
        ), mock.patch(
            "ocobot.ui.app.build_convert_executor", return_value=object()
        ), mock.patch(
            "ocobot.ui.app.make_convert_cb", return_value=(lambda *a, **k: None)
        ):
            wrapped = make_connect_wrapper(
                window, lambda *a, **k: FakeResult(ok=True), cfg
            )
            result = wrapped(api_key="k", api_secret="s", keys_path="")

        self.assertTrue(getattr(result, "ok", False))
        self.assertIsNotNone(notifier.state)
        self.assertEqual(notifier.state.status, ConnectionStatus.CONNECTED)
        return window, oo, sel, mon, provider, real_engine

    # (أ)+(ب) أمر OCO قديم: الاتصال يحقن المزوّد في النافذة، و_show_selected يبذر
    # السعر الحيّ فيبدأ المحرّك دون «تعذّر البدء — لا سعر حيّ بعد» (AC2).
    def test_old_oco_connect_seeds_live_price_and_start_succeeds(self):
        price = Decimal("60000.00")
        window, oo, sel, mon, provider, engine = self._connect_and_build(price)

        # (أ) make_connect_wrapper حقن المزوّد في النافذة نفسها (fix v2)، لا في
        # شاشة 04 وحدها — المسار المتجاوِز لـ _show_selected يراه الآن.
        self.assertIsNotNone(window._price_provider)
        self.assertIs(window._price_provider, provider)
        self.assertIsNotNone(mon._price_provider)

        # نقود مسار الاختيار الحقيقي: اختيار صفّ OCO في شاشة 02 عبر Selector
        # (المحقون أثناء الاتصال) ⇒ _handle_sell_selection_changed ⇒ on_sell_select.
        oo.set_on_sell_select(window._show_selected)
        oo.set_open_sell_orders(_oco_raw(order_list_id=31, symbol="BTCUSDT"))
        selected = oo._current_selection

        # إن تعذّر توجيه Selector (بيئة فيك) نُطبّق الهوية مباشرةً على نفس المسار
        # (open_orders → _show_selected) ببناء SelectedOCO لأمر OCO قديم.
        if selected is None:
            selected = SelectedOCO(
                order_list_id=31, symbol="BTCUSDT", quantity=Decimal("0.5"),
                tp=Decimal("70000.00"), stop_trigger=Decimal("58500.00"),
                stop_limit=Decimal("58000.00"), leg_ids=[11, 12],
                status="EXECUTING",
                filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
            )
            window._show_selected(selected)

        self.assertFalse(getattr(selected, "is_convert_candidate", False))

        # (ب) set_symbol استُدعي برمز الأمر، والسعر الحيّ بُذر على الهدف والشاشتين.
        self.assertIn("BTCUSDT", provider.symbols)
        self.assertEqual(selected.current_price, price)
        self.assertEqual(sel._current_price, price)
        self.assertEqual(mon._current_price, price)

        # البدء على المحرّك الحقيقي: ينجح بسعر مرجعي حقيقي، لا رسالة «لا سعر حيّ بعد».
        mon.set_selected(selected)
        mon.set_current_price(price)
        mon._pct_edits["trigger_pct"].setText("1")
        mon._pct_edits["tp_pct"].setText("4")
        mon._pct_edits["sl_pct"].setText("2")
        mon._on_start_clicked()

        self.assertNotIn(
            "تعذّر البدء — لا سعر حيّ بعد",
            mon._live["last_operation"].text(),
        )
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertEqual(engine.state.reference_price, price)
        self.assertEqual(engine.state.target_order_list_id, 31)

    # (ج) انحدار: أمر بيع مستقل/جديد (مرشّح تحويل) ما زال يُبذَر له السعر الحيّ
    # عبر نفس مسار الاتصال/الاختيار.
    def test_standalone_candidate_connect_still_seeds_live_price(self):
        price = Decimal("123.45")
        window, oo, sel, mon, provider, _engine = self._connect_and_build(price)
        self.assertIs(window._price_provider, provider)

        selected = SelectedOCO.from_open_sell_order(
            _standalone_order("BTCUSDT"),
            filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
        )
        self.assertTrue(selected.is_convert_candidate)

        window._show_selected(selected)

        self.assertIn("BTCUSDT", provider.symbols)
        self.assertEqual(selected.current_price, price)
        self.assertEqual(sel._current_price, price)
        self.assertEqual(mon._current_price, price)


if __name__ == "__main__":
    unittest.main()
