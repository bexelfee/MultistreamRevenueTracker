import logging
from pathlib import Path

from multistream_revenue_tracker.session_logging import (
    get_logs_dir,
    start_session_log_file,
    stop_session_log_file,
)


def test_start_session_log_file_writes_records(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        log_path = start_session_log_file(config_path)
        logging.getLogger("test.session").info("hello from session")

    stop_session_log_file()

    assert log_path.parent == tmp_path / "logs"
    assert log_path.suffix == ".log"
    text = log_path.read_text(encoding="utf-8")
    assert "hello from session" in text
    assert "[test.session]" in text


def test_session_log_rotates_on_restart(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    first = start_session_log_file(config_path)
    stop_session_log_file()
    second = start_session_log_file(config_path)
    stop_session_log_file()

    assert first != second
    assert get_logs_dir(config_path, create=False).is_dir()
    assert len(list(get_logs_dir(config_path).glob("*.log"))) == 2
