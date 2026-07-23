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
