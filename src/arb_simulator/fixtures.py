"""A seeded two-market feed with quote movement and temporary liquidity gaps."""

import numpy as np

from .tape import BookSnapshot, DexQuote, Tape, TapeTrade


def demo_tape(seed: int = 17) -> Tape:
    rng = np.random.default_rng(seed)
    books, dex_quotes, trades = [], [], []
    for market, base in (("ETH-USDC", 2_100), ("ALT-USDC", 95)):
        steps = rng.normal(0.0, base * 0.001, 60).cumsum()
        for index, step in enumerate(steps):
            quote_time = index * 120
            cex_mid = base + step
            dex_mid = cex_mid * (1 + rng.normal(0.0, 0.0035))
            quantity = 0.15 if index % 11 == 5 else 2 + float(rng.random())
            half_spread = base * 0.0002
            books.append(BookSnapshot(
                market=market, time_ms=quote_time,
                bids=[(cex_mid - half_spread, quantity), (cex_mid - 2 * half_spread, quantity)],
                asks=[(cex_mid + half_spread, quantity), (cex_mid + 2 * half_spread, quantity)],
            ))
            dex_quotes.append(DexQuote(
                market=market, time_ms=quote_time + 10, ask=dex_mid + half_spread, bid=dex_mid - half_spread,
                max_qty=1.5 if index % 7 else 0.7, gas_usd=0.6 + index % 3 * 0.15, impact_bps_per_unit=3,
            ))
            trades.append(TapeTrade(market=market, time_ms=quote_time + 30, price=cex_mid, quantity=0.2))
    return Tape(books=books, dex_quotes=dex_quotes, cex_trades=trades)
