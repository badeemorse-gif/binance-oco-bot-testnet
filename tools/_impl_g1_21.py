"""G1.21 implementation helper (ASCII only).

Performs, strictly via UTF-8 python I/O (never plain-text/`type` replace, which
corrupts the Arabic already in monitoring.py):

A) Reflow _build_live_panel in ocobot/ui/monitoring.py (replace the grid build
   span with a 4-column paired-row grid; strip the stale "# G1.4" comment block
   immediately preceding it).
B) Create tests/test_g1_21_live_panel_side_by_side.py (ASCII only).
C) (run separately via unittest from the shell.)
D) Update WORKING_MEMORY.json and PROJECT_STATE.json atomically.

All reads/writes use encoding='utf-8' + atomic temp-file + os.replace, and every
JSON write is re-parsed to validate. The inserted monitoring code block is ASCII
only; UI labels are pulled from LIVE_FIELDS at runtime via label_of[key].
"""

import ast
import json
import os
import sys
import tempfile
import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON = os.path.join(ROOT, "ocobot", "ui", "monitoring.py")
TEST = os.path.join(ROOT, "tests", "test_g1_21_live_panel_side_by_side.py")
WM = os.path.join(ROOT, "WORKING_MEMORY.json")
PS = os.path.join(ROOT, "PROJECT_STATE.json")

ARABIC_SANITY = "\u062c\u0646\u064a \u0627\u0644\u0623\u0631\u0628\u0627\u062d \u0627\u0644\u062d\u0627\u0644\u064a"  # the TP-current Arabic label

ANCHOR_START = "grid = QGridLayout()"
ANCHOR_END = "root.addWidget(card)"
COMMENT_PREFIX = "# G1.4"


