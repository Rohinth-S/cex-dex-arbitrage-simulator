import pytest
from arb_simulator.binance import BinanceTestnetClient

def test_binance_client_does_not_call_network_on_construction(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_BASE_URL", "https://example.test")
    client = BinanceTestnetClient()
    assert client.base_url == "https://example.test"

def test_binance_validates_depth_limit():
    with pytest.raises(ValueError): BinanceTestnetClient().depth("BTCUSDT", limit=2)
