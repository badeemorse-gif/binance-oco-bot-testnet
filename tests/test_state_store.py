"""اختبارات طبقة التخزين (State Store — T5 / M4a).

تُغطّي: الجولة الكاملة (round-trip) مع دقّة Decimal والـ enum، الكتابة الذرّية
عند التعطّل وسط الكتابة (الملف الجيّد السابق يبقى سليمًا ولا يُترَك ملف مؤقّت)،
الملف التالف (قراءة آمنة تعيد None أو ترفع الخطأ المُعرّف)، اكتمال السكيمة (كل
حقول MonitoringState اللازمة للاستئناف تنجو من الجولة)، أمان الأسرار (لا مفتاح/
سرّ/توقيع في الملف المكتوب)، والاعتماد على المكتبة القياسية فقط.
"""
import ast
import os
import tempfile
import unittest
from decimal import Decimal

from ocobot.core.state_store import (
    LogLocations,
    MonitoringCheckpoint,
    PersistedState,
    SelectedOcoContext,
    StateStore,
    StateStoreError,
    SymbolFiltersSchema,
    SCHEMA_VERSION,
)
from ocobot.domain.models import SelectedOCO, SymbolFilters
from ocobot.domain.monitoring import MonitoringState, MonitoringStateEnum


# كل حقول MonitoringState اللازمة للاستئناف — تُقارن ضدّ السكيمة (guard ضد إسقاط حقل).
_RESUME_FIELDS = [
    "enabled",
    "state",
    "symbol",
    "reference_price",
    "trigger_pct",
    "tp_pct",
    "sl_pct",
    "latched",
    "in_flight",
    "target_order_list_id",
    "tolerance_pct",
    "guard_pct",
    "last_price",
    "last_reposition",
    "cursor",
    "trade_uid",
    "session_no",
]


def _tmp_checkpoint():
    d = tempfile.mkdtemp()
    return os.path.join(d, "sub", "checkpoint.json")


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _full_monitoring_state() -> MonitoringState:
    st = MonitoringState()
    st.enabled = True
    st.state = MonitoringStateEnum.TRIGGERED
    st.symbol = "BTCUSDT"
    st.reference_price = Decimal("0.04959")
    st.trigger_pct = Decimal("1.5")
    st.tp_pct = Decimal("4")
    st.sl_pct = Decimal("2")
    st.latched = True
    st.in_flight = False
    st.target_order_list_id = 12345
    st.tolerance_pct = Decimal("0.1")
    st.guard_pct = Decimal("1.0")
    st.last_price = Decimal("0.05262")
    st.last_reposition = {"cursor": 3, "newOrderListId": 999, "referencePrice": "0.05262"}
    st.cursor = 3
    st.trade_uid = "T-UID-123"
    st.session_no = 2
    return st


