from dataclasses import dataclass
from pathlib import Path
import json
import logging
from typing import Any

from .appearance.bar_appearance import default_app_bar_fields
from .appearance.progress_effects import default_app_progress_effect_fields
from .appearance.timer_appearance import default_app_timer_fields
from .config_store import (
    DEFAULT_USER_CONFIG,
    load_raw_config,
    normalize_user_config,
    normalized_user_config_for_ui,
)
from .secrets import (
    resolve_patreon_credentials,
    resolve_streamlabs_socket_token,
    resolve_twitch_credentials,
    resolve_youtube_oauth_client_config,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8080
DEFAULT_PATREON_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_PATREON_POLL_INTERVAL_SECONDS = 30


@dataclass
class TwitchConfig:
    client_id: str
    client_secret: str
    channel_name: str


@dataclass
class YoutubeConfig:
    token_path: Path
    oauth_client_config: dict[str, Any] | None = None


@dataclass
class PatreonConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: Path
    campaign_id: str
    poll_interval_seconds: int


@dataclass
class StreamlabsConfig:
    socket_api_token: str


@dataclass
class AppSettings:
    """Process-wide settings read from config."""

    log_level: str
    log_chat_messages_for_testing: bool
    database_path: Path
    ui_host: str
    ui_port: int
    goals_directory: Path
    point_rules_path: Path
    exchange_rates_path: Path
    base_currency: str
    enable_test_events: bool
    twitch_sub_resub_dedupe_seconds: int
    require_ws_token: bool = False


@dataclass
class AppConfig:
    twitch: TwitchConfig
    youtube: YoutubeConfig
    patreon: PatreonConfig
    streamlabs: StreamlabsConfig
    app: AppSettings


def get_project_root(config_path: Path) -> Path:
    return config_path.resolve().parent


def get_data_dir(config_path: Path, *, create: bool = True) -> Path:
    data_dir = get_project_root(config_path) / "data"
    if create:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def resolve_runtime_path(config_path: Path, filename: str, *, is_dir: bool = False) -> Path:
    """
    Prefer data/<name>; if legacy file/dir exists at project root and not under data/, use root.
    """
    project_root = get_project_root(config_path)
    data_dir = get_data_dir(config_path, create=False)
    data_path = data_dir / filename
    root_path = project_root / filename

    if data_path.exists():
        return data_path
    if root_path.exists():
        if not data_dir.exists() or not any(data_dir.iterdir()):
            LOGGER.info(
                "using legacy path at project root for %s (%s); new files will use data/",
                filename,
                root_path,
            )
        return root_path
    get_data_dir(config_path, create=True)
    return data_path if not is_dir else data_dir / filename


def _build_youtube_config(
    config_path: Path,
    raw: dict[str, Any] | None = None,
) -> YoutubeConfig:
    return YoutubeConfig(
        token_path=resolve_runtime_path(config_path, "yt_token.json"),
        oauth_client_config=resolve_youtube_oauth_client_config(raw),
    )


def _build_twitch_config(
    config_path: Path,
    user: dict[str, Any],
    raw: dict[str, Any],
) -> TwitchConfig:
    client_id, client_secret = resolve_twitch_credentials()
    return TwitchConfig(
        client_id=client_id,
        client_secret=client_secret,
        channel_name=str(user["twitch"]["channel_name"]).strip().lstrip("#"),
    )


def _build_streamlabs_config(
    config_path: Path,
    user: dict[str, Any],
    raw: dict[str, Any],
) -> StreamlabsConfig:
    token = resolve_streamlabs_socket_token(raw)
    if not token:
        sl_user = user.get("streamlabs")
        if isinstance(sl_user, dict):
            token = str(sl_user.get("socket_api_token") or "").strip()
    return StreamlabsConfig(socket_api_token=token)


def _build_patreon_config(
    config_path: Path,
    user: dict[str, Any],
    raw: dict[str, Any],
) -> PatreonConfig:
    client_id, client_secret = resolve_patreon_credentials(raw)
    pa_raw = raw.get("patreon") if isinstance(raw.get("patreon"), dict) else {}
    return PatreonConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=DEFAULT_PATREON_REDIRECT_URI,
        token_path=resolve_runtime_path(config_path, "patreon_token.json"),
        campaign_id=str(pa_raw.get("campaign_id") or user["patreon"].get("campaign_id") or "").strip(),
        poll_interval_seconds=DEFAULT_PATREON_POLL_INTERVAL_SECONDS,
    )


