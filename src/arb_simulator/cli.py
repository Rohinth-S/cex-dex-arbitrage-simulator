"""Replay a normalized tape or capture a read-only Binance snapshot."""

import argparse
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .artifacts import write_text_atomic

from . import __version__
from .artifacts import require_distinct_paths
import time

import duckdb
import pandas as pd

from .binance import BinanceTestnetClient, normalize_order_book
from .fixtures import demo_tape
from .sensitivity import compare_dex_latency
from .replay import replay_tape, summarize_tape
from .tape import BookSnapshot, ReplayConfig, Tape


def _write(path: Path | None, payload: str) -> None:
    if path:
        write_text_atomic(path, payload)


def _write_ledger(path: Path, rows: list[dict]) -> None:
    if path.suffix.lower() not in {".csv", ".parquet"}:
        raise ValueError("ledger path must end in .csv or .parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        write_text_atomic(path, stream.getvalue())
    else:
        with TemporaryDirectory(prefix=".parquet-", dir=path.parent) as temporary:
            staged = Path(temporary) / "ledger.parquet"
            with duckdb.connect(config={"threads": 1}) as db:
                db.register("ledger", pd.DataFrame(rows))
                literal = staged.resolve().as_posix().replace("'", "''")
                db.execute(f"COPY ledger TO '{literal}' (FORMAT PARQUET)")
            staged.replace(path)


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
    parser.add_argument("--latency-study", type=int, nargs="+", metavar="MS")
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
            if args.ledger or args.config or args.write_tape or args.latency_study:
                parser.error("replay options require a tape")
            request_started = time.monotonic_ns()
            snapshot = normalize_order_book(BinanceTestnetClient().depth(args.capture_book))
            duration_ms = (time.monotonic_ns() - request_started) // 1_000_000
            result = BookSnapshot(
                market=args.market or args.capture_book.upper(), time_ms=time.time_ns() // 1_000_000,
                capture_elapsed_ms=duration_ms,
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
            config_raw = args.config.read_bytes() if args.config else None
            config = ReplayConfig.model_validate_json(config_raw) if config_raw is not None else ReplayConfig()
            if config_raw is not None:
                source_info["configuration_sha256"] = hashlib.sha256(config_raw).hexdigest()
            rows = replay_tape(tape, config)
            result = {**summarize_tape(tape, rows, config), "source": source_info}
            if args.latency_study:
                result["latency_study"] = compare_dex_latency(tape, config, args.latency_study)
            if args.ledger:
                _write_ledger(args.ledger, rows)
            _write(args.write_tape, tape.model_dump_json(indent=2) + "\n")

        if not args.capture_book:
            result["producer"] = {"name": "cex-dex-arbitrage-simulator", "version": __version__, "format_version": 1}
        payload = json.dumps(result, indent=2, allow_nan=False) + "\n"
        _write(args.output, payload)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(payload, end="")


if __name__ == "__main__":
    main()
