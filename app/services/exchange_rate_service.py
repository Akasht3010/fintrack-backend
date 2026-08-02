from datetime import date

import httpx

# Every aggregate figure in the app (Home summary, Insights, Budgets, net
# worth) is expressed in this currency — individual transactions/accounts
# can be in whatever currency they were actually made in.
HOME_CURRENCY = "INR"

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"

# Keyed by (from_currency, to_currency, date) — rates don't change intraday
# for this app's purposes, so caching by day avoids hitting the external
# API on every insights/budget/net-worth request. Resets on server
# restart, which is fine: a personal expense tracker doesn't need this
# durable, just fast on the common path.
_rate_cache: dict[tuple[str, str, date], float] = {}


def get_rate(from_currency: str, on_date: date | None = None, to_currency: str = HOME_CURRENCY) -> float:
    """
    Exchange rate to convert 1 unit of from_currency into to_currency, as of
    on_date (defaults to today). Using the rate as of the transaction's own
    date (rather than always "now") keeps historical totals stable instead
    of drifting every time today's rate moves.

    Never raises — a transient FX API outage shouldn't break insights or
    budgets, so a failed lookup falls back to 1.0 (no conversion) rather
    than surfacing an error on unrelated screens.
    """
    if from_currency == to_currency:
        return 1.0

    lookup_date = on_date or date.today()
    cache_key = (from_currency, to_currency, lookup_date)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    try:
        response = httpx.get(
            f"{FRANKFURTER_URL}/{lookup_date.isoformat()}",
            params={"base": from_currency, "symbols": to_currency},
            timeout=5.0
        )
        response.raise_for_status()
        rate = float(response.json()["rates"][to_currency])
    except Exception:
        rate = 1.0

    _rate_cache[cache_key] = rate
    return rate


def to_home_currency(amount: float, currency: str, on_date: date | None = None) -> float:
    return amount * get_rate(currency, on_date)
