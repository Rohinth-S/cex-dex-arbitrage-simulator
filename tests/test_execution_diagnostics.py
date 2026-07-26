import pytest

from arb_simulator.binance import normalize_order_book
from arb_simulator.replay import replay_tape, summarize_tape
from arb_simulator.tape import ReplayConfig, Tape
from test_tape_replay import tape_with_depth


def test_order_book_rejects_fractional_update_and_insufficient_tiny_depth():
    feed = {"bids": [[100, 1e-15]], "asks": [[101, 1e-15]]}
    with pytest.raises(ValueError, match="depth"):
        normalize_order_book(feed).vwap("buy", 2e-15)
    with pytest.raises(ValueError, match="lastUpdateId"):
        normalize_order_book({**feed, "lastUpdateId": 0.5})
    with pytest.raises(ValueError, match="invalid asks"):
        normalize_order_book({**feed, "asks": [[None, 1]]})

def test_execution_uses_market_age_caps_and_explains_edge_decay():
    tape = tape_with_depth()
    fast = ReplayConfig(cex_latency_ms=50, dex_latency_ms=100)
    rows = replay_tape(tape, fast)
    trade = next(row for row in rows if row["status"] == "filled")
    assert trade["scheduled_cex_ms"] == trade["execution_book_ms"] == 50
    assert trade["execution_dex_quote_age_ms"] == 100
    assert trade["edge_decay_usd"] == pytest.approx(trade["spread_decay_usd"] + trade["cost_drift_usd"])
    assert trade["fees_usd"] == pytest.approx(trade["cex_fees_usd"] + trade["dex_fees_usd"])
    stale = ReplayConfig(cex_latency_ms=50, dex_latency_ms=100, dex_max_age_ms=90)
    failure = next(row for row in replay_tape(tape, stale) if row["status"] == "failed_stale")
    assert failure["gas_mark_source"] == "signal_dex"

def test_atomic_ledger_roundtrip(tmp_path):
    import csv
    import duckdb
    from arb_simulator.cli import _write_ledger

    rows = replay_tape(tape_with_depth(), ReplayConfig(cex_latency_ms=50, dex_latency_ms=100))
    csv_path, parquet_path = tmp_path / "run.CSV", tmp_path / "run.parquet"
    _write_ledger(csv_path, rows)
    _write_ledger(parquet_path, rows)
    with csv_path.open(newline="", encoding="utf-8") as stream:
        assert [row["status"] for row in csv.DictReader(stream)] == [row["status"] for row in rows]
    with duckdb.connect() as conn:
        assert conn.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]).fetchone() == (len(rows),)
