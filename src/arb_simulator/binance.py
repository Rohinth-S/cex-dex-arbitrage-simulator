from __future__ import annotations

import json
import os
from dataclasses import dataclass
from collections import defaultdict
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class BookLevel:
    price: float
    quantity: float


@dataclass(frozen=True)
class NormalizedOrderBook:
    """Canonical, numeric Binance book used by the simulator and adapters."""

    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    last_update_id: int | None = None

    @property
    def best_bid(self) -> float:
        return self.bids[0].price

    @property
    def best_ask(self) -> float:
        return self.asks[0].price

    def vwap(self, side: str, quantity: float) -> float:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        levels = self.asks if side.lower() == "buy" else self.bids if side.lower() == "sell" else ()
        if not levels:
            raise ValueError("side must be buy or sell and the book cannot be empty")
        remaining = quantity
        notional = 0.0
        for level in levels:
            take = min(remaining, level.quantity)
            notional += take * level.price
            remaining -= take
            if remaining <= 1e-12:
                return notional / quantity
        raise ValueError("insufficient order-book depth")


def normalize_order_book(payload: dict, depth: int | None = None) -> NormalizedOrderBook:
    """Normalize Binance's string ``[price, quantity]`` levels.

    Duplicate prices are aggregated and levels are sorted best-first.  This
    protects simulations from feed-specific ordering and decimal-string
    quirks while retaining the exchange update id for replay diagnostics.
    """
    if not isinstance(payload, dict):
        raise ValueError("order book payload must be an object")

    def parse(raw: object, side: str) -> tuple[BookLevel, ...]:
        if not isinstance(raw, list):
            raise ValueError(f"{side} must be a list")
        aggregated: defaultdict[float, float] = defaultdict(float)
        for level in raw:
            if not isinstance(level, (list, tuple)) or len(level) != 2:
                raise ValueError(f"invalid {side} level")
            price, quantity = float(level[0]), float(level[1])
            if price <= 0 or quantity <= 0:
                raise ValueError("book prices and quantities must be positive")
            aggregated[price] += quantity
        values = sorted(aggregated.items(), key=lambda item: item[0], reverse=side == "bids")
        if depth is not None:
            values = values[:depth]
        return tuple(BookLevel(price, quantity) for price, quantity in values)

    if depth is not None and depth < 1:
        raise ValueError("depth must be positive")
    bids, asks = parse(payload.get("bids"), "bids"), parse(payload.get("asks"), "asks")
    if not bids or not asks:
        raise ValueError("order book must contain both bids and asks")
    if bids[0].price >= asks[0].price:
        raise ValueError("crossed order book")
    update_id = payload.get("lastUpdateId")
    return NormalizedOrderBook(bids, asks, int(update_id) if update_id is not None else None)

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
        return (lambda book: (book.best_bid, book.best_ask))(normalize_order_book(self.depth(symbol, limit=5)))
