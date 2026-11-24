import pytest

from arb_simulator.fixtures import demo_tape
from arb_simulator.replay import DEX_BUY, replay_tape, summarize_tape
from arb_simulator.tape import ReplayConfig, Tape


def tape_with_depth(second_quantity=2):
    market = "ETH-USDC"
    return Tape.model_validate({
        "books": [
            {"market": market, "time_ms": 0, "bids": [[120, 0.5], [118, 1]], "asks": [[121, 2]]},
            {"market": market, "time_ms": 50, "bids": [[117, second_quantity]], "asks": [[118, 2]]},
        ],
        "dex_quotes": [
            {"market": market, "time_ms": 0, "bid": 99, "ask": 100, "max_qty": 2, "gas_usd": 2},
        ],
        "observed_through_ms": 200,
    })


def config():
    return ReplayConfig(cex_latency_ms=50, dex_latency_ms=100, cex_fee_bps=0, dex_fee_bps=0, hedge_bps=0)


def test_signal_is_causal_and_fill_marks_at_completion_times():
    rows = replay_tape(tape_with_depth(), config())
    fill = next(row for row in rows if row["status"] == "filled")
    assert fill["direction"] == DEX_BUY
    assert fill["signal_book_ms"] == 0 and fill["execution_book_ms"] == 50
    assert fill["expected_pnl_usd"] == 17
    assert fill["net_pnl_usd"] == 15 and fill["edge_decay_usd"] == 2


def test_depth_failure_debits_gas_and_uses_starting_equity_for_drawdown():
    tape = tape_with_depth(0.1)
    cfg = config()
    rows = replay_tape(tape, cfg)
    failure = next(row for row in rows if row["status"] == "failed_depth")
    assert failure["net_pnl_usd"] == pytest.approx(-1.4)
    summary = summarize_tape(tape, rows, cfg)["portfolio"]
    assert summary["fill_rate"] == 0
    assert summary["max_drawdown_usd"] == pytest.approx(1.4)


def test_final_unobserved_execution_is_censored():
    dataset = tape_with_depth().model_dump()
    dataset["observed_through_ms"] = None
    replay = replay_tape(Tape.model_validate(dataset), config())
    assert replay[0]["status"] == "censored"
    assert all(row["status"] != "filled" for row in replay)


def test_demo_is_seeded_and_attempts_count_only_observed_executions():
    tape = demo_tape()
    rows = replay_tape(tape)
    assert rows == replay_tape(demo_tape())
    report = summarize_tape(tape, rows, ReplayConfig())
    assert len(report["by_market"]) == 2
    assert report["portfolio"]["attempts"] > report["portfolio"]["fills"] > 0
    assert report["portfolio"]["net_pnl_usd"] == pytest.approx(sum(row["net_pnl_usd"] for row in rows))
