"""عميل REST كسول للحارس (Guardian lazy REST client) — طبقة core.

نُقل من ``ocobot/ui/guardian_arm.py`` إلى طبقة ``core`` حفاظًا على ثابتة
المعمارية P2/P3: طبقة الواجهة (``ocobot/ui``) لا تنفّذ أي نداء شبكي مباشر؛ كل IO
يمرّ عبر طبقة الخدمات/الـ core. هذه الوحدة إضافية بحتة وخارج المسار الحار تمامًا،
ولا تكشف أي دالة إلغاء إطلاقًا.
"""
from __future__ import annotations


class LazyGuardianRestClient:
    """عميل REST كسول يحقّق الدوال الثلاث التي يحتاجها ``GuardianBroker`` فقط.

    يعيد بناء العميل الحيّ عند كل نداء (ليعكس مفاتيح الجلسة بعد الاتصال)، ويُعيد
    قيمًا آمنة (قائمة فارغة / قاموس فارغ) إن لم يكن الاتصال جاهزًا بعد — فلا يكسر
    دورة الإشراف. **لا يكشف أي دالة إلغاء إطلاقًا.**
    """

    @staticmethod
    def _client():
        from ocobot.config import AppConfig
        from ocobot.core.connection import build_gui_client

        return build_gui_client(AppConfig.from_env_vars())

    def get_open_orders(self, symbol):
        try:
            return self._client().get_open_orders(symbol) or []
        except Exception:
            return []

    def get_account(self):
        try:
            return self._client().get_account() or {}
        except Exception:
            return {}

    def signed_request(self, method, path, params):
        # يُستدعى فقط في وضع live عند التدخّل الفعلي؛ أي استثناء يُدار ويُغلَّف
        # داخل GuardianSupervisor._intervene (best-effort) فلا يكسر الإشراف.
        return self._client().signed_request(method, path, params)
