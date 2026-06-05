from __future__ import annotations

from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Opportunity:
    cex_bid: float
    dex_ask: float
    size: float
    cex_fee: float = .0004
    dex_fee: float = .0005
    gas_usd: float = 4
    hedge_cost: float = .0002

    def __post_init__(self) -> None:
        if self.cex_bid <= 0 or self.dex_ask <= 0 or self.size <= 0:
            raise ValueError("prices and size must be positive")
        if min(self.cex_fee, self.dex_fee, self.gas_usd, self.hedge_cost) < 0:
            raise ValueError("execution costs cannot be negative")

def execute(o: Opportunity, latency_ms: float = 80, fail_prob: float = .05, seed: int = 9) -> dict:
    if latency_ms < 0 or not 0 <= fail_prob <= 1:
        raise ValueError("latency must be non-negative and fail_prob must be between 0 and 1")
    failed = bool(np.random.default_rng(seed).random() < fail_prob)
    gross = (o.cex_bid - o.dex_ask) * o.size
    costs = o.cex_bid * o.size * (o.cex_fee + o.hedge_cost) + o.dex_ask * o.size * o.dex_fee + o.gas_usd
    latency_slippage = (latency_ms / 1000) * 0.0008 * o.size * o.cex_bid
    net_pnl = 0.0 if failed else gross - costs - latency_slippage
    return {"gross_edge": gross, "gross_edge_bps": (o.cex_bid / o.dex_ask - 1) * 1e4, "costs": costs, "latency_slippage": latency_slippage, "failed": failed, "net_pnl": net_pnl, "fill_rate": 0.0 if failed else 1.0}

def replay(n: int = 200, seed: int = 5) -> list[dict]:
    if n < 1:
        raise ValueError("n must be positive")
    rng = np.random.default_rng(seed); rows = []
    for _ in range(n):
        mid = 100 + rng.normal(0, 1); edge = max(0, rng.normal(.15, .12)); size = rng.uniform(.2, 2.0)
        rows.append(execute(Opportunity(mid + edge, mid, size), float(rng.uniform(20, 180)), seed=int(rng.integers(1_000_000))))
    return rows

def metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"net_pnl": 0.0, "fill_rate": 0.0, "sharpe_like": 0.0, "max_drawdown": 0.0, "trades": 0}
    pnl = np.array([r["net_pnl"] for r in rows], dtype=float); curve = np.cumsum(pnl); drawdown = np.maximum.accumulate(curve) - curve
    return {"net_pnl": float(pnl.sum()), "fill_rate": float(np.mean([r["fill_rate"] for r in rows])), "sharpe_like": float(pnl.mean() / (pnl.std() + 1e-9) * np.sqrt(len(pnl))), "max_drawdown": float(drawdown.max()), "trades": len(rows)}
