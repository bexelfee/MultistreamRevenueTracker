import argparse
import asyncio
import datetime as _dt
import json
import logging
import sys
import traceback
from pathlib import Path

from .revenue import db_writer
from .log_scrubbing import scrub_text
from .monitors.monitor_coordinator import MonitorCoordinator
from .monitors.monitor_status import MonitorStatusRegistry, build_initial_status
from .log_scrubbing import install_log_scrubbing_filter, register_from_app_config, register_token_file
from .ui.log_broadcast import register_log_broadcast_handler
from .ui.server import WebUiContext, run_web_server
from .config import load_app_config, subathon_state_path
from .config_store import DEFAULT_SUBATHON_POINTS, DEFAULT_SUBATHON_SECONDS
from .services.subathon_service import SubathonService
from .appearance.timer_appearance import extract_timer_appearance
from .config_store import config_exists, load_raw_config, normalize_user_config, normalized_user_config_for_ui
from .session_logging import start_session_log_file, stop_session_log_file
from .revenue.events import StreamEvent
from .services.exchange_rates import refresh_exchange_rates_file
from .goals.goal_service import build_goal_service
from .platforms.patreon_runtime import PatreonRuntime
from .revenue.revenue_db import RevenueDatabase
from .services.runtime_cleanup import clean_transient_data
from .revenue.session_handles import SessionHandles
from .revenue.session_revenue import SessionRevenueStore

LOGGER = logging.getLogger(__name__)
MAX_QUEUE_SIZE = 1000


async def run_async(
    name,
    coroutine,
    shutdown_event: asyncio.Event,
    *,
    stop_requested: asyncio.Event | None = None,
    trigger_shutdown_on_error: bool = True,
):
    try:
        await coroutine
    except asyncio.CancelledError:
        LOGGER.info(f"{name} cancelled")
        raise
    except Exception:
        LOGGER.exception(f"{name} failed")
        if trigger_shutdown_on_error:
            if stop_requested is not None:
                stop_requested.set()
            shutdown_event.set()
        raise
    finally:
        LOGGER.info(f"{name} finished")


async def dump_remaining_queue(queue, path):
    with open(path, "a", encoding="utf-8") as f:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if isinstance(item, StreamEvent):
                f.write(json.dumps(item.to_json_dict()) + "\n")
            else:
                f.write(json.dumps({"raw": repr(item)}) + "\n")
            queue.task_done()


async def _run_app_session(
    config_path: Path,
    *,
    open_browser: bool,
) -> bool:
    """
    Run monitors, db writer, and web UI until shutdown or restart.
    Returns True when the UI requested an in-process restart (reload config and run again).
    """
    log_path = start_session_log_file(config_path)
    LOGGER.info("session log file: %s", log_path)
    try:
        return await _run_app_session_body(
            config_path,
            open_browser=open_browser,
        )
    finally:
        stop_session_log_file()


