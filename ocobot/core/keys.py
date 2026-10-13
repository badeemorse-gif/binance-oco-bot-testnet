"""Key loading + redaction (D8 — Config & Security).

Format (يفصل البيئتين):
    TESTNET_KEY=...
    TESTNET_SECRET=...
    LIVE_KEY=...
    LIVE_SECRET=...

القواعد: لا تُسجَّل المفاتيح إطلاقًا (repr/str مقنّعان). التحقق للبيئة المختارة فقط.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from typing import Optional

from ocobot.core.environment import Environment
from ocobot.core.errors import KeysError
from ocobot.core.redaction import mask_key, mask_secret


class CredentialsError(KeysError):
    """خطأ في مصدر/اختيار المفاتيح (حقول ناقصة أو لا مصدر) — رسائل مقنّعة فقط."""


@dataclass
class ApiCredentials:
    api_key: str
    api_secret: str

    def masked_key(self) -> str:
        return mask_key(self.api_key)

    # يمنع أي تسريب عبر repr/str/logging
    def __repr__(self) -> str:
        return (
            f"ApiCredentials(api_key='{mask_key(self.api_key)}', "
            f"api_secret='{mask_secret(self.api_secret)}')"
        )

    __str__ = __repr__


def parse_keyfile(text: str) -> dict:
    """Parse ``KEY=VALUE`` lines; ignore blanks/comments; strip quotes."""
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_credentials(keys_path: str, env) -> ApiCredentials:
    env = Environment.parse(env)
    if not keys_path or not os.path.exists(keys_path):
        raise KeysError(
            f"ملف المفاتيح غير موجود على المسار المحدد: {keys_path!r}. "
            "أنشئه بالصيغة TESTNET_KEY/TESTNET_SECRET/LIVE_KEY/LIVE_SECRET، "
            "ولا ترفعه لأي repo."
        )
    try:
        with open(keys_path, "r", encoding="utf-8-sig") as fh:
            data = parse_keyfile(fh.read())
    except OSError as exc:
        raise KeysError(f"تعذّرت قراءة ملف المفاتيح: {exc}") from exc

    prefix = "TESTNET" if env == Environment.TESTNET else "LIVE"
    api_key = data.get(f"{prefix}_KEY", "").strip()
    api_secret = data.get(f"{prefix}_SECRET", "").strip()

    missing = [
        name
        for name, value in ((f"{prefix}_KEY", api_key), (f"{prefix}_SECRET", api_secret))
        if not value
    ]
    if missing:
        raise KeysError(
            f"المفاتيح ناقصة للبيئة {env.value}: {', '.join(missing)}. "
            "تحقّق من ملف المفاتيح."
        )
    return ApiCredentials(api_key=api_key, api_secret=api_secret)


def resolve_credentials(
    env,
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    keys_path: Optional[str] = None,
    fallback_path: Optional[str] = None,  # مُهمَل عمدًا (توافق خلفي)؛ لا يُستخدم.
) -> ApiCredentials:
    """يحدّد مصدر المفاتيح حسب الأولوية (G1.11):

    1) الحقول: إذا كان api_key و api_secret كلاهما غير فارغين (بعد strip) ←
       تُستخدم مباشرة.
    2) حقل واحد فقط ← ``CredentialsError`` (مفتاح ناقص).
    3) ملف مختار ``keys_path`` ← ``load_credentials(keys_path, env)``.
    4) لا مصدر إطلاقًا ← ``ValueError``.

    ملاحظة: ``fallback_path`` مقبول للتوافق مع المستدعين القدامى لكنه مُهمَل
    عمدًا؛ لا يُستخدم المسار الثابت للاتصال التلقائي بعد الآن.

    لا يُسجَّل أي سر؛ الرسائل مقنّعة/عامة.
    """
    key = (api_key or "").strip()
    secret = (api_secret or "").strip()
    _ = fallback_path  # تجاهل القيمة المُهمَلة لتفادي تحذير «غير مُستخدم».

    if key and secret:
        return ApiCredentials(api_key=key, api_secret=secret)
    if key or secret:
        raise CredentialsError("مفتاح ناقص: أدخل API Key وSecret معًا")

    if keys_path:
        return load_credentials(keys_path, env)

    raise ValueError("لا توجد مفاتيح للاتصال: الرجاء إدخال المفاتيح يدويًا أو فتح ملف المفاتيح من فرع الاتصال")
