from __future__ import annotations

import asyncio
import json
import logging
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any, AsyncIterator

import httpx

from ..config import PatreonConfig
from ..monitors.monitor_constants import MONITOR_AUTH_TIMEOUT_SECONDS
from ..log_scrubbing import register_patreon_token
from .patreon_catalog import PatreonCatalog, parse_campaigns_payload

LOGGER = logging.getLogger(__name__)

_oauth_cancel_lock = threading.Lock()
_oauth_cancel_event: Event | None = None
_oauth_server: HTTPServer | None = None


PATREON_CONNECT_CANCELLED = "__patreon_connect_cancelled__"


class PatreonOAuthCancelled(Exception):
    """Raised when Patreon browser OAuth is interrupted (disconnect, shutdown, or Cancel)."""


# Re-exported under the original private name so existing call sites in this
# file (and the YouTube monitor) read the same way without further churn.
from .oauth_local_server import force_close_oauth_server as _force_close_oauth_server  # noqa: E402


def cancel_pending_oauth() -> None:
    """Unblock an in-progress Patreon OAuth flow (same effect as Cancel in the UI)."""
    with _oauth_cancel_lock:
        if _oauth_cancel_event is not None:
            _oauth_cancel_event.set()
        _force_close_oauth_server(_oauth_server)


PATREON_API_BASE = "https://www.patreon.com"
PATREON_AUTHORIZE_URL = f"{PATREON_API_BASE}/oauth2/authorize"
PATREON_TOKEN_URL = f"{PATREON_API_BASE}/api/oauth2/token"
PATREON_SCOPES = "identity campaigns campaigns.members"

MEMBER_FIELDS = (
    "full_name,patron_status,last_charge_date,last_charge_status,"
    "currently_entitled_amount_cents,pledge_relationship_start"
)


@dataclass
class PatreonToken:
    access_token: str
    refresh_token: str | None
    expires_in: int | None = None
    token_type: str = "Bearer"
    scope: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "token_type": self.token_type,
            "scope": self.scope,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> PatreonToken:
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
        )


class PatreonApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class PatreonClient:
    def __init__(self, config: PatreonConfig, token: PatreonToken):
        self._config = config
        self._token = token
        self._http = httpx.AsyncClient(base_url=PATREON_API_BASE, timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def token(self) -> PatreonToken:
        return self._token

    async def fetch_campaigns_with_tiers(self) -> PatreonCatalog:
        catalog = PatreonCatalog()
        params = {
            "fields[campaign]": "creation_name",
            "include": "tiers",
            "fields[tier]": "title,amount_cents,published",
            "page[count]": "100",
        }
        path = "/api/oauth2/v2/campaigns"
        while path:
            payload = await self._api_get(path, params=params if path.startswith("/api") else None)
            page = parse_campaigns_payload(payload)
            catalog.campaigns.extend(page.campaigns)
            for campaign_id, tiers in page.tiers_by_campaign.items():
                catalog.tiers_by_campaign.setdefault(campaign_id, []).extend(tiers)
            path = _next_link(payload)
            params = None
        _dedupe_catalog(catalog)
        return catalog

    async def fetch_campaign_tiers(self, campaign_id: str) -> list:
        params = {
            "fields[campaign]": "creation_name",
            "include": "tiers",
            "fields[tier]": "title,amount_cents,published",
        }
        payload = await self._api_get(f"/api/oauth2/v2/campaigns/{campaign_id}", params=params)
        page = parse_campaigns_payload({"data": [payload.get("data")], "included": payload.get("included") or []})
        return page.tiers_by_campaign.get(campaign_id, [])

    async def iter_campaign_members(self, campaign_id: str) -> AsyncIterator[dict[str, Any]]:
        params = {
            "fields[member]": MEMBER_FIELDS,
            "page[count]": "100",
        }
        path = f"/api/oauth2/v2/campaigns/{campaign_id}/members"
        while path:
            payload = await self._api_get(path, params=params if path.startswith("/api") else None)
            for item in payload.get("data") or []:
                if item.get("type") == "member":
                    yield item
            path = _next_link(payload)
            params = None

    async def _api_get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else path
        attempt = 0
        while True:
            attempt += 1
            response = await self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token.access_token}"},
            )
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                LOGGER.warning("Patreon rate limited; retrying in %ss (attempt %s)", retry_after, attempt)
                await asyncio.sleep(retry_after)
                if attempt < 8:
                    continue
            if response.status_code >= 400:
                raise PatreonApiError(
                    f"Patreon API {response.status_code}: {response.text[:500]}",
                    status_code=response.status_code,
                    payload=_safe_json(response),
                )
            return response.json()

    async def refresh_access_token(self) -> PatreonToken:
        if not self._token.refresh_token:
            raise PatreonApiError("Patreon token has no refresh_token; re-run OAuth.")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        token = await _exchange_token_async(self._http, data)
        self._token = token
        save_token(self._config.token_path, token)
        return token


def load_token(path: Path) -> PatreonToken | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not raw.get("access_token"):
        return None
    return PatreonToken.from_json_dict(raw)


def save_token(path: Path, token: PatreonToken) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token.to_json_dict(), indent=2), encoding="utf-8")
    register_patreon_token(token)