async def _run_app_session_body(
    config_path: Path,
    *,
    open_browser: bool,
) -> bool:
    LOGGER.info("main init")
    if not config_exists(config_path):
        LOGGER.info("config.json not found — using UI defaults (developer credentials from env/bundle)")
    app_cfg = load_app_config(config_path)
    register_from_app_config(app_cfg)
    register_token_file(app_cfg.patreon.token_path)
    register_token_file(app_cfg.youtube.token_path)
    database = RevenueDatabase(app_cfg.app.database_path)
    database.initialize()
    refresh_exchange_rates_file(app_cfg.app.exchange_rates_path, app_cfg.app.base_currency)
    goal_service = build_goal_service(app_cfg.app, database)
    if config_exists(config_path):
        user_norm = normalize_user_config(load_raw_config(config_path))
    else:
        user_norm = normalize_user_config({})
    subathon_points = int(user_norm["app"].get("subathon_points", DEFAULT_SUBATHON_POINTS))
    subathon_seconds = int(user_norm["app"].get("subathon_seconds", DEFAULT_SUBATHON_SECONDS))
    timer_app = extract_timer_appearance(user_norm.get("app"))
    subathon_service = SubathonService(
        subathon_state_path(config_path),
        database,
        subathon_points=subathon_points,
        subathon_seconds=subathon_seconds,
        show_days=timer_app["show_days"],
    )
    subathon_service.set_running(False)
    queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    shutdown_event = asyncio.Event()
    stop_requested = asyncio.Event()
    LOGGER.info(f"created shared queue (max_size={MAX_QUEUE_SIZE}) and shutdown event")

    patreon_runtime = PatreonRuntime(config_path, app_cfg.patreon.campaign_id)

    monitor_registry = MonitorStatusRegistry(build_initial_status(app_cfg, patreon_runtime))
    session_revenue = SessionRevenueStore()

    monitor_coordinator = MonitorCoordinator(
        monitor_registry,
        shutdown_event,
        factories={},
        app_cfg=app_cfg,
    )
    session_handles = SessionHandles(
        config_path=config_path,
        queue=queue,
        shutdown_event=shutdown_event,
        registry=monitor_registry,
        coordinator=monitor_coordinator,
        patreon_runtime=patreon_runtime,
    )
    session_handles._sync_factories(app_cfg)
    session_handles.set_connect_patreon(session_handles._build_connect_patreon(app_cfg))
    session_handles.set_connect_youtube(session_handles._build_connect_youtube(app_cfg))
    monitor_coordinator.start_restart_loop()
    LOGGER.info(
        "monitors ready to connect (not auto-started): %s",
        ", ".join(monitor_coordinator.factory_ids()) or "none",
    )

    user_config = normalized_user_config_for_ui(user_norm)

    ui_stop_event = asyncio.Event()
    ui_context = WebUiContext()
    ui_context.restart_requested = False
    ui_task = asyncio.create_task(
        run_async(
            "ui",
            run_web_server(
                app_cfg.app.ui_host,
                app_cfg.app.ui_port,
                ui_stop_event,
                goal_service=goal_service,
                subathon_service=subathon_service,
                event_queue=queue,
                    allow_test_events=app_cfg.app.enable_test_events,
                    patreon_runtime=patreon_runtime,
                    monitor_registry=monitor_registry,
                monitor_coordinator=monitor_coordinator,
                session_revenue=session_revenue,
                session_handles=session_handles,
                shutdown_event=shutdown_event,
                stop_requested=stop_requested,
                ui_context=ui_context,
                user_config=user_config,
                config_path=config_path,
                open_browser=open_browser,
                require_ws_token=app_cfg.app.require_ws_token,
            ),
            ui_stop_event,
            trigger_shutdown_on_error=False,
        ),
        name="ui",
    )
    LOGGER.info("started ui task: ui")

    db_task = asyncio.create_task(
        run_async(
            "db",
            db_writer.write_to_db(
                queue, shutdown_event, database, goal_service, session_revenue, subathon_service,
            ),
            shutdown_event,
            stop_requested=stop_requested,
        ),
        name="db",
    )
    subathon_task = asyncio.create_task(
        run_async(
            "subathon",
            subathon_service.tick_loop(shutdown_event),
            shutdown_event,
            stop_requested=stop_requested,
            trigger_shutdown_on_error=False,
        ),
        name="subathon",
    )
    LOGGER.info(f"started db task: {db_task.get_name()}")
    LOGGER.info(f"started subathon task: {subathon_task.get_name()}")

    restart_requested = False
    db_failed = False
    try:
        LOGGER.info("main waiting for shutdown (use UI Shutdown or Ctrl+C)")
        await stop_requested.wait()
        LOGGER.info("shutdown requested")
        db_failed = db_task.done() and db_task.exception() is not None
        if db_failed:
            LOGGER.info(f"db_failed={db_failed}")
        for task in list(monitor_coordinator._tasks.values()) + [db_task, subathon_task]:
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    LOGGER.error(f"task {task.get_name()} failed: {exc!r}", exc_info=exc)
    finally:
        LOGGER.info("main shutdown sequence starting")
        restart_requested = bool(ui_context.restart_requested)

        shutdown_event.set()
        LOGGER.info("shutdown event set; cancelling monitors")
        await monitor_coordinator.cancel_all()
        LOGGER.info("monitor tasks gather finished")

        if db_failed:
            LOGGER.warning("db task failed, dumping remaining queue items to remaining_queue.json")
            await dump_remaining_queue(queue, "remaining_queue.json")
            LOGGER.info("remaining queue dump complete")
        else:
            LOGGER.info("waiting for queue to drain before stopping db task")
            await queue.join()
            LOGGER.info("queue drained, stopping db task")
            await asyncio.gather(db_task, subathon_task, return_exceptions=True)
            LOGGER.info("db and subathon tasks stopped")

        if restart_requested:
            LOGGER.info("session ended for in-process restart")
        elif ui_context.broadcaster is not None:
            LOGGER.info("notifying UI that shutdown is complete")
            await ui_context.broadcaster.broadcast_shutdown_complete()
            await asyncio.sleep(0.75)

        if ui_task is not None:
            LOGGER.info("stopping ui task")
            ui_stop_event.set()
            await asyncio.gather(ui_task, return_exceptions=True)

        LOGGER.info("main shutdown sequence complete")

    return restart_requested


