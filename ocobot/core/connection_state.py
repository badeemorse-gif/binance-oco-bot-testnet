"""Visible connection state (الحالة المرئية) — DoD T1 & state machine 5.3.

كائن حالة خالٍ من الأسرار (redacted) يعرضه أي UI/CLI لاحقًا.
DISCONNECTED -> CONNECTING -> CONNECTED | ERROR
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ocobot.core.environment import Environment


class ConnectionStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


@dataclass
class ConnectionState:
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    environment: Optional[Environment] = None
    rest_base: str = ""
    key_hint: str = ""  # مقنّع دائمًا (لا سر)
    clock_offset_ms: Optional[int] = None
    message: str = ""
    checked_at: Optional[str] = None
    detail: dict = field(default_factory=dict)  # حقول غير حساسة فقط (لا أرصدة/أسرار)

    def is_connected(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "environment": self.environment.value if self.environment else None,
            "rest_base": self.rest_base,
            "key_hint": self.key_hint,
            "clock_offset_ms": self.clock_offset_ms,
            "message": self.message,
            "checked_at": self.checked_at,
            "detail": self.detail,
        }

    def to_display(self) -> str:
        icon = {
            ConnectionStatus.CONNECTED: "\u2705",
            ConnectionStatus.ERROR: "\u26d4",
            ConnectionStatus.CONNECTING: "\u2026",
            ConnectionStatus.DISCONNECTED: "\u25cb",
        }[self.status]
        env = self.environment.value if self.environment else "-"
        offset = f"{self.clock_offset_ms} ms" if self.clock_offset_ms is not None else "\u2014"
        lines = [
            "OCOBot \u2014 \u0641\u062d\u0635 \u0627\u0644\u0627\u062a\u0635\u0627\u0644 (Preflight)",
            f"  \u0627\u0644\u0628\u064a\u0626\u0629 (Environment): {env}",
            f"  REST base: {self.rest_base}",
            f"  \u0627\u0644\u0645\u0641\u062a\u0627\u062d (API key): {self.key_hint or '\u2014'}   [secret redacted]",
            f"  \u0625\u0632\u0627\u062d\u0629 \u0627\u0644\u0633\u0627\u0639\u0629 (clock offset): {offset}",
            f"  \u0627\u0644\u062d\u0627\u0644\u0629 (Connection): {icon} {self.status.value}",
            f"  \u0627\u0644\u0631\u0633\u0627\u0644\u0629: {self.message}",
        ]
        if self.detail:
            lines.append(f"  \u062a\u0641\u0627\u0635\u064a\u0644: {self.detail}")
        return "\n".join(lines)
