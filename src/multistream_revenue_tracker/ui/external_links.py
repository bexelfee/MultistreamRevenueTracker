"""Canonical external URLs shown in the dashboard UI (single source for templates and tests)."""

from __future__ import annotations

from urllib.parse import urldefrag, urlparse

from multistream_revenue_tracker import __version__

# User-facing links (update here when a vendor changes URLs).
STREAMLABS_API_SETTINGS_HREF = "https://streamlabs.com/dashboard#/settings/api-settings"
PATREON_CLIENT_REGISTER_HREF = (
    "https://www.patreon.com/portal/registration/register-clients"
)
# Pin to a specific Pico CSS minor version (rather than `@2`) so a published
# upstream change cannot silently re-style the dashboard between two of our
# releases. Bump deliberately when we want to pick up new styles.
PICO_CSS_HREF = "https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css"
GITHUB_ISSUES_HREF = "https://github.com/bexelfee/MultistreamRevenueTracker/issues"

# Jinja globals for templates
UI_EXTERNAL_LINK_TEMPLATE_VARS = {
    "streamlabs_api_settings_href": STREAMLABS_API_SETTINGS_HREF,
    "patreon_client_register_href": PATREON_CLIENT_REGISTER_HREF,
    "pico_css_href": PICO_CSS_HREF,
    "github_issues_href": GITHUB_ISSUES_HREF,
    "app_version": __version__,
}


def request_url_for_href(href: str) -> str:
    """HTTP request URL (fragments are not sent to the server)."""
    base, _fragment = urldefrag(href)
    return base


def external_link_check_targets() -> list[tuple[str, str]]:
    """(label, url) pairs used by reachability tests."""
    return [
        ("streamlabs_api_settings", request_url_for_href(STREAMLABS_API_SETTINGS_HREF)),
        ("patreon_client_register", PATREON_CLIENT_REGISTER_HREF),
        ("pico_css_cdn", PICO_CSS_HREF),
    ]
