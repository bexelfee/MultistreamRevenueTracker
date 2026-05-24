"""Launch the app with an explicit config path (used for E2E_TARGET=source).

The first positional argument (after `--`) is the config path. Any remaining
arguments are forwarded to the app's argparse-based CLI (e.g. `--clean`).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from multistream_revenue_tracker.main import cli  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_app.py <config.json path> [--clean ...]")
    config_path = Path(sys.argv[1]).resolve()
    # The app's own argparse expects no positional arg, so strip the config path
    # from sys.argv before calling cli.
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    cli(config_path)


if __name__ == "__main__":
    main()
