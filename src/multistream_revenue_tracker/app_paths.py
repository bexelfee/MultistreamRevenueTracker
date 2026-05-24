"""Install and bundle paths for development and frozen (PyInstaller) runs."""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _PACKAGE_DIR.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Unpack directory for packaged assets (templates, static JSON)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return _SRC_ROOT


def install_dir() -> Path:
    """Writable directory beside the executable (or repo root in development)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _SRC_ROOT.parent


def default_config_path() -> Path:
    return install_dir() / "config.json"


def package_static_path(*parts: str) -> Path:
    return bundle_dir().joinpath("multistream_revenue_tracker", *parts)


def ui_templates_directory() -> str:
    return str(package_static_path("ui", "templates"))


def supported_currencies_file() -> Path:
    return package_static_path("static", "supported_currencies.json")
