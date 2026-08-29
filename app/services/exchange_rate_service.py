import time
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
# durable, just fast on the common path. Only successful lookups are ever
# stored here — see get_rate for why a failure must never land in this cache.
_rate_cache: dict[tuple[str, str, date], float] = {}

# Most recent successful rate per currency pair, regardless of date — used
# as the fallback on a failed lookup instead of a blind 1.0, which silently
# treats (say) USD as INR 1:1 and is wrong by roughly the real exchange rate.
_last_known_good: dict[tuple[str, str], float] = {}

# Outcome of the last real Frankfurter call — distinct from the cache above,
# since a cache hit never tells you whether the API is currently reachable.
_last_status: dict = {"ok": None, "checked_at": None, "error": None}


def get_fx_status() -> dict:
    return dict(_last_status)


def get_rate(from_currency: str, on_date: date | None = None, to_currency: str = HOME_CURRENCY) -> float:
    """
    Exchange rate to convert 1 unit of from_currency into to_currency, as of
    on_date (defaults to today). Using the rate as of the transaction's own
    date (rather than always "now") keeps historical totals stable instead
    of drifting every time today's rate moves.

    Never raises — a transient FX API outage shouldn't break insights or
    budgets. On failure, falls back to the last successful rate seen for
    this currency pair (any date) rather than a blind 1.0, and — critically —
    does NOT cache the failure, so the very next call retries the API
    instead of quietly repeating a bad conversion for the rest of the day.
    """
    if from_currency == to_currency:
        return 1.0

    lookup_date = on_date or date.today()
    cache_key = (from_currency, to_currency, lookup_date)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    pair_key = (from_currency, to_currency)
    try:
        response = httpx.get(
            f"{FRANKFURTER_URL}/{lookup_date.isoformat()}",
            params={"base": from_currency, "symbols": to_currency},
            timeout=5.0
        )
        response.raise_for_status()
        rate = float(response.json()["rates"][to_currency])
        _last_status.update({"ok": True, "checked_at": time.time(), "error": None})
        _rate_cache[cache_key] = rate
        _last_known_good[pair_key] = rate
        return rate
    except Exception as e:
        _last_status.update({"ok": False, "checked_at": time.time(), "error": str(e)})
        if pair_key in _last_known_good:
            fallback = _last_known_good[pair_key]
            print(f"⚠️  FX lookup failed for {from_currency}->{to_currency} on {lookup_date}: {e}. "
                  f"Using last-known-good rate {fallback} instead of a blind 1.0.")
            return fallback
        print(f"⚠️  FX lookup failed for {from_currency}->{to_currency} on {lookup_date}: {e}. "
              f"No prior rate known for this pair — falling back to unconverted 1.0.")
        return 1.0


def to_home_currency(amount: float, currency: str, on_date: date | None = None) -> float:
    return amount * get_rate(currency, on_date)
