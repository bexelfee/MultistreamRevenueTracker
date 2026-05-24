"""Dashboard external links: present in HTML and still reachable (no 404)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from multistream_revenue_tracker.ui.app import create_app
from multistream_revenue_tracker.ui.external_links import (
    GITHUB_ISSUES_HREF,
    PATREON_CLIENT_REGISTER_HREF,
    PICO_CSS_HREF,
    STREAMLABS_API_SETTINGS_HREF,
    external_link_check_targets,
)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; MultistreamRevenueTracker/1.0; +https://github.com/local/release-build)"
)


@pytest.mark.parametrize("label,url", external_link_check_targets())
def test_ui_external_link_is_reachable(label: str, url: str) -> None:
    """HEAD/GET vendor URLs; fails in CI if a link rots or returns 404."""
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=20.0, headers=headers) as client:
        response = client.head(url)
        if response.status_code in {405, 501} or response.status_code >= 400:
            response = client.get(url)
    assert response.status_code < 400, (
        f"{label} {url!r} returned HTTP {response.status_code}"
    )


def test_index_html_includes_patreon_client_register_link() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert PATREON_CLIENT_REGISTER_HREF in response.text
    assert "prefer additional security" in response.text


def test_index_html_includes_canonical_streamlabs_link() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert STREAMLABS_API_SETTINGS_HREF in response.text


def test_index_html_includes_canonical_pico_stylesheet() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert PICO_CSS_HREF in response.text


def test_index_html_includes_report_bug_link() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Report a Bug" in response.text
    assert GITHUB_ISSUES_HREF in response.text


def test_index_html_includes_app_version() -> None:
    from multistream_revenue_tracker import __version__

    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert f"v{__version__}" in response.text
