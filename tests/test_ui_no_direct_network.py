import glob
import os
import unittest

# Directory holding the UI layer modules.
_UI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ocobot",
    "ui",
)

# Forbidden markers: the UI layer must make NO direct network calls — all IO
# goes through the services layer via the async runner (T10c acceptance #3).
_FORBIDDEN = (
    "urllib",
    "http.client",
    "import socket",
    "SignedRestClient(",
    ".signed_request(",
    ".public_request(",
)


class UINoDirectNetworkTests(unittest.TestCase):
    def test_ui_layer_has_no_direct_network(self):
        files = sorted(glob.glob(os.path.join(_UI_DIR, "*.py")))
        self.assertTrue(files, "expected to find ocobot/ui/*.py modules")
        offenders = []
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            for marker in _FORBIDDEN:
                if marker in source:
                    offenders.append((os.path.basename(path), marker))
        self.assertEqual(
            offenders,
            [],
            "UI layer must not contain direct-network markers: %r" % (offenders,),
        )


if __name__ == "__main__":
    unittest.main()
