"""Multi-route arbitrage portfolio replay and risk metrics."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
import numpy as np

from .sim import Opportunity, execute, size_opportunity


@dataclass(frozen=True)
class Route:
    name: str
    opportunity: Opportunity
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.name or self.weight <= 0:
            raise ValueError("route name is required and weight must be positive")


def backtest_portfolio(
    routes: Sequence[Route],
    capital_usd: float,
    rounds: int = 100,
    *,
    seed: int = 17,
    failure_probability: float = 0.05,
) -> list[dict]:
    """Replay independently sized routes with deterministic per-round seeds."""
    if not routes or capital_usd <= 0 or rounds < 1 or not 0 <= failure_probability <= 1:
        raise ValueError("routes, capital, rounds, and failure probability are invalid")
    total_weight = sum(route.weight for route in routes)
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for round_id in range(rounds):
        for route in routes:
            route_capital = capital_usd * route.weight / total_weight
            sizing = size_opportunity(route.opportunity, route_capital, max_size=route.opportunity.size)
            if sizing.size <= 0:
                rows.append({"round": round_id, "route": route.name, "net_pnl": 0.0,
                             "fill_rate": 0.0, "failed": True, "sized": 0.0})
                continue
            sized = Opportunity(route.opportunity.cex_bid, route.opportunity.dex_ask, sizing.size,
                                route.opportunity.cex_fee, route.opportunity.dex_fee,
                                route.opportunity.gas_usd, route.opportunity.hedge_cost)
            result = execute(sized, latency_ms=float(rng.uniform(20, 180)),
                             fail_prob=failure_probability, seed=int(rng.integers(2**31 - 1)))
            result.update({"round": round_id, "route": route.name, "sized": sizing.size})
            rows.append(result)
    return rows


def portfolio_metrics(rows: Sequence[dict]) -> dict:
    """Compute aggregate and per-route PnL, drawdown, and risk-adjusted return."""
    if not rows:
        return {"trades": 0, "net_pnl": 0.0, "max_drawdown": 0.0, "sharpe_like": 0.0, "by_route": {}}
    pnl = np.asarray([float(row["net_pnl"]) for row in rows])
    curve = np.cumsum(pnl)
    drawdown = np.maximum.accumulate(curve) - curve
    by_route: dict[str, dict] = {}
    for route in sorted({str(row.get("route", "unknown")) for row in rows}):
        values = np.asarray([float(row["net_pnl"]) for row in rows if row.get("route", "unknown") == route])
        by_route[route] = {"trades": len(values), "net_pnl": float(values.sum()),
                           "fill_rate": float(np.mean([row["fill_rate"] for row in rows if row.get("route", "unknown") == route]))}
    return {"trades": len(rows), "net_pnl": float(pnl.sum()), "max_drawdown": float(drawdown.max()),
            "sharpe_like": float(pnl.mean() / (pnl.std() + 1e-9) * np.sqrt(len(pnl))), "by_route": by_route}
