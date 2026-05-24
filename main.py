import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from multistream_revenue_tracker.app_paths import default_config_path
from multistream_revenue_tracker.main import cli


if __name__ == "__main__":
    cli(default_config_path())
