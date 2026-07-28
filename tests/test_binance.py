import pytest
from arb_simulator.binance import BinanceTestnetClient, normalize_order_book

def test_binance_client_does_not_call_network_on_construction(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_BASE_URL", "https://example.test")
    client = BinanceTestnetClient()
    assert client.base_url == "https://example.test"

def test_binance_validates_depth_limit():
    with pytest.raises(ValueError): BinanceTestnetClient().depth("BTCUSDT", limit=2)

def test_normalize_order_book_sorts_aggregates_and_prices_vwap():
    book = normalize_order_book({
        "lastUpdateId": 42,
        "bids": [["99", "1"], ["100", "0.5"], ["100", "0.25"]],
        "asks": [["101", "0.25"], ["102", "2"]],
    })
    assert book.best_bid == 100
    assert book.best_ask == 101
    assert book.vwap("buy", .5) == pytest.approx(101.5)
    assert book.last_update_id == 42

def test_normalize_rejects_crossed_or_empty_books():
    with pytest.raises(ValueError): normalize_order_book({"bids": [[101, 1]], "asks": [[100, 1]]})
    with pytest.raises(ValueError): normalize_order_book({"bids": [], "asks": [[101, 1]]})
