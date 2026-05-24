from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .config import get_project_root
from .log_scrubbing import attach_scrubber_to_handler

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_file_handler: logging.FileHandler | None = None
_session_log_path: Path | None = None


def get_logs_dir(config_path: Path, *, create: bool = True) -> Path:
    logs_dir = get_project_root(config_path) / "logs"
    if create:
        logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def start_session_log_file(config_path: Path) -> Path:
    """
    Attach a file handler for this app session. Each call rotates to a new timestamped log
    (including in-process restarts).
    """
    global _file_handler, _session_log_path
    stop_session_log_file()

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    path = get_logs_dir(config_path) / f"{stamp}-{now.microsecond:06d}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    attach_scrubber_to_handler(handler)
    logging.getLogger().addHandler(handler)

    _file_handler = handler
    _session_log_path = path
    return path


def stop_session_log_file() -> None:
    global _file_handler, _session_log_path
    if _file_handler is None:
        return
    root = logging.getLogger()
    root.removeHandler(_file_handler)
    _file_handler.close()
    _file_handler = None
    _session_log_path = None


def current_session_log_path() -> Path | None:
    return _session_log_path
