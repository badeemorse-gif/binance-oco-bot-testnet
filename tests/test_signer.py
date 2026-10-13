import unittest

from ocobot.core.signer import build_query, sign, signed_query


class TestSigner(unittest.TestCase):
    # Known-answer vector from Binance SPOT API docs (HMAC SHA256 example).
    SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    QS = (
        "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1"
        "&price=0.1&recvWindow=5000&timestamp=1499827319559"
    )
    EXPECTED = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"

    PARAMS = [
        ("symbol", "LTCBTC"),
        ("side", "BUY"),
        ("type", "LIMIT"),
        ("timeInForce", "GTC"),
        ("quantity", 1),
        ("price", "0.1"),
        ("recvWindow", 5000),
        ("timestamp", 1499827319559),
    ]

    def test_known_answer(self):
        self.assertEqual(sign(self.QS, self.SECRET), self.EXPECTED)

    def test_build_query_preserves_order(self):
        self.assertEqual(build_query(self.PARAMS), self.QS)

    def test_signed_query_appends_signature(self):
        out = signed_query(self.PARAMS, self.SECRET)
        self.assertEqual(out, f"{self.QS}&signature={self.EXPECTED}")


if __name__ == "__main__":
    unittest.main()
