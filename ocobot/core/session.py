"""مصدر مفاتيح الجلسة للواجهة (G1.11 — core, non-UI).

حاوية بسيطة في الذاكرة تحمل مصدر المفاتيح الذي اختاره المستخدم من الواجهة
(حقول يدوية أو ملف مختار). تُستخدم من ``build_gui_client`` لحسم المفاتيح
بأولوية: الحقول ← الملف المختار ← المسار الثابت fallback. لا تحفظ أي سر على
القرص ولا تُسجِّله؛ الحياة بمدى العملية فقط.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class KeySource:
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    keys_path: Optional[str] = None


_source = KeySource()


def get_key_source() -> KeySource:
    """يعيد مصدر مفاتيح الجلسة الحالي (قد يكون فارغًا)."""
    return _source


def set_key_source(api_key=None, api_secret=None, keys_path=None) -> KeySource:
    """يضبط مصدر مفاتيح الجلسة (حقول و/أو مسار ملف)؛ يعيد المصدر المحدَّث."""
    global _source
    _source = KeySource(
        api_key=(api_key or None),
        api_secret=(api_secret or None),
        keys_path=(keys_path or None),
    )
    return _source


def clear_key_source() -> None:
    """يمسح مصدر مفاتيح الجلسة (يعود للمسار الثابت fallback)."""
    global _source
    _source = KeySource()
