"""Remove transient runtime files (OAuth tokens, local DB, goals, caches, logs, config.json).

Does not touch bundled_credentials.py (developer credentials come from environment variables).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import get_project_root, load_bootstrap_config, load_config
from ..config_store import config_exists
from ..session_logging import get_logs_dir

LOGGER = logging.getLogger(__name__)

_TRANSIENT_FILENAMES = (
    "yt_token.json",
    "patreon_token.json",
    "twitch_token.json",
    "revenue_events.db",
    "revenue_events.db-wal",
    "revenue_events.db-shm",
    "point_rules.json",
    "exchange_rates.json",
    "remaining_queue.json",
)


def _sqlite_sidecars(database_path: Path) -> list[Path]:
    return [
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ]


def collect_transient_paths(config_path: Path) -> list[Path]:
    """Resolved paths that --clean will remove (files and directories)."""
    config_path = config_path.resolve()
    root = get_project_root(config_path)
    data_dir = root / "data"

    paths: list[Path] = []

    if config_exists(config_path):
        app_cfg = load_config(config_path)
        app = app_cfg.app
        paths.extend([
            app_cfg.youtube.token_path,
            app_cfg.patreon.token_path,
            app.database_path,
            app.point_rules_path,
            app.exchange_rates_path,
            app.goals_directory,
            root / "remaining_queue.json",
        ])
        paths.extend(_sqlite_sidecars(app.database_path))
    else:
        bootstrap = load_bootstrap_config(config_path)
        app = bootstrap.app
        paths.extend([
            bootstrap.youtube.token_path,
            bootstrap.patreon.token_path,
            app.database_path,
            app.point_rules_path,
            app.exchange_rates_path,
            app.goals_directory,
            root / "remaining_queue.json",
        ])
        paths.extend(_sqlite_sidecars(app.database_path))

    for name in _TRANSIENT_FILENAMES:
        for base in (root, data_dir):
            paths.append(base / name)

    logs_dir = get_logs_dir(config_path, create=False)
    if logs_dir.is_dir():
        paths.append(logs_dir)

    if config_path.is_file():
        paths.append(config_path)

    unique: dict[Path, None] = {}
    for path in paths:
        unique[path.resolve()] = None
    return list(unique.keys())


def clean_transient_data(config_path: Path) -> list[str]:
    """
    Delete config.json, OAuth tokens, revenue DB, goals, point rules, exchange-rate cache, and logs.
    Returns human-readable paths that were removed (for logging or CLI output).
    """
    removed: list[str] = []
    for path in collect_transient_paths(config_path):
        if not path.exists():
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))
            LOGGER.info("clean removed %s", path)
        except OSError as exc:
            LOGGER.warning("clean could not remove %s: %s", path, exc)
    return removed
