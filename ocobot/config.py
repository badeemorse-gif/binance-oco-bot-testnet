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


@dataclass
class AppConfig:
    env: Environment = Environment.TESTNET  # A6: الافتراضي Testnet حتى اعتماد Live
    keys_path: str = DEFAULT_KEYS_PATH
    recv_window: int = RECV_WINDOW_DEFAULT
    request_timeout: float = 10.0
    rest_base_override: Optional[str] = None
    ws_base_override: Optional[str] = None

    def __post_init__(self):
        self.env = Environment.parse(self.env)
        rw = int(self.recv_window)
        self.recv_window = max(1, min(rw, RECV_WINDOW_MAX))

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
        )

    @classmethod
    def from_env_vars(cls, **overrides) -> "AppConfig":
        base = dict(
            env=os.environ.get("OCOBOT_ENV", Environment.TESTNET.value),
            keys_path=os.environ.get("OCOBOT_KEYS_PATH", DEFAULT_KEYS_PATH),
            recv_window=int(os.environ.get("OCOBOT_RECV_WINDOW", RECV_WINDOW_DEFAULT)),
        )
        base.update(overrides)
        return cls(**base)