def _parse_log_level(name: str) -> int:
    upper = name.strip().upper()
    level = getattr(logging, upper, None)
    if not isinstance(level, int):
        raise ValueError(
            f"config.json app.log_level: invalid {name!r}. "
            "Use a standard name such as DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    return level


def load_bootstrap_config(path: Path) -> AppConfig:
    """
    Defaults when config.json is missing (user preferences from DEFAULT_USER_CONFIG).

    Developer credentials come from the release bundle or environment variables — same as load_config().
    """
    user = normalize_user_config({})
    raw: dict[str, Any] = {}
    youtube = _build_youtube_config(path, raw)
    twitch = _build_twitch_config(path, user, raw)
    patreon = _build_patreon_config(path, user, raw)
    streamlabs = _build_streamlabs_config(path, user, raw)
    database_path = resolve_runtime_path(path, "revenue_events.db")
    goals_directory = resolve_runtime_path(path, "goals", is_dir=True)
    point_rules_path = resolve_runtime_path(path, "point_rules.json")
    exchange_rates_path = resolve_runtime_path(path, "exchange_rates.json")
    goals_directory.mkdir(parents=True, exist_ok=True)
    app_section = user["app"]
    return _build_app_config(
        twitch=twitch,
        youtube=youtube,
        patreon=patreon,
        streamlabs=streamlabs,
        log_level_name=DEFAULT_LOG_LEVEL,
        log_chat_messages_for_testing=bool(app_section["log_chat_messages_for_testing"]),
        database_path=database_path,
        ui_port=int(app_section["ui_port"]),
        goals_directory=goals_directory,
        point_rules_path=point_rules_path,
        exchange_rates_path=exchange_rates_path,
        base_currency=str(app_section["base_currency"]).strip().upper(),
        enable_test_events=bool(app_section["enable_test_events"]),
        require_ws_token=bool(app_section.get("require_ws_token", False)),
        twitch_sub_resub_dedupe_seconds=int(app_section.get("twitch_sub_resub_dedupe_seconds", 300)),
    )


def load_config(path: Path) -> AppConfig:
    raw = load_raw_config(path)
    user = normalize_user_config(raw)

    youtube = _build_youtube_config(path, raw)
    twitch = _build_twitch_config(path, user, raw)
    patreon = _build_patreon_config(path, user, raw)
    streamlabs = _build_streamlabs_config(path, user, raw)

    app_section = user["app"]
    log_chat_messages_for_testing = bool(app_section["log_chat_messages_for_testing"])
    ui_port = int(app_section["ui_port"])
    base_currency = str(app_section["base_currency"]).strip().upper()
    enable_test_events = bool(app_section["enable_test_events"])
    require_ws_token = bool(app_section.get("require_ws_token", False))
    twitch_sub_resub_dedupe_seconds = int(app_section.get("twitch_sub_resub_dedupe_seconds", 300))
    log_level_name = DEFAULT_LOG_LEVEL
    if isinstance(raw.get("app"), dict) and raw["app"].get("log_level"):
        log_level_name = str(raw["app"]["log_level"]).strip().upper()

    database_path = resolve_runtime_path(path, "revenue_events.db")
    goals_directory = resolve_runtime_path(path, "goals", is_dir=True)
    point_rules_path = resolve_runtime_path(path, "point_rules.json")
    exchange_rates_path = resolve_runtime_path(path, "exchange_rates.json")
    goals_directory.mkdir(parents=True, exist_ok=True)

    _parse_log_level(log_level_name)

    return _build_app_config(
        twitch=twitch,
        youtube=youtube,
        patreon=patreon,
        streamlabs=streamlabs,
        log_level_name=log_level_name,
        log_chat_messages_for_testing=log_chat_messages_for_testing,
        database_path=database_path,
        ui_port=ui_port,
        goals_directory=goals_directory,
        point_rules_path=point_rules_path,
        exchange_rates_path=exchange_rates_path,
        base_currency=base_currency,
        enable_test_events=enable_test_events,
        require_ws_token=require_ws_token,
        twitch_sub_resub_dedupe_seconds=twitch_sub_resub_dedupe_seconds,
    )


def load_app_config(path: Path) -> AppConfig:
    """Load config.json when present, otherwise bootstrap defaults (credentials always resolved)."""
    if path.is_file():
        return load_config(path)
    return load_bootstrap_config(path)


def subathon_state_path(config_path: Path) -> Path:
    return resolve_runtime_path(config_path, "subathon_state.json")


def user_config_for_ui(cfg: AppConfig) -> dict:
    return normalized_user_config_for_ui(
        {
            "app": {
                "log_chat_messages_for_testing": cfg.app.log_chat_messages_for_testing,
                "base_currency": cfg.app.base_currency,
                "enable_test_events": cfg.app.enable_test_events,
                "require_ws_token": cfg.app.require_ws_token,
                "ui_port": cfg.app.ui_port,
                "twitch_sub_resub_dedupe_seconds": cfg.app.twitch_sub_resub_dedupe_seconds,
                "subathon_points": DEFAULT_USER_CONFIG["app"]["subathon_points"],
                "subathon_seconds": DEFAULT_USER_CONFIG["app"]["subathon_seconds"],
                **default_app_bar_fields(),
                **default_app_timer_fields(),
                **default_app_progress_effect_fields(),
            },
            "twitch": {"channel_name": cfg.twitch.channel_name},
            "patreon": {},
            "youtube": {},
            "streamlabs": {"socket_api_token": cfg.streamlabs.socket_api_token},
        }
    )


def _build_app_config(
    *,
    twitch: TwitchConfig,
    youtube: YoutubeConfig,
    patreon: PatreonConfig,
    streamlabs: StreamlabsConfig,
    log_level_name: str,
    log_chat_messages_for_testing: bool,
    database_path: Path,
    ui_port: int,
    goals_directory: Path,
    point_rules_path: Path,
    exchange_rates_path: Path,
    base_currency: str,
    enable_test_events: bool,
    require_ws_token: bool,
    twitch_sub_resub_dedupe_seconds: int,
) -> AppConfig:
    return AppConfig(
        twitch=twitch,
        youtube=youtube,
        patreon=patreon,
        streamlabs=streamlabs,
        app=AppSettings(
            log_level=log_level_name,
            log_chat_messages_for_testing=log_chat_messages_for_testing,
            database_path=database_path,
            ui_host=DEFAULT_UI_HOST,
            ui_port=ui_port,
            goals_directory=goals_directory,
            point_rules_path=point_rules_path,
            exchange_rates_path=exchange_rates_path,
            base_currency=base_currency,
            enable_test_events=enable_test_events,
            twitch_sub_resub_dedupe_seconds=max(0, int(twitch_sub_resub_dedupe_seconds)),
            require_ws_token=require_ws_token,
        ),
    )


def update_patreon_campaign_id(config_path: Path, campaign_id: str) -> None:
    raw = load_raw_config(config_path)
    patreon = raw.get("patreon")
    if not isinstance(patreon, dict):
        patreon = {}
        raw["patreon"] = patreon
    patreon["campaign_id"] = campaign_id
    temp = config_path.with_suffix(config_path.suffix + ".tmp")
    temp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    temp.replace(config_path)
