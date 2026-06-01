from arb_simulator.sim import Opportunity,execute,replay,metrics
def test_failed_fill_has_zero_pnl():
 r=execute(Opportunity(101,100,1),fail_prob=1,seed=1); assert r["failed"] and r["net_pnl"]==0
def test_replay_metrics():
 m=metrics(replay(50)); assert 0<=m["fill_rate"]<=1 and "max_drawdown" in m
