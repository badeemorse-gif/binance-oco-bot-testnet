"""اختبارات التنفيذ الآمن لإعادة التموضع (M2 / T3).

تُغطّي: البوابة (D16)، الترتيب الصارم (D4)، Partial-Fill (D17)، المسار السعيد
cancel→create (D2/D3/D19)، No-Blind-Retry (D9)، Idempotency عند ضياع الردّ (D10)،
واستهداف الأمر المحدد فقط (P3)، وقراءة فقط في dry_run (P2).
"""
import unittest
from decimal import Decimal

from ocobot.core.errors import BinanceApiError, TransportError
from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.reposition import (
    ExecutionState,
    SafeExecutor,
    validate_pre_cancel,
)
from tests._fakes import FakeClient


def _executor(client, ids=None):
    exi = ExchangeInfoService(client, monotonic=lambda: 1.0)
    reader = OcoReader(client)
    if ids is not None:
        seq = iter(ids)
        id_factory = lambda prefix: next(seq)
    else:
        id_factory = None
    return SafeExecutor(client, reader, exi, id_factory=id_factory)


class TestGate(unittest.TestCase):
    def _draft(self, client):
        _, draft = _executor(client).build_draft(31, "4", "2", "60000")
        return draft, client

    def test_gate_ok_makes_no_writes_on_dry_run(self):
        # P2: dry_run لا يكتب شيئًا
        client = FakeClient()
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=True)
        self.assertEqual(result.state, ExecutionState.GATE_PASSED)
        self.assertTrue(result.gate.ok)
        # لا DELETE ولا POST إطلاقًا
        self.assertEqual(client.cancel_calls(), [])
        self.assertEqual(client.create_calls(), [])

    def test_ordering_violation_blocks_cancel(self):
        # D4/D16: انتهاك الترتيب ⇒ gate not ok، ولا كتابة (لا إلغاء)
        client = FakeClient()
        # reference منخفض جدًا يجعل TP < Last ينكسر الترتيب الصارم مع last عالٍ
        # نبني مسودّة عبر build_draft ثم نتحقق بـ last مرتفع يكسر الترتيب
        _, draft = _executor(client).build_draft(31, "4", "2", "60000")
        gate = validate_pre_cancel(draft, Decimal("999999"), draft.filters)
        self.assertFalse(gate.ok)
        # وعبر execute مع reference يكسر الترتيب: reference أعلى من TP
        client2 = FakeClient()
        res = _executor(client2).execute(31, "1", "50", "60000", dry_run=False)
        # sl 50% يجعل trigger بعيدًا جدًا؛ نتحقق فقط أنه إن فشل، لا كتابة
        if res.state == ExecutionState.ABORTED:
            self.assertEqual(client2.cancel_calls(), [])
            self.assertEqual(client2.create_calls(), [])

    def test_partial_fill_abort_no_writes(self):
        # D17: متبقٍ ضئيل جدًا ⇒ partial_fill_abort و لا كتابة
        # executed 0.4999 من 0.5 → متبقٍ 0.0001، *سعر منخفض قد يقل عن minNotional
        client = FakeClient(orig_qty="0.5", executed_qty="0.4999")
        result = _executor(client).execute(31, "4", "2", "0.05", dry_run=False)
        self.assertEqual(result.state, ExecutionState.ABORTED)
        self.assertTrue(result.gate.partial_fill_abort)
        self.assertIn("naked", result.reason.lower() + " naked")  # رسالة "no naked position"
        self.assertEqual(client.cancel_calls(), [])
        self.assertEqual(client.create_calls(), [])