async def main(config_path: Path):
    open_browser = True
    while True:
        restart = await _run_app_session(
            config_path,
            open_browser=open_browser,
        )
        open_browser = False
        if not restart:
            break
        LOGGER.info("restarting application in-process with updated configuration")
        await asyncio.sleep(0.35)


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multistream revenue tracker — Twitch, YouTube, and Patreon monitors with a web dashboard.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Before starting, delete config.json and local runtime data (OAuth tokens, revenue "
            "database, goals, point rules, exchange-rate cache, session logs). Opens the "
            "dashboard defaults. Developer credentials are environment variables and are not removed."
        ),
    )
    return parser.parse_args()


def cli(default_config_path: Path) -> None:
    args = _parse_cli_args()
    config_path = default_config_path.resolve()

    if args.clean:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
        install_log_scrubbing_filter()
        removed = clean_transient_data(config_path)
        if removed:
            for line in removed:
                print(f"Removed: {line}", file=sys.stderr)
            LOGGER.info("--clean removed %s path(s)", len(removed))
        else:
            print("No transient data files found to remove.", file=sys.stderr)
            LOGGER.info("--clean: nothing to remove")
        return

    if config_exists(config_path):
        app_cfg = load_app_config(config_path)
        log_level = getattr(logging, app_cfg.app.log_level)
    else:
        log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    install_log_scrubbing_filter()
    register_log_broadcast_handler()
    if config_exists(config_path):
        LOGGER.info(
            "starting app (log_level=%s from config)",
            logging.getLevelName(log_level),
        )
    else:
        LOGGER.info("starting app (no config.json yet — using defaults)")
    try:
        asyncio.run(main(config_path))
    except KeyboardInterrupt:
        LOGGER.info("stopped by user")
    except SystemExit:
        raise
    except BaseException:
        _write_crash_log(config_path)
        raise


def _write_crash_log(config_path: Path) -> None:
    """Persist a scrubbed traceback so users can attach it to a bug report.

    Without this, a fatal exception only prints to stderr — which is invisible
    when launched from a Windows shortcut and gone after process exit. Writing
    a dated file alongside the existing session logs gives a single artifact
    to share. We deliberately route the traceback through the log scrubber
    first so OAuth tokens that may appear in object reprs are redacted.
    """
    try:
        log_dir = config_path.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        crash_path = log_dir / f"crash_{ts}.log"
        trace = "".join(traceback.format_exception(*sys.exc_info()))
        scrubbed = scrub_text(trace)
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(scrubbed)
        print(f"crash log written: {crash_path}", file=sys.stderr)
    except Exception:  # pragma: no cover - last-ditch best effort
        pass
