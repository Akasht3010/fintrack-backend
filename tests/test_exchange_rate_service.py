from datetime import date
from unittest.mock import MagicMock, patch

from app.services import exchange_rate_service as ers


def setup_function():
    # Each test gets a clean cache — otherwise earlier tests' cached rates
    # leak in and later tests can't tell if httpx.get was really called.
    ers._rate_cache.clear()


def test_same_currency_short_circuits_without_a_network_call():
    with patch("app.services.exchange_rate_service.httpx.get") as mock_get:
        rate = ers.get_rate("INR", date(2026, 8, 1), "INR")
        assert rate == 1.0
        mock_get.assert_not_called()


def test_successful_lookup_returns_the_api_rate():
    mock_response = MagicMock()
    mock_response.json.return_value = {"amount": 1.0, "base": "USD", "date": "2026-07-31", "rates": {"INR": 95.39}}
    with patch("app.services.exchange_rate_service.httpx.get", return_value=mock_response) as mock_get:
        rate = ers.get_rate("USD", date(2026, 8, 1), "INR")
        assert rate == 95.39
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"base": "USD", "symbols": "INR"}


def test_result_is_cached_per_currency_pair_and_date():
    mock_response = MagicMock()
    mock_response.json.return_value = {"rates": {"INR": 95.39}}
    with patch("app.services.exchange_rate_service.httpx.get", return_value=mock_response) as mock_get:
        ers.get_rate("USD", date(2026, 8, 1), "INR")
        ers.get_rate("USD", date(2026, 8, 1), "INR")
        assert mock_get.call_count == 1


def test_different_dates_are_cached_separately():
    mock_response = MagicMock()
    mock_response.json.return_value = {"rates": {"INR": 95.39}}
    with patch("app.services.exchange_rate_service.httpx.get", return_value=mock_response) as mock_get:
        ers.get_rate("USD", date(2026, 8, 1), "INR")
        ers.get_rate("USD", date(2026, 8, 2), "INR")
        assert mock_get.call_count == 2


def test_api_failure_falls_back_to_no_conversion_rather_than_raising():
    with patch("app.services.exchange_rate_service.httpx.get", side_effect=Exception("network down")):
        rate = ers.get_rate("USD", date(2026, 8, 1), "INR")
        assert rate == 1.0


def test_to_home_currency_multiplies_amount_by_the_rate():
    mock_response = MagicMock()
    mock_response.json.return_value = {"rates": {"INR": 95.39}}
    with patch("app.services.exchange_rate_service.httpx.get", return_value=mock_response):
        converted = ers.to_home_currency(10.0, "USD", date(2026, 8, 1))
        assert converted == 953.9
