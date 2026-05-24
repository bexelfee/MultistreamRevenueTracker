from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Open access, no API key: https://www.exchangerate-api.com/docs/free
OPEN_ER_API_URL = "https://open.er-api.com/v6/latest/EUR"
ATTRIBUTION = "Rates via ExchangeRate-API — https://www.exchangerate-api.com"


def fetch_rates_to_eur() -> dict[str, float]:
    """Return EUR per 1 unit of each currency (ExchangeRate-API open, base EUR)."""
    request = urllib.request.Request(OPEN_ER_API_URL, headers={"User-Agent": "multistream-revenue-tracker"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("result") != "success":
        raise ValueError(f"exchange rate API returned result={payload.get('result')!r}")
    rates_from_eur = payload.get("rates") or {}
    rates_to_eur: dict[str, float] = {}
    for currency, units_per_eur in rates_from_eur.items():
        if not currency or units_per_eur in (None, 0):
            continue
        code = str(currency).upper()
        rates_to_eur[code] = 1.0 if code == "EUR" else 1.0 / float(units_per_eur)
    if "EUR" not in rates_to_eur:
        rates_to_eur["EUR"] = 1.0
    return rates_to_eur


def _load_rates_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def refresh_exchange_rates_file(path: Path, base_currency: str = "EUR") -> dict:
    """Fetch live rates and write exchange_rates.json; on failure use existing file if present."""
    try:
        rates_to_eur = fetch_rates_to_eur()
        data = {
            "base_currency": base_currency.upper(),
            "source": "exchangerate-api-open",
            "attribution": ATTRIBUTION,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "rates_to_eur": rates_to_eur,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        LOGGER.info("exchange rates updated (%s currencies) -> %s", len(rates_to_eur), path)
        return data
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        if path.is_file():
            LOGGER.warning("exchange rate fetch failed (%s); using existing file %s", exc, path)
            return _load_rates_file(path)
        LOGGER.error(
            "exchange rate fetch failed (%s) and no local file at %s — "
            "monetary donations in unknown currencies will score 0 points until rates are available",
            exc,
            path,
        )
        return {
            "base_currency": base_currency.upper(),
            "source": "unavailable",
            "attribution": ATTRIBUTION,
            "fetched_at": None,
            "rates_to_eur": {"EUR": 1.0},
        }
