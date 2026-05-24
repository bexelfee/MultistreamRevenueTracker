import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_bundled_credentials.py"


def _env_without_oauth() -> dict[str, str]:
    skip_prefixes = ("TWITCH_", "PATREON_", "YOUTUBE_", "PATREON_SECRET")
    return {
        k: v
        for k, v in os.environ.items()
        if not any(k.startswith(prefix) for prefix in skip_prefixes)
    }


def test_generate_fails_without_credentials_by_default():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=_env_without_oauth(),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing required build credentials" in result.stderr + result.stdout


def test_generate_succeeds_with_minimal_env(tmp_path):
    google_json = tmp_path / "google.json"
    google_json.write_text(
        '{"installed": {"client_id": "g", "client_secret": "s"}}',
        encoding="utf-8",
    )
    out = tmp_path / "bundled_credentials.py"
    env = _env_without_oauth()
    env["TWITCH_CLIENT_ID"] = "tid"
    env["TWITCH_CLIENT_SECRET"] = "tsec"
    env["YOUTUBE_CLIENT_SECRETS_PATH"] = str(google_json)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "TWITCH_CLIENT_ID: str = 'tid'" in text
    assert "'client_id': 'g'" in text


def test_check_empty_accepts_double_quoted_placeholders(tmp_path):
    path = tmp_path / "bundled_credentials.py"
    path.write_text(
        "\n".join([
            "from typing import Any",
            'TWITCH_CLIENT_ID: str = ""',
            'TWITCH_CLIENT_SECRET: str = ""',
            'PATREON_CLIENT_ID: str = ""',
            'PATREON_CLIENT_SECRET: str = ""',
            "YOUTUBE_OAUTH_CLIENT_CONFIG: dict[str, Any] | None = None",
        ]),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-empty", "--output", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
