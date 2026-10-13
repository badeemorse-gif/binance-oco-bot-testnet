"""Alerts persistence layer (G1.25 / step_4) — settings JSON + secret token file.

============================================================================
قرار الجلسة (مُحسوم مسبقًا — يُنفَّذ هنا حرفيًا):
----------------------------------------------------------------------------
- **الإعدادات غير السرّية** (بيانات البوت، المستلمون، حالة التفعيل) تُستديم في
  ملف JSON ذرّي مخصّص عند ``env OCOBOT_ALERTS_FILE`` وإلا ``cwd/ocobot_alerts.json``.
  لا تُكتَب في ``PROJECT_STATE.json`` ولا داخل ``StateStore`` لأن
  ``StateStore._strip_secrets`` ينقّي المفاتيح الشبيهة بالأسرار وله سكيمة ثابتة
  لا تتّسع لحالة التنبيهات.
- **توكِن Telegram سرّ**: يُقرأ من ``env OCOBOT_TELEGRAM_TOKEN`` أولًا، وإلا من
  ملف توكِن عند ``env OCOBOT_TELEGRAM_TOKEN_FILE`` (الافتراضي ``.ocobot_telegram_token``
  في cwd). ملف التوكِن مُستثنى في git ولا يظهر التوكِن في أي سجل (يُقنَّع عبر
  ``ocobot.core.redaction.mask_secret``).

النمط الذرّي (مطابق لأسلوب ``ocobot.core.state_store``): كتابة إلى ملف مؤقّت في
نفس المجلد ⇒ flush ⇒ ``os.fsync`` ⇒ ``os.replace`` (rename ذرّي) ⇒ fsync للدليل
حيث يُدعَم. كل القراءات دفاعية: ملف مفقود/تالف ⇒ قيم افتراضية آمنة، لا استثناء خام.

قيود: مكتبة قياسية فقط + ``ocobot.core.redaction``. لا Qt، لا شبكة.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

from ocobot.core.redaction import mask_secret

# ---------------------------------------------------------------------------
# ثوابت الموديول
# ---------------------------------------------------------------------------
DEFAULT_ALERTS_FILENAME = "ocobot_alerts.json"
DEFAULT_TOKEN_FILENAME = ".ocobot_telegram_token"
SCHEMA_VERSION = 1

# أسماء متغيّرات البيئة المعتمدة (مطابقة لقرار الجلسة).
_ENV_ALERTS_FILE = "OCOBOT_ALERTS_FILE"
_ENV_TOKEN = "OCOBOT_TELEGRAM_TOKEN"
_ENV_TOKEN_FILE = "OCOBOT_TELEGRAM_TOKEN_FILE"


# ---------------------------------------------------------------------------
# مُحدِّدات المسار (path resolvers)
# ---------------------------------------------------------------------------
def alerts_file_path() -> str:
    """مسار ملف الإعدادات: ``env OCOBOT_ALERTS_FILE`` وإلا ``cwd/ocobot_alerts.json``."""
    env = os.environ.get(_ENV_ALERTS_FILE)
    if env:
        return env
    return os.path.join(os.getcwd(), DEFAULT_ALERTS_FILENAME)


def token_file_path() -> str:
    """مسار ملف التوكِن: ``env OCOBOT_TELEGRAM_TOKEN_FILE`` وإلا ``cwd/.ocobot_telegram_token``."""
    env = os.environ.get(_ENV_TOKEN_FILE)
    if env:
        return env
    return os.path.join(os.getcwd(), DEFAULT_TOKEN_FILENAME)


# ---------------------------------------------------------------------------
# dataclasses — الإعدادات غير السرّية فقط (لا توكِن إطلاقًا هنا)
# ---------------------------------------------------------------------------
@dataclass
class Recipient:
    """مستلِم إشعار: ``chat_id`` + تسمية اختيارية."""

    chat_id: str
    label: str = ""

    def to_dict(self) -> dict:
        return {"chat_id": str(self.chat_id), "label": self.label}

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Recipient"]:
        """يبني مستلِمًا من dict متسامحًا؛ يُعيد None لو كان ``chat_id`` غائبًا/فارغًا."""
        if not isinstance(data, dict):
            return None
        chat_id = data.get("chat_id")
        if chat_id is None:
            return None
        chat_id = str(chat_id).strip()
        if not chat_id:
            return None
        label = data.get("label", "")
        if not isinstance(label, str):
            label = str(label)
        return cls(chat_id=chat_id, label=label)


@dataclass
class BotInfo:
    """بيانات البوت غير السرّية (لا توكِن): اسم المستخدم/التسمية + علم الحضور."""

    username: str = ""
    label: str = ""
    present: bool = False

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "label": self.label,
            "present": bool(self.present),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BotInfo"]:
        if not isinstance(data, dict):
            return None
        username = data.get("username", "")
        label = data.get("label", "")
        if not isinstance(username, str):
            username = str(username) if username is not None else ""
        if not isinstance(label, str):
            label = str(label) if label is not None else ""
        return cls(
            username=username,
            label=label,
            present=bool(data.get("present", False)),
        )


@dataclass
class AlertsSettings:
    """الحالة المُستديمة الكاملة (غير السرّية): تفعيل + بوت + مستلمون."""

    enabled: bool = False
    bot: Optional[BotInfo] = None
    recipients: List[Recipient] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": bool(self.enabled),
            "bot": self.bot.to_dict() if self.bot else None,
            "recipients": [r.to_dict() for r in self.recipients],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "AlertsSettings":
        """متسامح تمامًا: مدخل مفقود/تالف/من نوع خاطئ ⇒ قيم افتراضية آمنة، لا يرفع أبدًا."""
        if not isinstance(data, dict):
            return cls()
        enabled = bool(data.get("enabled", False))

        bot = BotInfo.from_dict(data.get("bot"))

        recipients: List[Recipient] = []
        raw_recipients = data.get("recipients")
        if isinstance(raw_recipients, list):
            seen = set()
            for item in raw_recipients:
                rec = Recipient.from_dict(item)
                if rec is None:
                    continue
                if rec.chat_id in seen:
                    continue
                seen.add(rec.chat_id)
                recipients.append(rec)

        return cls(enabled=enabled, bot=bot, recipients=recipients)


# ---------------------------------------------------------------------------
# طبقة التخزين: إعدادات ذرّية (JSON) + توكِن سرّي (ملف dot مُقنَّع)
# ---------------------------------------------------------------------------
class AlertsStore:
    """تخزين إعدادات التنبيهات (JSON ذرّي) + التوكِن السرّي (ملف منفصل مُستثنى في git).

    كل العمليات دفاعية: JSON تالف/ملف مفقود ⇒ قيم افتراضية آمنة ولا تتعطّل.
    التوكِن الخام لا يظهر في ``__repr__`` ولا في أي استثناء/سجل — يُقنَّع عبر
    ``mask_secret``.
    """

    def __init__(self, path: Optional[str] = None, token_path: Optional[str] = None):
        self._path = path if path else alerts_file_path()
        self._token_path = token_path if token_path else token_file_path()

    # ----- repr آمن: لا يسرّب التوكِن ولا المسار السرّي الخام غير اللازم -----
    def __repr__(self) -> str:  # pragma: no cover - تمثيل بسيط
        has_token = self.get_token() is not None
        return (
            "AlertsStore(path={!r}, token_present={}, token={})".format(
                self._path, has_token, mask_secret("") if has_token else "(none)"
            )
        )

    # ================= الكتابة الذرّية (مطابقة لـ state_store) =================
    @staticmethod
    def _atomic_write_bytes(target: str, data: bytes, *, mode: Optional[int] = None) -> None:
        """يكتب ``data`` ذرّيًا إلى ``target`` (temp ⇒ fsync ⇒ os.replace ⇒ fsync dir).

        عند أي فشل يُنظَّف الملف المؤقّت ولا يُمَسّ الملف الهدف السابق.
        ``mode`` اختياري لضبط صلاحيات مقيّدة (best-effort) على الملف المؤقّت.
        """
        directory = os.path.dirname(os.path.abspath(target)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".{}.".format(os.path.basename(target)),
            suffix=".tmp",
            dir=directory,
        )
        try:
            if mode is not None:
                try:
                    os.chmod(tmp_path, mode)
                except OSError:
                    # Windows / أنظمة لا تدعم الصلاحيات POSIX — تجاهل بهدوء.
                    pass
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
            tmp_path = None  # نجح الاستبدال — لا تنظيف بعده
            AlertsStore._fsync_dir(directory)
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        """fsync لدليل الحاوية لتثبيت الـ rename (يُتجاهل بهدوء على Windows)."""
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    # ======================= الإعدادات غير السرّية =======================
    def load(self) -> AlertsSettings:
        """قراءة آمنة: ملف مفقود/تالف/غير قابل للفكّ ⇒ قيم افتراضية آمنة (لا يرفع)."""
        try:
            with open(self._path, "rb") as handle:
                raw_bytes = handle.read()
        except (FileNotFoundError, OSError):
            return AlertsSettings()

        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return AlertsSettings()

        if not raw.strip():
            return AlertsSettings()

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return AlertsSettings()

        try:
            return AlertsSettings.from_dict(data)
        except Exception:  # noqa: BLE001 — حصانة أخيرة ضد أي بنية غير متوقّعة
            return AlertsSettings()

    def save(self, settings: AlertsSettings) -> None:
        """يحفظ الإعدادات ذرّيًا كـ JSON مُنسَّق مع ``schema_version``."""
        payload = settings.to_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        self._atomic_write_bytes(self._path, text.encode("utf-8"))

    # ------- عمليات load-modify-save مريحة -------
    def set_enabled(self, flag: bool) -> None:
        settings = self.load()
        settings.enabled = bool(flag)
        self.save(settings)

    def set_bot(self, username: str = "", label: str = "") -> None:
        settings = self.load()
        settings.bot = BotInfo(username=username or "", label=label or "", present=True)
        self.save(settings)

    def clear_bot(self) -> None:
        settings = self.load()
        settings.bot = None
        self.save(settings)

    def add_recipient(self, chat_id: str, label: str = "") -> None:
        """يضيف مستلِمًا مع إزالة التكرار حسب ``chat_id`` (آخر تسمية تفوز)."""
        chat_id = str(chat_id).strip()
        if not chat_id:
            return
        settings = self.load()
        for existing in settings.recipients:
            if existing.chat_id == chat_id:
                if label:
                    existing.label = label
                self.save(settings)
                return
        settings.recipients.append(Recipient(chat_id=chat_id, label=label or ""))
        self.save(settings)

    def remove_recipients(self, chat_ids: Iterable[str]) -> None:
        """يحذف المستلمين المطابقين؛ غير الموجود = لا عملية؛ والمحذوف يبقى محذوفًا."""
        to_remove = {str(c).strip() for c in (chat_ids or [])}
        if not to_remove:
            return
        settings = self.load()
        settings.recipients = [
            r for r in settings.recipients if r.chat_id not in to_remove
        ]
        self.save(settings)

    # ============================ التوكِن (سرّ) ============================
    def get_token(self) -> Optional[str]:
        """يُفضّل ``env OCOBOT_TELEGRAM_TOKEN`` وإلا يقرأ ملف التوكِن (مُقلَّم).

        يُعيد None عند غياب التوكِن. لا يُسرَّب التوكِن في أي استثناء/سجل.
        """
        env_token = os.environ.get(_ENV_TOKEN)
        if env_token and env_token.strip():
            return env_token.strip()
        try:
            with open(self._token_path, "rb") as handle:
                raw = handle.read()
        except (FileNotFoundError, OSError):
            return None
        try:
            token = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        return token or None

    def set_token(self, token: str) -> None:
        """يكتب التوكِن ذرّيًا لملف التوكِن بصلاحيات مقيّدة (0o600 best-effort)."""
        if token is None:
            token = ""
        data = str(token).strip().encode("utf-8")
        try:
            self._atomic_write_bytes(self._token_path, data, mode=0o600)
            # harden perms on the final file too (best-effort; Windows ignores).
            try:
                os.chmod(self._token_path, 0o600)
            except OSError:
                pass
        except OSError:
            # لا تسريب للتوكِن في رسالة الاستثناء مطلقًا.
            raise OSError(
                "failed to persist telegram token (masked={})".format(mask_secret(""))
            ) from None

    def clear_token(self) -> None:
        """يحذف ملف التوكِن إن وُجد؛ المحذوف يبقى محذوفًا (لا خطأ إن غائبًا)."""
        try:
            os.remove(self._token_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    # ===================== مزوّدات Notifier =====================
    def recipients_provider(self) -> List[str]:
        """يُعيد قائمة ``chat_id`` للمستلمين الحاليين (iterable لـ Notifier)."""
        settings = self.load()
        return [r.chat_id for r in settings.recipients]

    def enabled_provider(self) -> bool:
        """مُفعَّل فقط إذا enabled=True وبوت حاضر وأدنى تهيئة صالحة للإرسال.

        الحدّ الأدنى: ``settings.enabled`` صحيح. نضيف تحقّقًا أن البوت حاضر
        فعليًا حتى لا يُفعَّل الإرسال دون بوت مُهيّأ.
        """
        settings = self.load()
        if not settings.enabled:
            return False
        if settings.bot is None or not settings.bot.present:
            return False
        return True


__all__ = [
    "DEFAULT_ALERTS_FILENAME",
    "DEFAULT_TOKEN_FILENAME",
    "SCHEMA_VERSION",
    "alerts_file_path",
    "token_file_path",
    "Recipient",
    "BotInfo",
    "AlertsSettings",
    "AlertsStore",
]
