"""Preflight — تحقق عند الإقلاع (Deliverable 4.6).

الخطوات: (1) تحميل المفاتيح للبيئة المختارة، (2) مزامنة serverTime (offset)،
(3) نداء موقّع خفيف GET /api/v3/account. يعيد ConnectionState مرئيًا.
لا يطبع/يُسجّل أي سر، ولا يُدرِج الأرصدة في الحالة.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ocobot.config import AppConfig
from ocobot.core.connection_state import ConnectionState, ConnectionStatus
from ocobot.core.errors import BinanceApiError, KeysError, TransportError
from ocobot.core.failure_matrix import humanize
from ocobot.core.keys import ApiCredentials, load_credentials
from ocobot.core.rest_client import SignedRestClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _interpret(err: BinanceApiError) -> str:
    """يمرّر كل الأخطاء عبر مصفوفة الفشل الموحّدة (T7) — لا نصّ Binance خام.

    -2014/-2015 (مفتاح API غير مسموح) تُعالَج هنا برسالة عربية بشرية محدّدة
    ثمّ يتولّى ``humanize`` بقية الحالات (‎-1021/-1022/429/418/fallback آمن).
    """
    if err.code in (-2014, -2015):
        return (
            "مفتاح API غير صالح أو غير مسموح ({code}): راجع صحّة المفتاح، "
            "صلاحياته (تداول فقط)، وقائمة IP."
        ).format(code=err.code)
    return humanize(err)


def run_preflight(
    config: AppConfig,
    transport=None,
    now_ms=None,
    credentials: Optional[ApiCredentials] = None,
) -> ConnectionState:
    state = ConnectionState(
        status=ConnectionStatus.CONNECTING,
        environment=config.env,
        rest_base=config.rest_base(),
    )

    # 1) المفاتيح للبيئة المختارة
    try:
        creds = credentials or load_credentials(config.keys_path, config.env)
    except KeysError as exc:
        state.status = ConnectionStatus.ERROR
        state.message = str(exc)
        state.checked_at = _now_iso()
        return state
    state.key_hint = creds.masked_key()

    client = SignedRestClient(config, creds, transport=transport, now_ms=now_ms)
    try:
        # 2) مزامنة الوقت (serverTime -> offset) قبل التوقيع
        state.clock_offset_ms = client.sync_time()
        # 3) نداء موقّع خفيف
        account = client.get_account()
        state.status = ConnectionStatus.CONNECTED
        state.message = "الاتصال ناجح: المفتاح والتوقيع صحيحان للبيئة المختارة."
        # حقول غير حساسة فقط (لا أرصدة)
        state.detail = {
            "canTrade": account.get("canTrade"),
            "accountType": account.get("accountType"),
            "permissions": account.get("permissions"),
        }
        if client.last_used_weight is not None:
            state.detail["usedWeight"] = client.last_used_weight
    except BinanceApiError as exc:
        state.status = ConnectionStatus.ERROR
        state.message = _interpret(exc)
    except TransportError as exc:
        state.status = ConnectionStatus.ERROR
        state.message = humanize(exc)  # لا نصّ استثناء خام (T7)
    except Exception as exc:  # مظلّة أمان: لا استثناء خام يصعد للمستخدم (T7)
        state.status = ConnectionStatus.ERROR
        state.message = humanize(exc)

    state.checked_at = _now_iso()
    return state
