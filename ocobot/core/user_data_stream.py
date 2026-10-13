"""دورة حياة listenKey — User Data Stream (M4e/1 · T9a).

النطاق (D20): إدارة listenKey عبر مصادقة مفتاح فقط (X-MBX-APIKEY) دون توقيع
HMAC — create (POST) / keepalive (PUT) / close (DELETE) على
/api/v3/userDataStream، مع تجديد تلقائي (keepalive) قبل ~30م عبر ساعة قابلة
للحقن (نمط ServerClock — لا time/sleep حقيقي). stdlib فقط.

أمان (D8/P): لا يُسجَّل أو يُكشَف api_key أو listenKey في أي log/خطأ — تُقنَّع
عبر أدوات redaction القائمة.

لا WS ولا تحليل أحداث هنا (ذلك نطاق T9b). لا إعادة اتصال (T9c).
"""
from __future__ import annotations

import logging
from typing import Optional

from ocobot.core.errors import OcoBotError
from ocobot.core.redaction import mask_key

log = logging.getLogger("ocobot.userdata")

PATH_USER_DATA_STREAM = "/api/v3/userDataStream"

# keepalive قبل ~30م من عتبة الانتهاء (~60م). نجدّد عند مرور هذه المدة منذ آخر
# نشاط لنبقى في الجانب الآمن قبل علامة ~30م.
KEEPALIVE_INTERVAL_MS = 25 * 60 * 1000  # 25 دقيقة


class ListenKeyError(OcoBotError):
    """فشل في دورة حياة listenKey (create/keepalive/close)."""


class ListenKeyManager:
    """يدير دورة حياة listenKey بمصادقة مفتاح فقط (بلا توقيع HMAC) + تجديد تلقائي.

    - create() → POST يُنشئ ويخزّن listenKey.
    - keepalive() → PUT يمدّد الصلاحية (~60م)؛ يُستدعى قبل علامة ~30م.
    - close() → DELETE يحرّر المفتاح.
    - maybe_keepalive(now_ms) → يُطلِق keepalive تلقائيًا إذا انقضت المدّة منذ
      آخر نشاط، اعتمادًا على الساعة المحقونة فقط.

    الساعة تُحقَن كدالة now_ms() (نمط ServerClock) لتفادي time/sleep الحقيقي
    وليكون التوقيت قابلًا للاختبار بلا شبكة.
    """

    def __init__(self, client, now_ms, keepalive_interval_ms: int = KEEPALIVE_INTERVAL_MS):
        self._client = client
        self._now_ms = now_ms
        self._interval_ms = int(keepalive_interval_ms)
        self._listen_key: Optional[str] = None
        self._last_keepalive_ms: Optional[int] = None

    @property
    def listen_key(self) -> Optional[str]:
        return self._listen_key

    @property
    def active(self) -> bool:
        return self._listen_key is not None

    @property
    def last_keepalive_ms(self) -> Optional[int]:
        return self._last_keepalive_ms

    # ---- lifecycle ----
    def create(self) -> str:
        """POST /api/v3/userDataStream — ينشئ listenKey ويخزّنه ويعيده."""
        data = self._client.keyed_request("POST", PATH_USER_DATA_STREAM)
        key = data.get("listenKey") if isinstance(data, dict) else None
        if not key:
            # لا نُدرِج جسم الرد الخام تفاديًا لأي تسريب محتمل للمفتاح.
            raise ListenKeyError("ردّ إنشاء listenKey غير صالح (لا يحتوي listenKey).")
        self._listen_key = key
        self._last_keepalive_ms = self._now_ms()
        log.info("listenKey created (%s)", mask_key(key))
        return key

    def keepalive(self) -> None:
        """PUT /api/v3/userDataStream — يمدّد صلاحية listenKey (~60م)."""
        if not self._listen_key:
            raise ListenKeyError("لا يوجد listenKey نشط لتمديده (استدعِ create أولًا).")
        self._client.keyed_request(
            "PUT", PATH_USER_DATA_STREAM, [("listenKey", self._listen_key)]
        )
        self._last_keepalive_ms = self._now_ms()
        log.info("listenKey keepalive (%s)", mask_key(self._listen_key))

    def close(self) -> None:
        """DELETE /api/v3/userDataStream — يحرّر listenKey."""
        if not self._listen_key:
            return
        key = self._listen_key
        self._client.keyed_request(
            "DELETE", PATH_USER_DATA_STREAM, [("listenKey", key)]
        )
        self._listen_key = None
        self._last_keepalive_ms = None
        log.info("listenKey closed (%s)", mask_key(key))

    # ---- auto-renew (injected clock) ----
    def due_for_keepalive(self, now_ms: Optional[int] = None) -> bool:
        """هل حان موعد keepalive؟ (انقضت المدّة منذ آخر نشاط) اعتمادًا على الساعة المحقونة."""
        if not self._listen_key or self._last_keepalive_ms is None:
            return False
        now = self._now_ms() if now_ms is None else now_ms
        return (now - self._last_keepalive_ms) >= self._interval_ms

    def maybe_keepalive(self, now_ms: Optional[int] = None) -> bool:
        """يُطلِق keepalive إذا حان موعده. يعيد True عند التنفيذ الفعلي."""
        if self.due_for_keepalive(now_ms):
            self.keepalive()
            return True
        return False

    # للتوافق مع أسماء الاستدعاء المتوقّعة من حلقة المستهلك (T9b).
    ensure_active = maybe_keepalive