def _full_selected_oco() -> SelectedOCO:
    filters = SymbolFilters(
        symbol="BTCUSDT",
        tick_size=Decimal("0.00001"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        min_notional=Decimal("10"),
        updated_at="2026-01-01T00:00:00+00:00",
    )
    return SelectedOCO(
        order_list_id=12345,
        symbol="BTCUSDT",
        quantity=Decimal("1.23456789"),
        tp=Decimal("0.05262"),
        stop_trigger=Decimal("0.04959"),
        stop_limit=Decimal("0.04958"),
        leg_ids=[111, 222],
        status="EXECUTING",
        filters=filters,
    )


class TestRoundTrip(unittest.TestCase):
    def test_full_round_trip_preserves_decimal_and_enum(self):
        path = _tmp_checkpoint()
        store = StateStore(path, audit_log_path=os.path.join(os.path.dirname(path), "audit.jsonl"))

        checkpoint = MonitoringCheckpoint.from_state(_full_monitoring_state())
        selected = SelectedOcoContext.from_model(_full_selected_oco())
        state = PersistedState(monitoring=checkpoint, selected_oco=selected,
                               saved_at="2026-01-01T00:00:00+00:00")

        store.save(state)
        loaded = store.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)

        mon = loaded.monitoring
        # enum value يُستعاد نصًّا مطابقًا للقيمة الأصلية.
        self.assertEqual(mon.state, MonitoringStateEnum.TRIGGERED.value)
        # الدقّة المالية محفوظة تمامًا (Decimal، لا float).
        self.assertEqual(mon.reference_price, Decimal("0.04959"))
        self.assertIsInstance(mon.reference_price, Decimal)
        self.assertEqual(mon.last_price, Decimal("0.05262"))
        self.assertEqual(mon.trigger_pct, Decimal("1.5"))
        self.assertEqual(mon.tolerance_pct, Decimal("0.1"))
        self.assertEqual(mon.guard_pct, Decimal("1.0"))
        self.assertEqual(mon.target_order_list_id, 12345)
        self.assertTrue(mon.latched)
        self.assertFalse(mon.in_flight)
        self.assertEqual(mon.cursor, 3)
        self.assertEqual(mon.last_reposition["newOrderListId"], 999)

        sel = loaded.selected_oco
        self.assertEqual(sel.order_list_id, 12345)
        self.assertEqual(sel.symbol, "BTCUSDT")
        self.assertEqual(sel.quantity, Decimal("1.23456789"))
        self.assertIsInstance(sel.quantity, Decimal)
        self.assertEqual(sel.tp, Decimal("0.05262"))
        self.assertEqual(sel.stop_trigger, Decimal("0.04959"))
        self.assertEqual(sel.stop_limit, Decimal("0.04958"))
        self.assertEqual(sel.leg_ids, [111, 222])
        self.assertTrue(sel.quantity_locked)
        self.assertEqual(sel.filters.tick_size, Decimal("0.00001"))
        self.assertEqual(sel.filters.min_notional, Decimal("10"))

        self.assertEqual(loaded.logs.checkpoint_path, path)
        self.assertTrue(loaded.logs.audit_log_path.endswith("audit.jsonl"))

    def test_missing_file_returns_none(self):
        path = _tmp_checkpoint()
        store = StateStore(path)
        self.assertIsNone(store.load())

    def test_decimal_stored_as_string_not_float(self):
        path = _tmp_checkpoint()
        store = StateStore(path)
        state = PersistedState(monitoring=MonitoringCheckpoint(reference_price=Decimal("0.1")))
        store.save(state)
        raw = _read_text(path)
        # القيمة مُخزَّنة كنصّ "0.1" لا كـ float 0.1 (لا فقد دقّة).
        self.assertIn('"referencePrice": "0.1"', raw)
        self.assertNotIn('"referencePrice": 0.1', raw)


