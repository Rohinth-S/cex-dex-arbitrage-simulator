from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

@dataclass
class BinanceTestnetClient:
    base_url: str = "https://testnet.binance.vision"
    api_key: str | None = None
    timeout: float = 10.0

    def __post_init__(self) -> None:
        self.base_url = os.getenv("BINANCE_TESTNET_BASE_URL", self.base_url)
        self.api_key = self.api_key or os.getenv("BINANCE_TESTNET_API_KEY")

    def _get(self, path: str, params: dict[str, object]) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}?{urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
            payload = json.loads(response.read())
        if isinstance(payload, dict) and payload.get("code", 0) < 0:
            raise RuntimeError(f"Binance testnet request failed: {payload}")
        return payload

    def depth(self, symbol: str, limit: int = 20) -> dict:
        if not symbol or limit < 5 or limit > 1000:
            raise ValueError("symbol is required and limit must be between 5 and 1000")
        return self._get("/api/v3/depth", {"symbol": symbol.upper(), "limit": limit})

    def best_bid_ask(self, symbol: str) -> tuple[float, float]:
        book = self.depth(symbol, limit=5)
        if not book.get("bids") or not book.get("asks"):
            raise RuntimeError("Binance testnet returned an empty order book")
        return float(book["bids"][0][0]), float(book["asks"][0][0])