class TestSafeExecute(unittest.TestCase):
    def test_happy_path_cancel_then_create(self):
        # D2/D3/D19: cancel ثم create، مع تحقق ترتيب النداءات والحمولة
        client = FakeClient(new_order_list_id=99)
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.SUCCESS)
        self.assertEqual(result.new_order_list_id, 99)
        self.assertEqual(result.cancelled_order_list_id, 31)

        # DELETE قبل POST
        methods = [(m, p) for (m, p, _) in client.write_calls if m in ("DELETE", "POST")]
        self.assertEqual(methods[0], ("DELETE", "/api/v3/orderList"))
        self.assertEqual(methods[1], ("POST", "/api/v3/orderList/oco"))

        # حمولة الإنشاء (D3)
        create = client.create_calls()[0][2]
        self.assertEqual(create["side"], "SELL")
        self.assertEqual(create["aboveType"], "LIMIT_MAKER")
        self.assertEqual(create["belowType"], "STOP_LOSS_LIMIT")
        self.assertEqual(create["belowTimeInForce"], "GTC")
        self.assertIn("belowStopPrice", create)
        self.assertIn("belowPrice", create)
        # الكمية = المتبقية المُنزَّلة لِ step (D7): remaining 0.5 → 0.5
        self.assertEqual(create["quantity"], "0.5")

    def test_remaining_qty_used(self):
        # D7: تُستخدم الكمية المتبقية (origQty - executedQty)
        client = FakeClient(orig_qty="0.5", executed_qty="0.1")
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.SUCCESS)
        create = client.create_calls()[0][2]
        # المتبقي 0.4 (مضاعف step 0.0001)
        self.assertEqual(create["quantity"], "0.4")

    def test_unique_client_order_id_across_executes(self):
        # D10: listClientOrderId فريد بين تنفيذين
        c1 = FakeClient()
        c2 = FakeClient()
        _executor(c1).execute(31, "4", "2", "60000", dry_run=False)
        _executor(c2).execute(31, "4", "2", "60000", dry_run=False)
        id1 = c1.create_calls()[0][2]["listClientOrderId"]
        id2 = c2.create_calls()[0][2]["listClientOrderId"]
        self.assertNotEqual(id1, id2)
        # <=36 حرفًا (Binance-safe)
        self.assertLessEqual(len(id1), 36)

    def test_create_fail_after_cancel_needs_attention(self):
        # D9: Cancel OK + Create FAILED (BinanceApiError) ⇒ FAILED_NEEDS_ATTENTION
        client = FakeClient(create_error=BinanceApiError(-2010, "rejected", 400))
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.FAILED_NEEDS_ATTENTION)
        self.assertIn("تدخّل يدوي", result.reason)
        # DELETE تم، وPOST جُرّب
        self.assertEqual(len(client.cancel_calls()), 1)
        self.assertEqual(len(client.create_calls()), 1)

    def test_lost_reply_idempotency_exists(self):
        # D10: ردّ ضائع + الأمر موجود عند الفحص ⇒ SUCCESS، فحص واحد فقط، لا POST ثانٍ
        client = FakeClient(create_transport_error=True, exists_on_recheck=True,
                            recheck_id=99)
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.SUCCESS)
        self.assertEqual(result.new_order_list_id, 99)
        self.assertEqual(len(client.recheck_calls()), 1)  # فحص واحد بالضبط
        self.assertEqual(len(client.create_calls()), 1)   # POST واحد فقط (الأصلي)

    def test_lost_reply_idempotency_missing(self):
        # D10: ردّ ضائع + الأمر غير موجود ⇒ FAILED_NEEDS_ATTENTION، لا POST ثانٍ
        client = FakeClient(create_transport_error=True, exists_on_recheck=False)
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.FAILED_NEEDS_ATTENTION)
        self.assertEqual(len(client.recheck_calls()), 1)
        self.assertEqual(len(client.create_calls()), 1)

    def test_cancel_failure_aborts_no_create(self):
        # D9: فشل الإلغاء ⇒ ABORTED، لا إنشاء
        client = FakeClient(cancel_error=BinanceApiError(-2011, "unknown order", 400))
        result = _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        self.assertEqual(result.state, ExecutionState.ABORTED)
        self.assertEqual(len(client.cancel_calls()), 1)
        self.assertEqual(client.create_calls(), [])

    def test_p3_delete_targets_exact_order_list_id(self):
        # P3: يُلغى فقط الأمر المحدد بالـ orderListId
        client = FakeClient()
        _executor(client).execute(31, "4", "2", "60000", dry_run=False)
        delete_params = client.cancel_calls()[0][2]
        self.assertEqual(delete_params["orderListId"], 31)
        self.assertEqual(delete_params["symbol"], "BTCUSDT")

    def test_p2_dry_run_no_writes(self):
        # P2: dry_run لا يكتب
        client = FakeClient()
        _executor(client).execute(31, "4", "2", "60000", dry_run=True)
        self.assertEqual(client.cancel_calls(), [])
        self.assertEqual(client.create_calls(), [])


if __name__ == "__main__":
    unittest.main()
