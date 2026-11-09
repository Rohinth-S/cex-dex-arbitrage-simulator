from dataclasses import dataclass
import numpy as np
@dataclass
class Opportunity:
    cex_bid: float; dex_ask: float; size: float; cex_fee: float=.0004; dex_fee: float=.0005; gas_usd: float=4; hedge_cost: float=.0002

def execute(o: Opportunity, latency_ms=80, fail_prob=.05, seed=9):
    rng=np.random.default_rng(seed); failed=bool(rng.random()<fail_prob)
    gross=(o.cex_bid-o.dex_ask)*o.size
    costs=o.cex_bid*o.size*(o.cex_fee+o.hedge_cost)+o.dex_ask*o.size*o.dex_fee+o.gas_usd
    slippage=(latency_ms/1000)*0.0008*o.size*o.cex_bid
    pnl=0.0 if failed else gross-costs-slippage
    return {"gross_edge":gross,"costs":costs,"latency_slippage":slippage,"failed":failed,"net_pnl":pnl,"fill_rate":0.0 if failed else 1.0}

def replay(n=200, seed=5):
    rng=np.random.default_rng(seed); rows=[]
    for _ in range(n):
      mid=100+rng.normal(0,1); edge=max(0,rng.normal(.15,.12)); size=rng.uniform(.2,2.0)
      rows.append(execute(Opportunity(mid+edge,mid,size),int(rng.uniform(20,180)),seed=int(rng.integers(1_000_000))))
    return rows

def metrics(rows):
    pnl=np.array([r["net_pnl"] for r in rows]); return {"net_pnl":float(pnl.sum()),"fill_rate":float(np.mean([r["fill_rate"] for r in rows])),"sharpe_like":float(pnl.mean()/(pnl.std()+1e-9)*np.sqrt(len(pnl))),"max_drawdown":float(np.max(np.maximum.accumulate(np.cumsum(pnl))-np.cumsum(pnl)))}
