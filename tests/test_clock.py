import unittest

from ocobot.core.clock import ServerClock


class TestClock(unittest.TestCase):
    def test_offset_and_timestamp(self):
        local = [1000]  # mutable "now"
        clock = ServerClock(time_fetcher=lambda: 1500, now_ms=lambda: local[0])

        self.assertFalse(clock.synced)
        self.assertEqual(clock.sync(), 500)  # 1500 - 1000
        self.assertTrue(clock.synced)
        self.assertEqual(clock.offset_ms, 500)
        self.assertEqual(clock.timestamp(), 1500)  # now(1000) + offset(500)

        local[0] = 2000
        self.assertEqual(clock.timestamp(), 2500)  # now(2000) + offset(500)

    def test_negative_offset(self):
        clock = ServerClock(time_fetcher=lambda: 900, now_ms=lambda: 1000)
        self.assertEqual(clock.sync(), -100)
        self.assertEqual(clock.timestamp(), 900)


if __name__ == "__main__":
    unittest.main()
