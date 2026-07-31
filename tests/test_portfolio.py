from arb_simulator.portfolio import Route, backtest_portfolio, portfolio_metrics
from arb_simulator.sim import Opportunity


def test_multi_route_backtest_and_metrics():
    routes = [Route("eth-usdc", Opportunity(101, 100, 1, gas_usd=.1), weight=2),
              Route("arb-usdc", Opportunity(202, 200, 1, gas_usd=.1), weight=1)]
    rows = backtest_portfolio(routes, capital_usd=1_000, rounds=8, seed=4, failure_probability=0)
    metrics = portfolio_metrics(rows)
    assert len(rows) == 16 and metrics["trades"] == 16
    assert set(metrics["by_route"]) == {"eth-usdc", "arb-usdc"}
    assert metrics["net_pnl"] > 0 and metrics["max_drawdown"] >= 0
