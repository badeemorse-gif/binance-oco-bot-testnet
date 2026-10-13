"""Append-only Audit Log (T5 / M4) — JSONL آمن بلا أسرار.

مُسجّل تدقيق يكتب سطرًا JSON واحدًا لكل حدث (JSON Lines) في وضع الإلحاق ('a')
فقط — لا يُعاد كتابة/اقتطاع أي سطر سابق أبدًا (append-only). كل سطر يحمل:
  - ts: طابع زمني UTC بصيغة ISO-8601.
  - event: نوع الحدث.
  - details: تفاصيل مُهيكلة (dict).

يُعاد استخدام أداة الإخفاء القائمة عبر الاستيراد من ``ocobot.core.redaction``
(استيراد فقط — بلا أي تعديل عليها) لضمان ألّا تُكتب المفاتيح/التواقيع/الأسرار
إطلاقًا (D8). مسار الملف قابل للتهيئة عبر الباني — لا مسار مستخدم مُثبَّت.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ocobot.core.redaction import redact_signature


def _now_iso() -> str:
    """طابع زمني UTC بصيغة ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    """مُسجّل تدقيق append-only يكتب JSONL مُخفَّى الأسرار."""

    def __init__(self, path: str, *, ensure_dir: bool = True):
        if not path:
            raise ValueError("audit log path is required")
        self.path = path
        if ensure_dir:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)

    def record(self, event: str, details: Optional[dict] = None) -> dict:
        """يُلحق حدثًا واحدًا (سطر JSONL) دون المساس بالأسطر السابقة.

        يُخفي أي مفتاح/توقيع في التفاصيل المُسلسلة قبل الكتابة، ويعيد الإدخال
        المكتوب (بعد الإخفاء) للاطلاع/الاختبار.
        """
        entry = {
            "ts": _now_iso(),
            "event": event,
            "details": details if details is not None else {},
        }
        # تسلسل ثمّ إخفاء الأسرار على النصّ النهائي (D8) — لا تُكتب أي مفاتيح.
        line = redact_signature(json.dumps(entry, ensure_ascii=False, default=str))
        # وضع الإلحاق فقط: لا يُقتطع/يُعاد كتابة أي سطر سابق.
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return entry
