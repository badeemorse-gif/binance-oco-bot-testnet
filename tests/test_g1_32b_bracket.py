"""G1.32b chunk_1/2 — اختبارات القوس الخالصة: validate_bracket + BracketConfig + BracketMonitor."""
import unittest
from decimal import Decimal

from ocobot.domain.bracket import BracketConfig, validate_bracket, BracketMonitor
from ocobot.domain.market_exit import EXIT_LOWER, EXIT_UPPER


class TestValidateBracket(unittest.TestCase):
    def test_valid_normal_in_range(self):
        v = validate_bracket("1.0", "2.0", "1.5")
        self.assertTrue(v["valid"])
        self.assertFalse(v["inverted"])
        self.assertTrue(v["in_range"])

    def test_inverted_bounds(self):
        v = validate_bracket("2.0", "1.0")
        self.assertFalse(v["valid"])
        self.assertTrue(v["inverted"])
        self.assertEqual(v["reason"], "inverted_bounds")

    def test_equal_bounds_is_inverted(self):
        self.assertTrue(validate_bracket("1.0", "1.0")["inverted"])

    def test_no_bounds(self):
        v = validate_bracket("", "")
        self.assertFalse(v["valid"])
        self.assertEqual(v["reason"], "no_bounds")

    def test_current_outside_bounds(self):
        v = validate_bracket("1.0", "2.0", "3.0")
        self.assertTrue(v["valid"])
        self.assertFalse(v["in_range"])
        self.assertEqual(v["reason"], "current_outside_bounds")

    def test_single_bound_valid(self):
        self.assertTrue(validate_bracket("1.0", "")["valid"])


class TestBracketConfig(unittest.TestCase):
    def test_from_inputs_parses(self):
        c = BracketConfig.from_inputs(True, "1.5", "2.5")
        self.assertTrue(c.enabled)
        self.assertEqual(c.lower, Decimal("1.5"))
        self.assertEqual(c.upper, Decimal("2.5"))

    def test_empty_strings_become_none(self):
        c = BracketConfig.from_inputs(False, "", "  ")
        self.assertFalse(c.enabled)
        self.assertIsNone(c.lower)
        self.assertIsNone(c.upper)


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, side, price):
        self.calls.append((side, price))
        return {"action": "PLACED", "exit_side": side}


def _cfg(enabled=True, lower="1.0", upper="2.0"):
    return lambda: BracketConfig.from_inputs(enabled, lower, upper)


class TestBracketMonitor(unittest.TestCase):
    def test_disabled_noop(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg(enabled=False))
        self.assertEqual(m.check("1.5")["action"], "DISABLED")
        self.assertEqual(rec.calls, [])

    def test_within_bracket_noop(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg())
        self.assertEqual(m.check("1.5")["action"], "WITHIN_BRACKET")
        self.assertEqual(rec.calls, [])

    def test_upper_breach_triggers_once(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg())
        # G1.49: wick-debounce — أول اختراق «مُسلَّح» (ARMED) بلا إطلاق.
        self.assertEqual(m.check("2.0")["action"], "ARMED")
        self.assertEqual(len(rec.calls), 0)
        # اختراق ثانٍ متتالٍ (مستمرّ) ⇒ إطلاق خروج واحد.
        r = m.check("2.0")
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(r["exit_side"], EXIT_UPPER)
        self.assertEqual(len(rec.calls), 1)
        # خروج-واحد: الفحص الثالث لا يُطلق ثانيةً.
        self.assertEqual(m.check("2.5")["action"], "ALREADY_FIRED")
        self.assertEqual(len(rec.calls), 1)

    def test_lower_breach_triggers(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg())
        # G1.49: اختراق سفلي مستمرّ (تِكّتان متتاليتان) قبل الإطلاق.
        self.assertEqual(m.check("1.0")["action"], "ARMED")
        r = m.check("1.0")
        self.assertEqual(r["exit_side"], EXIT_LOWER)
        self.assertEqual(len(rec.calls), 1)

    def test_no_price(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg())
        self.assertEqual(m.check(None)["action"], "NO_PRICE")

    def test_reset_allows_refire(self):
        rec = _Rec()
        m = BracketMonitor(exit_executor=rec, config_getter=_cfg())
        # G1.49: كل إطلاق يتطلّب اختراقًا مستمرًّا (تِكّتان)؛ reset يصفّر العدّاد أيضًا.
        m.check("2.0"); m.check("2.0")   # اختراق مستمرّ ⇒ إطلاق أول
        m.reset()
        m.check("2.0"); m.check("2.0")   # بعد reset ⇒ إطلاق ثانٍ
        self.assertEqual(len(rec.calls), 2)


if __name__ == "__main__":
    unittest.main()
