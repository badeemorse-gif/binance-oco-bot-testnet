"""Failure → human Arabic message mapping (T5 / M4).

طبقة تحويل تربط حالات الأخطاء/الاستثناءات إلى رسائل عربية مقروءة بحيث لا يظهر
للمستخدم أبدًا نصّ استثناء خام أو stack trace (معيار القبول: "No raw Exception
messages"). تدعم على الأقل:
  - Binance -1021 (timestamp/recvWindow)
  - Binance -1022 (signature)
  - HTTP 429 (rate limit)
  - HTTP 418 (IP ban / backoff)
  - الحالة الداخلية FAILED_NEEDS_ATTENTION (Cancel نجح + Create فشل — D9)
  - fallback عربي آمن لأي خطأ غير معروف (لا يُعيد النصّ الخام إطلاقًا)

لا تُسجَّل ولا تُعاد أي أسرار (D8): المخرجات رسائل ثابتة معدّة مسبقًا، ولا نضمّن
نصّ الاستثناء الخام في الرسالة الموجَّهة للمستخدم.
"""
from __future__ import annotations

from typing import Optional

from ocobot.core.errors import BinanceApiError, OcoBotError, TransportError

# الحالة الداخلية (تطابق ExecutionState.FAILED_NEEDS_ATTENTION قيمةً) — D9.
FAILED_NEEDS_ATTENTION = "FAILED_NEEDS_ATTENTION"

# رسائل بشرية عربية ثابتة — لا نصّ خام، لا stack trace.
MSG_1021 = (
    "الطابع الزمني خارج نافذة recvWindow (-1021): تمّت إعادة مزامنة ساعة الخادم؛ "
    "إن تكرّر الخطأ فتحقّق من ضبط ساعة الجهاز."
)
MSG_1022 = (
    "توقيع الطلب غير صالح (-1022): تحقّق من صحّة السر (Secret) وترتيب البارامترات. "
    "لن تُعاد المحاولة تلقائيًا."
)
MSG_429 = (
    "تجاوزت حدّ معدّل الطلبات (429): تمهّل قليلًا قبل إعادة المحاولة "
    "(rate limit)."
)
MSG_418 = (
    "تمّ حظر عنوان IP مؤقتًا بسبب كثرة الطلبات (418): انتظر فترة التهدئة "
    "(backoff) قبل أي محاولة جديدة."
)
MSG_FAILED_NEEDS_ATTENTION = (
    "تمّ إلغاء الأمر المحدّد، لكن إنشاء البديل فشل — لا توجد إعادة محاولة تلقائية "
    "(No Blind Retry). تدخّل يدوي مطلوب. (D9)"
)
MSG_TRANSPORT = (
    "تعذّر الوصول إلى Binance (مشكلة شبكة/اتصال): تحقّق من الإنترنت ثم أعد "
    "المحاولة."
)
# fallback آمن — يُستخدم لأي خطأ غير معروف بلا كشف تفاصيل خام.
MSG_FALLBACK = (
    "حدث خطأ غير متوقّع أثناء تنفيذ العملية. تمّ إيقاف الإجراء بأمان؛ يُرجى "
    "المحاولة لاحقًا أو مراجعة السجل (Audit Log)."
)

# جدول أكواد Binance الحرجة → رسالة عربية.
_BINANCE_CODE_MESSAGES = {
    -1021: MSG_1021,
    -1022: MSG_1022,
}
# جدول أكواد HTTP → رسالة عربية.
_HTTP_STATUS_MESSAGES = {
    429: MSG_429,
    418: MSG_418,
}


class FailureMatrix:
    """مُحوِّل الحالات إلى رسائل عربية بشرية (بلا نصّ خام)."""

    @staticmethod
    def humanize(err: object) -> str:
        """يعيد رسالة عربية غير فارغة لأي خطأ/حالة، دون كشف النصّ الخام.

        يقبل: ``BinanceApiError`` (code / http_status)، ``TransportError``،
        السلسلة ``"FAILED_NEEDS_ATTENTION"`` أو أي كائن يحمل ``state`` بهذه القيمة،
        رقم كود Binance، رقم HTTP، أو أي استثناء/قيمة أخرى (⇒ fallback آمن).
        """
        # 1) الحالة الداخلية FAILED_NEEDS_ATTENTION (D9).
        if _is_failed_needs_attention(err):
            return MSG_FAILED_NEEDS_ATTENTION

        # 2) خطأ Binance مُصنَّف (code سالب + http_status).
        if isinstance(err, BinanceApiError):
            if err.code in _BINANCE_CODE_MESSAGES:
                return _BINANCE_CODE_MESSAGES[err.code]
            if err.http_status in _HTTP_STATUS_MESSAGES:
                return _HTTP_STATUS_MESSAGES[err.http_status]
            return MSG_FALLBACK

        # 3) خطأ نقل/شبكة.
        if isinstance(err, TransportError):
            return MSG_TRANSPORT

        # 4) كود عددي مباشر (Binance code سالب أو HTTP status).
        code = _coerce_int(err)
        if code is not None:
            if code in _BINANCE_CODE_MESSAGES:
                return _BINANCE_CODE_MESSAGES[code]
            if code in _HTTP_STATUS_MESSAGES:
                return _HTTP_STATUS_MESSAGES[code]

        # 5) أي استثناء/قيمة غير معروفة ⇒ fallback آمن (لا نصّ خام إطلاقًا).
        return MSG_FALLBACK


def humanize(err: object) -> str:
    """واجهة دالّية مختصرة تعادل ``FailureMatrix.humanize``."""
    return FailureMatrix.humanize(err)


def _is_failed_needs_attention(err: object) -> bool:
    if isinstance(err, str):
        return err == FAILED_NEEDS_ATTENTION
    # كائن حالة تنفيذ يحمل state (Enum بقيمة نصّية) أو خاصية value.
    state = getattr(err, "state", None)
    if state is not None:
        value = getattr(state, "value", state)
        if value == FAILED_NEEDS_ATTENTION:
            return True
    value = getattr(err, "value", None)
    return value == FAILED_NEEDS_ATTENTION


def _coerce_int(err: object) -> Optional[int]:
    if isinstance(err, bool):  # bool فرع من int — نتجاهله صراحةً.
        return None
    if isinstance(err, int):
        return err
    return None
