"""As-of quote joining and two-leg fill-or-kill execution simulation."""

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Protocol, TypeVar

import numpy as np

from .binance import NormalizedOrderBook, normalize_order_book
from .tape import DexQuote, ReplayConfig, Tape

DEX_BUY = "dex_buy_cex_sell"
CEX_BUY = "cex_buy_dex_sell"


@dataclass(frozen=True)
class Book:
    time_ms: int
    levels: NormalizedOrderBook


@dataclass(frozen=True)
class FillCost:
    buy_price: float
    sell_price: float
    gross: float
    cex_fee: float
    dex_fee: float
    hedge: float
    gas: float
    debit: float

    @property
    def net(self) -> float:
        return self.gross - self.fees - self.hedge - self.gas

    @property
    def fees(self) -> float:
        return self.cex_fee + self.dex_fee


class TimedQuote(Protocol):
    @property
    def time_ms(self) -> int: ...


Quote = TypeVar("Quote", bound=TimedQuote)


def _asof(stream: list[Quote], at: int, max_age: int) -> Quote | None:
    index = bisect_right(stream, at, key=lambda quote: quote.time_ms) - 1
    return stream[index] if index >= 0 and at - stream[index].time_ms <= max_age else None


def _quote(book: Book, dex: DexQuote, direction: str, cfg: ReplayConfig) -> FillCost:
    buy_on_dex = direction == DEX_BUY
    cex_price = book.levels.vwap("sell" if buy_on_dex else "buy", cfg.size)
    dex_price = dex.price(buy_on_dex, cfg.size)
    buy, sell = (dex_price, cex_price) if buy_on_dex else (cex_price, dex_price)
    cex_fee = cex_price * cfg.size * cfg.cex_fee_bps / 10_000
    dex_fee = dex_price * cfg.size * cfg.dex_fee_bps / 10_000
    hedge = cex_price * cfg.size * cfg.hedge_bps / 10_000
    buy_fee = dex_fee if buy_on_dex else cex_fee
    return FillCost(
        buy, sell, (sell - buy) * cfg.size, cex_fee, dex_fee, hedge, dex.gas_usd,
        buy * cfg.size + buy_fee + dex.gas_usd + hedge,
    )


def _run_market(
    market: str, books: list[Book], dex_quotes: list[DexQuote], cfg: ReplayConfig, budget: float,
    observed_through_ms: int | None,
) -> list[dict]:
    books.sort(key=lambda book: book.time_ms)
    dex_quotes.sort(key=lambda quote: quote.time_ms)
    through = min(books[-1].time_ms, dex_quotes[-1].time_ms) if observed_through_ms is None else observed_through_ms
    signals = sorted({book.time_ms for book in books} | {quote.time_ms for quote in dex_quotes})
    next_free = -1
    cex_age = cfg.cex_max_age_ms or cfg.max_quote_age_ms
    dex_age = cfg.dex_max_age_ms or cfg.max_quote_age_ms
    rows = []
    for signal in signals:
        order = {
            "market": market, "decision_time_ms": signal, "event_time_ms": signal, "status": "busy",
            "direction": None, "size": cfg.size, "signal_book_ms": None, "signal_dex_ms": None,
            "execution_book_ms": None, "execution_dex_ms": None, "expected_pnl_usd": None,
            "scheduled_cex_ms": None, "scheduled_dex_ms": None,
            "execution_cex_quote_age_ms": None, "execution_dex_quote_age_ms": None,
            "gross_pnl_usd": 0.0, "fees_usd": 0.0, "hedge_usd": 0.0, "gas_usd": 0.0,
            "cex_fees_usd": 0.0, "dex_fees_usd": 0.0,
            "expected_gross_pnl_usd": None, "expected_cost_usd": None,
            "gas_mark_source": None,
            "net_pnl_usd": 0.0, "edge_decay_usd": None, "buy_price": None, "sell_price": None,
        }
        rows.append(order)
        if signal < next_free:
            continue
        book = _asof(books, signal, cex_age)
        dex = _asof(dex_quotes, signal, dex_age)
        if book is None or dex is None:
            order["status"] = "stale_signal"
            continue
        order.update({"signal_book_ms": book.time_ms, "signal_dex_ms": dex.time_ms})
        choices = []
        for direction in (DEX_BUY, CEX_BUY):
            try:
                fill = _quote(book, dex, direction, cfg)
            except ValueError:
                continue
            if fill.debit <= budget:
                choices.append((direction, fill))
        if not choices:
            order["status"] = "signal_depth_or_capital"
            continue
        direction, forecast = max(choices, key=lambda choice: (choice[1].net, choice[0]))
        expected = forecast.net
        order.update({
            "expected_pnl_usd": expected, "direction": direction,
            "expected_gross_pnl_usd": forecast.gross, "expected_cost_usd": forecast.gross - expected,
        })
        if expected <= cfg.min_expected_pnl_usd:
            order["status"] = "below_edge"
            continue

        cex_at, dex_at = (signal + cfg.cex_latency_ms, signal + cfg.dex_latency_ms)
        order.update({"scheduled_cex_ms": cex_at, "scheduled_dex_ms": dex_at})
        if max(cex_at, dex_at) > through:
            order["status"] = "censored"
            continue
        next_free = max(cex_at, dex_at)
        order["event_time_ms"] = next_free
        exec_book = _asof(books, cex_at, cex_age)
        exec_dex = _asof(dex_quotes, dex_at, dex_age)
        order["execution_book_ms"] = exec_book.time_ms if exec_book else None
        order["execution_dex_ms"] = exec_dex.time_ms if exec_dex else None
        order["execution_cex_quote_age_ms"] = cex_at - exec_book.time_ms if exec_book else None
        order["execution_dex_quote_age_ms"] = dex_at - exec_dex.time_ms if exec_dex else None

        settled = None
        status = "failed_stale"
        if exec_book and exec_dex:
            try:
                fill = _quote(exec_book, exec_dex, direction, cfg)
            except ValueError:
                status = "failed_depth"
            else:
                if fill.debit <= budget:
                    settled = fill
                else:
                    status = "failed_capital"
        if settled is None:
            gas = (exec_dex or dex).gas_usd * cfg.revert_cost_fraction
            order.update({
                "status": status, "gas_usd": gas, "net_pnl_usd": -gas, "edge_decay_usd": expected + gas,
                "gas_mark_source": "execution_dex" if exec_dex else "signal_dex",
            })
            continue
        order.update({
            "status": "filled", "gross_pnl_usd": settled.gross, "fees_usd": settled.fees,
            "cex_fees_usd": settled.cex_fee, "dex_fees_usd": settled.dex_fee,
            "gas_mark_source": "execution_dex",
            "hedge_usd": settled.hedge, "gas_usd": settled.gas, "net_pnl_usd": settled.net,
            "edge_decay_usd": expected - settled.net, "buy_price": settled.buy_price, "sell_price": settled.sell_price,
        })
    return rows


