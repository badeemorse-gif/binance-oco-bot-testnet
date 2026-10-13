import os
import tempfile
import unittest

from ocobot.core.environment import Environment
from ocobot.core.errors import KeysError
from ocobot.core.keys import ApiCredentials, load_credentials, parse_keyfile

SAMPLE = """# keys file
TESTNET_KEY=tkey123456789
TESTNET_SECRET=tsecretABCDEFGH
LIVE_KEY=lkey987654321
LIVE_SECRET=lsecretZYXWVU
"""


class TestKeys(unittest.TestCase):
    def _write(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_parse(self):
        data = parse_keyfile(SAMPLE)
        self.assertEqual(data["TESTNET_KEY"], "tkey123456789")
        self.assertEqual(data["LIVE_SECRET"], "lsecretZYXWVU")

    def test_load_testnet(self):
        creds = load_credentials(self._write(SAMPLE), Environment.TESTNET)
        self.assertEqual(creds.api_key, "tkey123456789")
        self.assertEqual(creds.api_secret, "tsecretABCDEFGH")

    def test_load_live(self):
        creds = load_credentials(self._write(SAMPLE), "live")
        self.assertEqual(creds.api_key, "lkey987654321")

    def test_missing_file(self):
        with self.assertRaises(KeysError):
            load_credentials("D:/definitely/not/here/key.txt", Environment.TESTNET)

    def test_missing_env_keys(self):
        with self.assertRaises(KeysError):
            load_credentials(self._write("TESTNET_KEY=only\n"), Environment.TESTNET)

    def test_redaction_never_leaks(self):
        creds = ApiCredentials(api_key="tkey123456789", api_secret="supersecretvalue")
        text = repr(creds) + str(creds)
        self.assertNotIn("supersecretvalue", text)  # secret never shown
        self.assertNotIn("tkey123456789", text)     # full key never shown


if __name__ == "__main__":
    unittest.main()
