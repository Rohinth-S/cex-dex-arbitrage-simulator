"""Replay a normalized tape or capture a read-only Binance snapshot."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .artifacts import write_text_atomic

from . import __version__
from .artifacts import require_distinct_paths
import time

import duckdb
import pandas as pd

from .binance import BinanceTestnetClient, normalize_order_book
from .fixtures import demo_tape
from .replay import replay_tape, summarize_tape
from .tape import BookSnapshot, ReplayConfig, Tape


def _write(path: Path | None, payload: str) -> None:
    if path:
        write_text_atomic(path, payload)


def _write_ledger(path: Path, rows: list[dict]) -> None:
    if path.suffix not in {".csv", ".parquet"}:
        raise ValueError("ledger path must end in .csv or .parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        with duckdb.connect(config={"threads": 1}) as db:
            db.register("ledger", pd.DataFrame(rows))
            literal = path.resolve().as_posix().replace("'", "''")
            db.execute(f"COPY ledger TO '{literal}' (FORMAT PARQUET)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay synchronized CEX and DEX execution observations")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="normalized tape JSON")
    source.add_argument("--capture-book", metavar="SYMBOL", help="fetch a single Binance Spot Testnet snapshot")
    parser.add_argument("--market", help="local market name for --capture-book")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ledger", type=Path, help="export decision and fill rows as CSV or Parquet")
    parser.add_argument("--write-tape", type=Path, help="export the exact replay input")
    parser.add_argument("--config", type=Path, help="execution assumptions as JSON")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    try:
        require_distinct_paths(
            input_file=args.input,
            configuration=args.config,
            report=args.output,
            ledger=args.ledger,
            tape=args.write_tape,
        )
        if args.capture_book:
            if args.ledger or args.config or args.write_tape:
                parser.error("replay options require a tape")
            snapshot = normalize_order_book(BinanceTestnetClient().depth(args.capture_book))
            result = BookSnapshot(
                market=args.market or args.capture_book.upper(), time_ms=time.time_ns() // 1_000_000,
                bids=[(row.price, row.quantity) for row in snapshot.bids],
                asks=[(row.price, row.quantity) for row in snapshot.asks], update_id=snapshot.last_update_id,
            ).model_dump()
        else:
            if args.input:
                raw = args.input.read_bytes()
                tape = Tape.model_validate_json(raw)
                source_info = {"kind": "normalized_tape", "sha256": hashlib.sha256(raw).hexdigest()}
            else:
                tape = demo_tape(args.seed)
                source_info = {"kind": "synthetic", "seed": args.seed}
            config = ReplayConfig.model_validate_json(args.config.read_bytes()) if args.config else ReplayConfig()
            rows = replay_tape(tape, config)
            result = {**summarize_tape(tape, rows, config), "source": source_info}
            if args.ledger:
                _write_ledger(args.ledger, rows)
            _write(args.write_tape, tape.model_dump_json(indent=2) + "\n")

        payload = json.dumps(result, indent=2, allow_nan=False) + "\n"
        _write(args.output, payload)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(payload, end="")


if __name__ == "__main__":
    main()