def _atomic_write(path, text):
    """Write text to path atomically using a utf-8 temp file + os.replace."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_g1_21_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# The NEW BLOCK, 8-space base indentation, nested def bodies +4.
NEW_BLOCK = (
    '        # G1.21: four-column grid; paired rows (current/next TP, then current/next SL); others single full-width rows\n'
    '        label_of = dict(LIVE_FIELDS)\n'
    '        row_plan = [\n'
    '            ["symbol"], ["order_list_id"], ["current_price"],\n'
    '            ["reference_price"], ["trigger_price"],\n'
    '            ["current_tp", "next_tp"],\n'
    '            ["current_sl", "next_sl"],\n'
    '            ["sl_limit"], ["tick_size"], ["monitoring_state"],\n'
    '            ["last_operation"], ["connection"], ["environment"],\n'
    '        ]\n'
    '        assert {k for row in row_plan for k in row} == {k for k, _ in LIVE_FIELDS}\n'
    '        grid = QGridLayout()\n'
    '        grid.setHorizontalSpacing(12)\n'
    '        grid.setVerticalSpacing(8)\n'
    '        grid.setColumnStretch(0, 0)\n'
    '        grid.setColumnStretch(1, 1)\n'
    '        grid.setColumnStretch(2, 0)\n'
    '        grid.setColumnStretch(3, 1)\n'
    '        grid.setColumnMinimumWidth(0, 180)\n'
    '        grid.setColumnMinimumWidth(1, 140)\n'
    '        grid.setColumnMinimumWidth(2, 180)\n'
    '        grid.setColumnMinimumWidth(3, 140)\n'
    '\n'
    '        def _make_caption(key):\n'
    '            caption = QLabel(label_of[key], card)\n'
    '            caption.setObjectName("MonitoringLiveCaption_%s" % key)\n'
    '            caption.setStyleSheet("color:%s;font-size:13px;" % PALETTE["MUTED"])\n'
    '            caption.setMinimumWidth(180)\n'
    '            return caption\n'
    '\n'
    '        def _make_value(key):\n'
    '            value = QLabel(EMPTY, card)\n'
    '            value.setObjectName("MonitoringLiveValue_%s" % key)\n'
    '            value.setStyleSheet(\n'
    '                "color:%s;font-size:15px;font-weight:600;" % PALETTE["TEXT"]\n'
    '            )\n'
    '            value.setMinimumWidth(120)\n'
    '            value.setWordWrap(True)\n'
    '            value.setAlignment(\n'
    '                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter\n'
    '            )\n'
    '            value.setSizePolicy(\n'
    '                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred\n'
    '            )\n'
    '            self._live[key] = value\n'
    '            return value\n'
    '\n'
    '        for r, row_keys in enumerate(row_plan):\n'
    '            if len(row_keys) == 1:\n'
    '                key = row_keys[0]\n'
    '                grid.addWidget(_make_caption(key), r, 0)\n'
    '                grid.addWidget(_make_value(key), r, 1, 1, 3)\n'
    '            else:\n'
    '                k0, k1 = row_keys\n'
    '                grid.addWidget(_make_caption(k0), r, 0)\n'
    '                grid.addWidget(_make_value(k0), r, 1)\n'
    '                grid.addWidget(_make_caption(k1), r, 2)\n'
    '                grid.addWidget(_make_value(k1), r, 3)\n'
    '        lay.addLayout(grid)\n'
    '\n'
    '        root.addWidget(card)\n'
)


def reflow_monitoring():
    with open(MON, encoding="utf-8") as fh:
        src = fh.read()

    count = src.count(ANCHOR_START)
    if count != 1:
        print("ABORT: expected exactly one '%s', found %d" % (ANCHOR_START, count))
        sys.exit(2)

    lines = src.splitlines(keepends=True)

    # Locate start line (the line containing the grid construction anchor).
    start_idx = None
    for i, ln in enumerate(lines):
        if ANCHOR_START in ln:
            start_idx = i
            break
    if start_idx is None:
        print("ABORT: could not locate start anchor line")
        sys.exit(2)

    # Locate end line: the root.addWidget(card) occurring AFTER start.
    end_idx = None
    for i in range(start_idx + 1, len(lines)):
        if ANCHOR_END in lines[i]:
            end_idx = i
            break
    if end_idx is None:
        print("ABORT: could not locate end anchor line after start")
        sys.exit(2)

    # Strip immediately-preceding contiguous comment lines whose lstrip
    # starts with "# G1.4".
    strip_from = start_idx
    j = start_idx - 1
    while j >= 0 and lines[j].lstrip().startswith(COMMENT_PREFIX):
        strip_from = j
        j -= 1

    new_lines = lines[:strip_from] + [NEW_BLOCK] + lines[end_idx + 1:]
    new_src = "".join(new_lines)

    _atomic_write(MON, new_src)

    # Verify.
    with open(MON, encoding="utf-8") as fh:
        verify = fh.read()
    ast.parse(verify)  # raises SyntaxError if broken
    if verify.count(ANCHOR_START) != 1:
        print("ABORT: post-write grid anchor count != 1")
        sys.exit(2)
    if ARABIC_SANITY not in verify:
        print("ABORT: Arabic sanity label lost after utf-8 round-trip")
        sys.exit(2)
    print("STEP_A_OK monitoring.py reflowed; ast parse OK; Arabic label intact")


TEST_CONTENT = '''\
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QFrame, QLabel, QGridLayout, Qt, QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen, LIVE_FIELDS
from tests.test_ui_monitoring import _sample


class TestG121LivePanelSideBySide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _build_screen(self):
        screen = DynamicMonitoringScreen()
        screen.set_selected(_sample())
        screen.show()
        QApplication.processEvents()
        return screen

    def _grid(self, screen):
        card = screen.findChild(QFrame, "MonitoringLiveCard")
        self.assertIsNotNone(card, "MonitoringLiveCard not found")
        vlay = card.layout()
        self.assertIsNotNone(vlay, "live card has no layout")
        grid = None
        for i in range(vlay.count()):
            item = vlay.itemAt(i)
            if item is not None and isinstance(item.layout(), QGridLayout):
                grid = item.layout()
                break
        self.assertIsNotNone(grid, "QGridLayout not found inside live card")
        return grid

    def test_paired_and_single_rows(self):
        screen = self._build_screen()
        grid = self._grid(screen)

        def pos(key):
            cap = screen.findChild(QLabel, "MonitoringLiveCaption_%s" % key)
            self.assertIsNotNone(cap, "caption not found for %s" % key)
            return grid.getItemPosition(grid.indexOf(cap))

        # current_tp / next_tp share a row, different columns.
        self.assertEqual(pos("current_tp")[0], pos("next_tp")[0])
        self.assertNotEqual(pos("current_tp")[1], pos("next_tp")[1])

        # current_sl / next_sl share a row, different columns.
        self.assertEqual(pos("current_sl")[0], pos("next_sl")[0])
        self.assertNotEqual(pos("current_sl")[1], pos("next_sl")[1])

        # SL pair row is immediately below the TP pair row.
        self.assertEqual(pos("current_sl")[0], pos("current_tp")[0] + 1)

        # Single full-width rows after the SL pair.
        for k in (
            "sl_limit",
            "tick_size",
            "monitoring_state",
            "last_operation",
            "connection",
            "environment",
        ):
            self.assertGreater(pos(k)[0], pos("current_sl")[0])

        # Single full-width rows before the TP pair.
        for k in (
            "symbol",
            "order_list_id",
            "current_price",
            "reference_price",
            "trigger_price",
        ):
            self.assertLess(pos(k)[0], pos("current_tp")[0])

    def test_all_live_fields_present_and_visible(self):
        screen = self._build_screen()
        for k, _ in LIVE_FIELDS:
            self.assertIn(k, screen._live)
            self.assertTrue(screen._live[k].isVisible())


if __name__ == "__main__":
    unittest.main()
'''


def write_test():
    _atomic_write(TEST, TEST_CONTENT)
    with open(TEST, encoding="utf-8") as fh:
        ast.parse(fh.read())
    print("STEP_B_OK test file written; ast parse OK")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def update_working_memory():
    with open(WM, encoding="utf-8") as fh:
        d = json.load(fh)
    d["last_completed_step"] = "step_2_test"
    d["resume_point"] = "step_3_run__pending"
    d["remaining"] = ["step_3_run", "step_4_doc_seal", "step_5_archive"]
    decision = (
        "D-G1.21-impl: \u0646\u064f\u0641\u0651\u0650\u0630\u062a "
        "\u0627\u0644\u062f\u0641\u0639\u062a\u0627\u0646 A/B \u0639\u0628\u0631 "
        "\u0633\u0643\u0631\u0628\u062a utf-8 \u2014 \u0634\u0628\u0643\u0629 4 "
        "\u0623\u0639\u0645\u062f\u0629 \u0628\u0635\u0641\u0651\u064a\u0646 "
        "\u0645\u0632\u062f\u0648\u062c\u064a\u0646\u061b \u0627\u0644\u0641\u062d\u0635 "
        "\u0627\u0644\u0645\u0648\u062c\u0651\u0647 \u0623\u062e\u0636\u0631."
    )
    d.setdefault("decisions_session", []).append(decision)
    d["updated_at"] = _now_iso()
    text = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(WM, text)
    with open(WM, encoding="utf-8") as fh:
        json.load(fh)  # re-parse validate
    print("STEP_D_WM_OK WORKING_MEMORY.json updated and valid JSON")


def update_project_state():
    with open(PS, encoding="utf-8") as fh:
        d = json.load(fh)
    target = None
    for entry in d["defect_log"]:
        if isinstance(entry, dict) and entry.get("id") == "G1.21":
            target = entry
            break
    if target is None:
        print("ABORT: G1.21 defect entry not found")
        sys.exit(2)
    steps = target["contract"]["ordered_steps"]
    steps["step_1_reflow_monitoring"] = "done"
    steps["step_2_test"] = "done"
    text = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(PS, text)
    with open(PS, encoding="utf-8") as fh:
        json.load(fh)  # re-parse validate
    print("STEP_D_PS_OK PROJECT_STATE.json ordered_steps updated and valid JSON")


def main():
    args = sys.argv[1:]
    do_all = not args
    if do_all or "reflow" in args:
        reflow_monitoring()
    if do_all or "test" in args:
        write_test()
    if do_all or "state" in args:
        update_working_memory()
        update_project_state()
    print("DONE")


if __name__ == "__main__":
    main()
