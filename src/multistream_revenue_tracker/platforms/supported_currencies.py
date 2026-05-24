from __future__ import annotations

import json
from functools import lru_cache

from ..app_paths import supported_currencies_file

_DATA_FILE = supported_currencies_file()


@lru_cache(maxsize=1)
def supported_currency_codes() -> tuple[str, ...]:
    codes = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise ValueError(f"invalid currency list in {_DATA_FILE}")
    return tuple(sorted({c.strip().upper() for c in codes if c.strip()}))


def is_supported_currency(code: str) -> bool:
    return code.upper() in supported_currency_codes()
