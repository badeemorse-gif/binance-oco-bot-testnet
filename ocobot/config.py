"""AppConfig — الإعداد (Deliverable 9: AppConfig).

env(testnet/live) · keysPath · baseUrls · recvWindow. (gap/tolerance/guard
تُضاف كنقاط إعداد في مراحل لاحقة؛ هنا نبقي M0 فقط.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ocobot.core.environment import Environment, rest_base_url, ws_base_url

# المسار الافتراضي لملف المفاتيح (file_map.keys_file_default / D8) — قابل للتهيئة.
DEFAULT_KEYS_PATH = ""

RECV_WINDOW_DEFAULT = 5000
RECV_WINDOW_MAX = 60000  # سقف Binance


def _env_bool(name: str, default: bool = False) -> bool:
    """قراءة علم منطقي من البيئة (افتراضه default عند الغياب)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AppConfig:
    env: Environment = Environment.TESTNET  # A6: الافتراضي Testnet حتى اعتماد Live
    keys_path: str = DEFAULT_KEYS_PATH
    recv_window: int = RECV_WINDOW_DEFAULT
    request_timeout: float = 10.0
    rest_base_override: Optional[str] = None
    ws_base_override: Optional[str] = None
    # G1.65 — الخروج المتكيّف (dynamic exit): مُطفأ افتراضيًّا. لا تغيير سلوك ما لم
    # يُفعَّل صراحةً عبر OCOBOT_DYNAMIC_EXIT. وصل حيّ فقط، لا ختم/Live بلا «نفّذ».
    dynamic_exit_enabled: bool = False
    dynamic_exit_lock_base: float = 0.80
    dynamic_exit_profile: str = "baseline"
    # G1.65 increment #5 — شادو-مود: يحسب الخروج التكيّف ويسجّله فقط دون تنفيذه
    # (صفر تغيير سلوك). مُطفأ افتراضيًّا؛ يُفعَّل عبر OCOBOT_DYNAMIC_EXIT_SHADOW.
    dynamic_exit_shadow: bool = False

    def __post_init__(self):
        self.env = Environment.parse(self.env)
        rw = int(self.recv_window)
        self.recv_window = max(1, min(rw, RECV_WINDOW_MAX))
        self.dynamic_exit_enabled = bool(self.dynamic_exit_enabled)
        self.dynamic_exit_lock_base = float(self.dynamic_exit_lock_base)
        self.dynamic_exit_profile = str(self.dynamic_exit_profile)
        self.dynamic_exit_shadow = bool(self.dynamic_exit_shadow)

    def rest_base(self) -> str:
        return self.rest_base_override or rest_base_url(self.env)

    def ws_base(self) -> str:
        return self.ws_base_override or ws_base_url(self.env)

    def for_env(self, env) -> "AppConfig":
        """Copy switched to another environment.

        التبديل يغيّر البيئة (base URL + مصدر المفتاح) فقط — قرار D12. تُمسح
        أي overrides ليكون التبديل نظيفًا.
        """
        return AppConfig(
            env=Environment.parse(env),
            keys_path=self.keys_path,
            recv_window=self.recv_window,
            request_timeout=self.request_timeout,
            dynamic_exit_enabled=self.dynamic_exit_enabled,
            dynamic_exit_lock_base=self.dynamic_exit_lock_base,
            dynamic_exit_profile=self.dynamic_exit_profile,
            dynamic_exit_shadow=self.dynamic_exit_shadow,
        )

    @classmethod
    def from_env_vars(cls, **overrides) -> "AppConfig":
        base = dict(
            env=os.environ.get("OCOBOT_ENV", Environment.TESTNET.value),
            keys_path=os.environ.get("OCOBOT_KEYS_PATH", DEFAULT_KEYS_PATH),
            recv_window=int(os.environ.get("OCOBOT_RECV_WINDOW", RECV_WINDOW_DEFAULT)),
            dynamic_exit_enabled=_env_bool("OCOBOT_DYNAMIC_EXIT", False),
            dynamic_exit_lock_base=float(
                os.environ.get("OCOBOT_DYNAMIC_EXIT_LOCK_BASE", "0.80")),
            dynamic_exit_profile=os.environ.get("OCOBOT_DYNAMIC_EXIT_PROFILE", "baseline"),
            dynamic_exit_shadow=_env_bool("OCOBOT_DYNAMIC_EXIT_SHADOW", False),
        )
        base.update(overrides)
        return cls(**base)