class TestAtomicity(unittest.TestCase):
    def test_crash_mid_write_keeps_previous_good_file(self):
        path = _tmp_checkpoint()
        store = StateStore(path)

        # اكتب حالة جيّدة أولى.
        good = PersistedState(monitoring=MonitoringCheckpoint(symbol="GOOD", cursor=1))
        store.save(good)
        good_bytes = _read_bytes(path)

        # حاكِ فشلًا أثناء rename (os.replace) في الكتابة التالية.
        import ocobot.core.state_store as ss

        original_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated crash during replace")

        ss.os.replace = boom
        try:
            with self.assertRaises(OSError):
                store.save(PersistedState(monitoring=MonitoringCheckpoint(symbol="BAD", cursor=2)))
        finally:
            ss.os.replace = original_replace

        # الملف الجيّد السابق سليم تمامًا وقابل للقراءة.
        self.assertEqual(_read_bytes(path), good_bytes)
        loaded = store.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.monitoring.symbol, "GOOD")
        self.assertEqual(loaded.monitoring.cursor, 1)

        # لا ملف مؤقّت متبقٍّ في المجلد.
        directory = os.path.dirname(path)
        leftovers = [n for n in os.listdir(directory) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_write_when_no_previous_file_leaves_no_temp(self):
        path = _tmp_checkpoint()
        store = StateStore(path)
        import ocobot.core.state_store as ss
        original_replace = os.replace

        def boom(src, dst):
            raise OSError("boom")

        ss.os.replace = boom
        try:
            with self.assertRaises(OSError):
                store.save(PersistedState(monitoring=MonitoringCheckpoint(symbol="X")))
        finally:
            ss.os.replace = original_replace

        # لا هدف مكتوب ولا ملف مؤقّت متبقٍّ.
        self.assertFalse(os.path.exists(path))
        directory = os.path.dirname(path)
        leftovers = [n for n in os.listdir(directory) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestCorruptFile(unittest.TestCase):
    def test_corrupt_json_returns_none(self):
        path = _tmp_checkpoint()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"schemaVersion": 1, "monitoring": {"referen')  # مقطوع
        store = StateStore(path, ensure_dir=False)
        self.assertIsNone(store.load())

    def test_garbage_bytes_return_none(self):
        path = _tmp_checkpoint()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x00\x01\x02not json at all\xff")
        store = StateStore(path, ensure_dir=False)
        # بايتات لا يمكن فكّها كـ UTF-8 ⇒ قراءة آمنة تعيد None (لا استثناء خام).
        self.assertIsNone(store.load())

    def test_corrupt_json_strict_raises_defined_error(self):
        path = _tmp_checkpoint()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        store = StateStore(path, ensure_dir=False)
        with self.assertRaises(StateStoreError):
            store.load(strict=True)


class TestSchemaCompleteness(unittest.TestCase):
    def test_every_monitoring_state_resume_field_present_on_schema(self):
        checkpoint = MonitoringCheckpoint()
        for field_name in _RESUME_FIELDS:
            self.assertTrue(
                hasattr(checkpoint, field_name),
                f"MonitoringCheckpoint is missing resume field: {field_name}",
            )

    def test_every_resume_field_survives_round_trip(self):
        path = _tmp_checkpoint()
        store = StateStore(path)
        original = MonitoringCheckpoint.from_state(_full_monitoring_state())
        store.save(PersistedState(monitoring=original))
        restored = store.load().monitoring
        for field_name in _RESUME_FIELDS:
            self.assertEqual(
                getattr(restored, field_name),
                getattr(original, field_name),
                f"resume field changed across round-trip: {field_name}",
            )

    def test_monitoring_state_has_no_unknown_resume_fields(self):
        # حصانة: إن أُضيف حقل جديد لـ MonitoringState لاحقًا يُنبّه هذا الاختبار.
        model_fields = set(MonitoringState.__dataclass_fields__.keys())
        schema_fields = set(_RESUME_FIELDS)
        self.assertEqual(
            model_fields,
            schema_fields,
            "MonitoringState fields drifted from the persisted schema; update state_store + tests.",
        )


class TestSecretSafety(unittest.TestCase):
    def test_secretlike_fields_are_not_written(self):
        path = _tmp_checkpoint()
        store = StateStore(path)
        secret = "RAWAPIKEY0123456789"
        sig = "deadBEEF0123456789abcdef"
        # حمولة ملوّثة بحقول سرّية داخل last_reposition (مسار dict حرّ).
        checkpoint = MonitoringCheckpoint(
            symbol="BTCUSDT",
            last_reposition={
                "api_key": secret,
                "secret": secret,
                "signature": sig,
                "token": "abc.def.ghi",
                "nested": {"password": "hunter2", "ok": "keep-me"},
                "safeField": "visible",
            },
        )
        store.save(PersistedState(monitoring=checkpoint))
        raw = _read_text(path)
        self.assertNotIn(secret, raw)
        self.assertNotIn(sig, raw)
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("abc.def.ghi", raw)
        self.assertIn("***", raw)
        self.assertIn("keep-me", raw)  # الحقول غير الحسّاسة تبقى


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "ocobot", "core", "state_store.py",
        )
        with open(module_path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        stdlib_allowed = {
            "__future__", "json", "os", "tempfile", "dataclasses",
            "decimal", "enum", "typing",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_roots.add(node.module.split(".")[0])

        # لا استيراد من ocobot.* ولا أي حزمة خارجية — مكتبة قياسية فقط.
        self.assertTrue(
            imported_roots.issubset(stdlib_allowed),
            f"state_store imports outside stdlib: {imported_roots - stdlib_allowed}",
        )


if __name__ == "__main__":
    unittest.main()
