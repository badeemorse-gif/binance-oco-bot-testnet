"""Read-only connection test (G1.11 — core, non-UI).

يحلّ مصدر المفاتيح (حقول ← ملف مختار فقط)، يبني عميلًا
موقّعًا، ثم يستدعي ``get_account()`` (قراءة فقط، /api/v3/account) للتحقق من
الاتصال والمفاتيح. لا يُسرَّب أي سر مطلقًا: لا نُدرِج api_secret في أي رسالة،
ونعتمد على repr المقنّع أو رسائل عامة/نوع الخطأ فقط.

قابلة للاستدعاء دون شبكة في الاختبارات عبر حقن ``client_factory`` يعيد عميلًا
مزيّفًا. لا لمس لمنطق التوقيع ولا لمسارات التداول.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ocobot.core.errors import KeysError
from ocobot.core.keys import ApiCredentials, CredentialsError, resolve_credentials
from ocobot.core.rest_client import build_signed_client
from ocobot.core.connection_state import ConnectionState, ConnectionStatus


@dataclass
class ConnectionResult:
    ok: bool
    message: str


def test_connection(
    cfg,
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    keys_path: Optional[str] = None,
    client_factory: Optional[Callable[[object, ApiCredentials], object]] = None,
) -> ConnectionResult:
    """يجرّب الاتصال (قراءة فقط) ويعيد ``ConnectionResult``.

    - يحلّ المفاتيح عبر ``resolve_credentials`` (حقول ← ملف مختار فقط).
    - يبني العميل عبر ``client_factory`` (للاختبارات) أو ``build_signed_client``.
    - يستدعي ``client.get_account()`` (لا كتابة).
    - نجاح ← ``ConnectionResult(True, "متصل")``.
    - أي استثناء ← ``ConnectionResult(False, رسالة عربية موجزة)`` دون تسريب سر.
    """
    try:
        creds = resolve_credentials(
            cfg.env,
            api_key=api_key,
            api_secret=api_secret,
            keys_path=keys_path,
        )
    except CredentialsError as exc:
        # رسالة CredentialsError عامة ولا تحوي أسرارًا.
        return ConnectionResult(False, str(exc))
    except KeysError as exc:
        return ConnectionResult(False, str(exc))
    except Exception:
        return ConnectionResult(False, "تعذّر تحديد مصدر المفاتيح")

    try:
        factory = client_factory or build_signed_client
        client = factory(cfg, creds)
        client.get_account()
    except CredentialsError as exc:
        return ConnectionResult(False, str(exc))
    except KeysError as exc:
        return ConnectionResult(False, str(exc))
    except FileNotFoundError:
        return ConnectionResult(False, "مسار المفاتيح غير متاح")
    except Exception as exc:
        # رسالة عامة بنوع الخطأ فقط — لا نُدرِج قيَم المفاتيح إطلاقًا.
        return ConnectionResult(False, f"فشل الاتصال: {type(exc).__name__}")

    return ConnectionResult(True, "متصل")


test_connection.__test__ = False


def build_gui_client(cfg, source=None):
    """يبني عميلًا موقّعًا للواجهة من مصدر مفاتيح الجلسة (أو ``source`` المحقون).

    الأولوية: الحقول ← الملف المختار فقط (لا مسار ثابت افتراضي بعد الآن).
    يُستخدم في إقلاع الواجهة وإعادة تحميلها كي تُستعمل المفاتيح المُدخَلة/المختارة
    فعليًا في العمليات (لا في اختبار الاتصال فقط). لا يلمس منطق التوقيع/التداول.
    """
    if source is None:
        from ocobot.core.session import get_key_source
        source = get_key_source()
    creds = resolve_credentials(
        cfg.env,
        api_key=getattr(source, "api_key", None),
        api_secret=getattr(source, "api_secret", None),
        keys_path=getattr(source, "keys_path", None),
    )
    return build_signed_client(cfg, creds)


def make_gui_connect_handler(cfg=None):
    """يبني دالة اتصال لواجهة المستخدم.

    تُعيد callable(*, api_key, api_secret, keys_path) -> ConnectionResult
    تستدعي test_connection (قراءة فقط، /api/v3/account) على الإعداد المعطى
    (أو AppConfig الافتراضي Testnet). لا ترفع استثناءً؛ تُعيد ConnectionResult
    دائمًا. عند النجاح تُثبّت مصدر المفاتيح في الجلسة (set_key_source)."""

    def _handler(*, api_key=None, api_secret=None, keys_path=None):
        from ocobot.config import AppConfig

        active_cfg = cfg if cfg is not None else AppConfig.from_env_vars()
        result = test_connection(
            active_cfg, api_key=api_key, api_secret=api_secret, keys_path=keys_path
        )
        if getattr(result, "ok", False):
            from ocobot.core.session import set_key_source

            set_key_source(api_key=api_key, api_secret=api_secret, keys_path=keys_path)
        return result

    return _handler


def make_gui_disconnect_handler(cfg=None):
    """G1.12: معالج قطع اتصال معزول — يمسح مصدر مفاتيح الجلسة فقط ويعيد حالة غير متصل. لا شبكة، لا مساس بأي منطق تداول/OCO/مراقبة/Live."""

    def _handler(*_args, **_kwargs):
        from ocobot.core.session import clear_key_source

        clear_key_source()
        return ConnectionState(
            status=ConnectionStatus.DISCONNECTED,
            message="تم قطع الاتصال",
            detail="USER_DISCONNECT",
        )

    return _handler
