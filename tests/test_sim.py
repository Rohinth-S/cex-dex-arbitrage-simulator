import pytest
from arb_simulator.sim import Opportunity, execute, replay, metrics, net_pnl_for_size, size_opportunity
def test_failed_fill_has_zero_pnl():
    r=execute(Opportunity(101,100,1),fail_prob=1,seed=1); assert r["failed"] and r["net_pnl"]==0
def test_replay_metrics():
    m=metrics(replay(50)); assert 0<=m["fill_rate"]<=1 and "max_drawdown" in m
def test_empty_metrics_and_validation():
    assert metrics([])["trades"]==0
    with pytest.raises(ValueError): Opportunity(0,100,1)

def test_size_accounts_for_fixed_gas_and_depth_impact():
    o = Opportunity(101.0, 100.0, 1.0, gas_usd=.5)
    result = size_opportunity(o, capital_usd=1000, max_size=5, impact_bps_per_unit=5, step=.1)
    assert result.size > 0
    assert result.capital_used <= 1000
    assert result.net_pnl == pytest.approx(net_pnl_for_size(o, result.size, latency_ms=80, impact_bps_per_unit=5))

def test_costs_can_turn_a_thin_edge_negative():
    o = Opportunity(100.01, 100.0, 1.0, gas_usd=20)
    assert net_pnl_for_size(o, 1, slippage_bps=30) < 0
    assert size_opportunity(o, 1000, max_size=2, slippage_bps=30).size == 0
