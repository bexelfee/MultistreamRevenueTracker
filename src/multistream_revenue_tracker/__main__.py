"""Allow `python -m multistream_revenue_tracker` as an entry point."""

from .main import cli
from .app_paths import default_config_path


def main() -> None:
    cli(default_config_path())


if __name__ == "__main__":
    main()
