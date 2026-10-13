"""اختبار عيب G1.35 (offscreen، بلا شبكة).

يُثبت أنّ لكل مستلم في بطاقة التنبيهات زرّ «حذف» فردي:
  - يظهر زرّ حذف واحد لكل مستلم (AlertsDeleteRecipientButton).
  - الحذف يزيل المستلم من التخزين الدائم (AlertsStore) ومن قائمة الواجهة فورًا.
  - ضغط الزرّ فعليًّا يُطلق الحذف.
  - ``Notifier`` يقرأ recipients_provider حيًّا ⇒ المستلم المحذوف لا يبقى في القائمة
    التي يُرسِل إليها (لا تسرّب رسائل لمستلم قديم).

نفس بيئة اختبارات الواجهة: منصّة offscreen، QApplication وحيد، AlertsStore بمسار
مؤقّت محقون، AlertsScreen(runner=None).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from ocobot.ui._qt import QApplication, QPushButton
from ocobot.ui.theme import apply_theme
from ocobot.ui.alerts import AlertsScreen
from ocobot.alerts.storage import AlertsStore
from ocobot.alerts.notifier import Notifier


class DeleteRecipientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _store(self):
        d = tempfile.mkdtemp(prefix="oco_g135_")
        return AlertsStore(
            path=os.path.join(d, "alerts.json"),
            token_path=os.path.join(d, ".ocobot_telegram_token"),
        )

    def _screen_with_two(self):
        store = self._store()
        store.add_recipient("100", "alice")
        store.add_recipient("200", "bob")
        screen = AlertsScreen(runner=None, store=store)
        return screen, store

    def test_per_recipient_delete_buttons_exist(self):
        screen, _store = self._screen_with_two()
        btns = screen.findChildren(QPushButton, "AlertsDeleteRecipientButton")
        self.assertEqual(len(btns), 2)
        self.assertEqual(screen.recipients_list.count(), 2)
        self.assertEqual(
            sorted(b.property("chat_id") for b in btns), ["100", "200"]
        )

    def test_delete_removes_from_store_and_ui(self):
        screen, store = self._screen_with_two()
        screen._on_delete_recipient("100")
        # أُزيل من التخزين الدائم فورًا.
        self.assertEqual(store.recipients_provider(), ["200"])
        # وأُزيل من قائمة الواجهة: نفحص عناصر القائمة الحيّة فقط (بلا حلقة أحداث قد
        # تبقى عناصر pending-delete قديمة كأبناء، لذا لا نعتمد على findChildren).
        self.assertEqual(screen.recipients_list.count(), 1)
        live_ids = []
        for i in range(screen.recipients_list.count()):
            it = screen.recipients_list.item(i)
            w = screen.recipients_list.itemWidget(it)
            btn = w.findChild(QPushButton, "AlertsDeleteRecipientButton") if w else None
            if btn is not None:
                live_ids.append(btn.property("chat_id"))
        self.assertEqual(live_ids, ["200"])

    def test_delete_button_click_triggers_removal(self):
        screen, store = self._screen_with_two()
        target = [
            b for b in screen.findChildren(QPushButton, "AlertsDeleteRecipientButton")
            if b.property("chat_id") == "100"
        ][0]
        target.click()
        self.assertEqual(store.recipients_provider(), ["200"])

    def test_notifier_live_list_excludes_deleted(self):
        screen, store = self._screen_with_two()
        notifier = Notifier(
            client_provider=lambda: None,
            recipients_provider=store.recipients_provider,
        )
        self.assertIn("100", list(notifier._recipients_provider()))
        screen._on_delete_recipient("100")
        # القائمة الحيّة التي يُرسِل إليها المُنبِّه لم تعد تشمل المحذوف.
        self.assertNotIn("100", list(notifier._recipients_provider()))
        self.assertEqual(list(notifier._recipients_provider()), ["200"])


if __name__ == "__main__":
    unittest.main()