def replay_tape(tape: Tape, config: ReplayConfig = ReplayConfig()) -> list[dict]:
    books = defaultdict(list)
    dex_quotes = defaultdict(list)
    for item in tape.books:
        payload = {"bids": item.bids, "asks": item.asks, "lastUpdateId": item.update_id}
        books[item.market].append(Book(item.time_ms, normalize_order_book(payload)))
    for item in tape.dex_quotes:
        dex_quotes[item.market].append(item)
    budget = config.capital_usd / len(books)
    ledger = [
        row for market in sorted(books)
        for row in _run_market(market, books[market], dex_quotes[market], config, budget, tape.observed_through_ms)
    ]
    return sorted(ledger, key=lambda row: (row["event_time_ms"], row["market"], row["decision_time_ms"]))


def _summary(ledger: list[dict], capital: float) -> dict:
    attempts = [row for row in ledger if row["status"] == "filled" or row["status"].startswith("failed_")]
    fills = sum(row["status"] == "filled" for row in attempts)
    realized = np.array([row["net_pnl_usd"] for row in attempts], dtype=float)
    curve = np.r_[0.0, realized.cumsum()]
    count = len(attempts)
    std = float(realized.std(ddof=1)) if count > 1 else 0
    return {
        "decisions": len(ledger), "attempts": count, "fills": fills, "fill_rate": fills / count if count else None,
        "states": dict(sorted(Counter(row["status"] for row in ledger).items())),
        "net_pnl_usd": float(realized.sum()), "return_pct": float(100 * realized.sum() / capital),
        "max_drawdown_usd": float((np.maximum.accumulate(curve) - curve).max()),
        "trade_sharpe_like": float(realized.mean() / std * np.sqrt(count)) if std else None,
        "mean_edge_decay_usd": float(np.mean([row["edge_decay_usd"] for row in attempts])) if count else None,
        **{column: sum(row[column] for row in attempts) for column in (
            "gross_pnl_usd", "fees_usd", "cex_fees_usd", "dex_fees_usd", "hedge_usd", "gas_usd",
        )},
    }


def summarize_tape(tape: Tape, ledger: list[dict], config: ReplayConfig) -> dict:
    groups = defaultdict(list)
    trades = defaultdict(list)
    for row in ledger:
        groups[row["market"]].append(row)
    for trade in tape.cex_trades:
        trades[trade.market].append(trade.price * trade.quantity)
    budget = config.capital_usd / len(groups)
    return {
        "config": config.model_dump(), "portfolio": _summary(ledger, config.capital_usd),
        "by_market": {
            market: {
                **_summary(rows, budget), "cex_trade_count": len(trades[market]),
                "cex_trade_notional_usd": sum(trades[market]),
            }
            for market, rows in sorted(groups.items())
        },
    }
