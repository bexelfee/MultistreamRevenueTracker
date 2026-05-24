import sys
from pathlib import Path
from unittest.mock import patch

from multistream_revenue_tracker.app_paths import (
    bundle_dir,
    default_config_path,
    install_dir,
    is_frozen,
    supported_currencies_file,
    ui_templates_directory,
)


def test_dev_paths():
    with patch.object(sys, "frozen", False, create=True):
        assert is_frozen() is False
        root = install_dir()
        assert root == Path(__file__).resolve().parents[1]
        assert default_config_path() == root / "config.json"
        assert (bundle_dir() / "multistream_revenue_tracker" / "ui" / "templates").is_dir()
        assert supported_currencies_file().is_file()
        assert Path(ui_templates_directory()).is_dir()


def test_frozen_paths():
    fake_exe = Path("C:/Apps/Multistream/MultistreamRevenueTracker.exe")
    fake_meipass = Path("C:/Apps/Multistream/_internal")
    with patch.object(sys, "frozen", True, create=True), patch.object(
        sys, "executable", str(fake_exe), create=True
    ), patch.object(sys, "_MEIPASS", str(fake_meipass), create=True):
        assert is_frozen() is True
        assert install_dir() == fake_exe.parent
        assert default_config_path() == fake_exe.parent / "config.json"
        assert bundle_dir() == fake_meipass
        assert "templates" in ui_templates_directory()