async def ensure_patreon_token(config: PatreonConfig) -> PatreonToken:
    token = load_token(config.token_path)
    if token and token.refresh_token:
        async with httpx.AsyncClient(base_url=PATREON_API_BASE, timeout=30.0) as http:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
            }
            try:
                refreshed = await _exchange_token_async(http, data)
                save_token(config.token_path, refreshed)
                return refreshed
            except PatreonApiError:
                LOGGER.warning("Patreon token refresh failed; starting OAuth flow")
    elif token and token.access_token:
        return token
    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    result: list[PatreonToken] = []
    error: list[BaseException] = []

    def _oauth_target() -> None:
        try:
            result.append(_run_oauth_flow(config))
        except BaseException as exc:
            error.append(exc)
        finally:
            loop.call_soon_threadsafe(done.set)

    oauth_thread = Thread(target=_oauth_target, daemon=True, name="patreon-oauth")
    oauth_thread.start()
    try:
        await done.wait()
    except asyncio.CancelledError:
        cancel_pending_oauth()
        oauth_thread.join(timeout=2.0)
        raise
    if error:
        exc = error[0]
        if isinstance(exc, PatreonOAuthCancelled):
            raise PatreonApiError("Patreon authorisation cancelled") from None
        raise exc
    return result[0]


def _run_oauth_flow(config: PatreonConfig) -> PatreonToken:
    redirect = urllib.parse.urlparse(config.redirect_uri)
    if redirect.scheme not in {"http", "https"} or not redirect.hostname:
        raise ValueError(f"Invalid patreon.redirect_uri: {config.redirect_uri}")
    port = redirect.port or (443 if redirect.scheme == "https" else 80)
    path = redirect.path or "/callback"

    state = secrets.token_urlsafe(16)
    auth_code: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid state")
                return
            if "error" in query:
                auth_code["error"] = query.get("error", ["access_denied"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Patreon authorisation failed. You can close this tab.")
                return
            code = query.get("code", [""])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return
            auth_code["code"] = code
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"Patreon authorisation complete. You can close this tab.")

        def log_message(self, format, *args):
            return

    cancel = Event()
    with _oauth_cancel_lock:
        global _oauth_cancel_event, _oauth_server
        _oauth_cancel_event = cancel

    server = HTTPServer((redirect.hostname, port), Handler)
    server.socket.settimeout(0.25)
    with _oauth_cancel_lock:
        _oauth_server = server

    def _serve_until_callback() -> None:
        while not cancel.is_set():
            if auth_code:
                return
            try:
                server.handle_request()
            except socket.timeout:
                continue
            except OSError:
                return
            if auth_code:
                return

    thread = Thread(target=_serve_until_callback, daemon=True)
    thread.start()

    try:
        params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": PATREON_SCOPES,
            "state": state,
        })
        url = f"{PATREON_AUTHORIZE_URL}?{params}"
        LOGGER.info("Opening Patreon OAuth in browser")
        webbrowser.open(url)
        deadline = time.monotonic() + MONITOR_AUTH_TIMEOUT_SECONDS
        while thread.is_alive() and time.monotonic() < deadline:
            if cancel.is_set():
                raise PatreonOAuthCancelled()
            if auth_code:
                break
            time.sleep(0.05)
        if cancel.is_set():
            raise PatreonOAuthCancelled()
    finally:
        _force_close_oauth_server(server)
        thread.join(timeout=2.0)
        with _oauth_cancel_lock:
            if _oauth_cancel_event is cancel:
                _oauth_cancel_event = None
            if _oauth_server is server:
                _oauth_server = None

    if "error" in auth_code:
        raise PatreonApiError(f"Patreon authorisation denied: {auth_code['error']}")
    if "code" not in auth_code:
        raise PatreonApiError("Patreon OAuth timed out or was denied")

    data = {
        "grant_type": "authorization_code",
        "code": auth_code["code"],
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    with httpx.Client(base_url=PATREON_API_BASE, timeout=30.0) as http:
        token = _exchange_token_sync(http, data)
    save_token(config.token_path, token)
    return token


def _token_from_response(response: httpx.Response) -> PatreonToken:
    if response.status_code >= 400:
        raise PatreonApiError(
            f"Patreon token exchange failed: {response.status_code} {response.text[:500]}",
            status_code=response.status_code,
        )
    payload = response.json()
    return PatreonToken(
        access_token=str(payload["access_token"]),
        refresh_token=payload.get("refresh_token"),
        expires_in=payload.get("expires_in"),
        token_type=payload.get("token_type", "Bearer"),
        scope=payload.get("scope"),
    )


async def _exchange_token_async(http: httpx.AsyncClient, data: dict[str, str]) -> PatreonToken:
    response = await http.post(PATREON_TOKEN_URL, data=data)
    return _token_from_response(response)


def _exchange_token_sync(http: httpx.Client, data: dict[str, str]) -> PatreonToken:
    response = http.post(PATREON_TOKEN_URL, data=data)
    return _token_from_response(response)


def _next_link(payload: dict[str, Any]) -> str | None:
    links = payload.get("links") or {}
    next_url = links.get("next")
    if not next_url:
        return None
    parsed = urllib.parse.urlparse(next_url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _retry_after_seconds(response: httpx.Response) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return max(1.0, float(header))
        except ValueError:
            pass
    payload = _safe_json(response)
    errors = payload.get("errors") or []
    for err in errors:
        value = err.get("retry_after_seconds")
        if value is not None:
            return max(1.0, float(value))
    return min(60.0, 2.0 ** 3)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {}


def _dedupe_catalog(catalog: PatreonCatalog) -> None:
    by_id: dict[str, Any] = {}
    for campaign in catalog.campaigns:
        by_id[campaign.id] = campaign
    catalog.campaigns = list(by_id.values())
    catalog.campaigns.sort(key=lambda c: c.name.lower())
    for campaign_id in list(catalog.tiers_by_campaign.keys()):
        tiers = catalog.tiers_by_campaign[campaign_id]
        seen: set[str] = set()
        unique = []
        for tier in sorted(tiers, key=lambda t: t.amount_cents):
            if tier.tier_id in seen:
                continue
            seen.add(tier.tier_id)
            unique.append(tier)
        catalog.tiers_by_campaign[campaign_id] = unique
