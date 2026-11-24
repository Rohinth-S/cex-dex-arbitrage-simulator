"""A normalized, replayable market-data tape."""

from collections import defaultdict
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Time = Annotated[int, Field(ge=0)]
Market = Annotated[str, Field(min_length=1, max_length=80)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    market: Market
    time_ms: Time


class BookSnapshot(Record):
    bids: list[tuple[Positive, Positive]] = Field(min_length=1)
    asks: list[tuple[Positive, Positive]] = Field(min_length=1)
    update_id: int | None = None


class DexQuote(Record):
    bid: Positive
    ask: Positive
    max_qty: Positive
    gas_usd: Nonnegative
    impact_bps_per_unit: Nonnegative = 0

    @model_validator(mode="after")
    def check_spread(self) -> "DexQuote":
        if self.bid > self.ask:
            raise ValueError("DEX bid cannot exceed ask")
        if self.impact_bps_per_unit * self.max_qty >= 10_000:
            raise ValueError("modeled impact is too large for the quoted depth")
        return self

    def price(self, buy: bool, size: float) -> float:
        if size > self.max_qty:
            raise ValueError("insufficient DEX depth")
        impact = size * self.impact_bps_per_unit / 10_000
        return self.ask * (1 + impact) if buy else self.bid * (1 - impact)


class TapeTrade(Record):
    price: Positive
    quantity: Positive


class Tape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    books: list[BookSnapshot] = Field(min_length=1)
    dex_quotes: list[DexQuote] = Field(min_length=1)
    cex_trades: list[TapeTrade] = Field(default_factory=list)
    observed_through_ms: Time | None = None

    @model_validator(mode="after")
    def require_aligned_markets(self) -> "Tape":
        markets = {item.market for item in self.books}
        if markets != {item.market for item in self.dex_quotes}:
            raise ValueError("each market needs CEX books and DEX quotes")
        if any(item.market not in markets for item in self.cex_trades):
            raise ValueError("CEX trade market is missing from the two quote streams")
        if self.observed_through_ms is not None and any(
            row.time_ms > self.observed_through_ms
            for stream in (self.books, self.dex_quotes, self.cex_trades) for row in stream
        ):
            raise ValueError("the observation end must cover all supplied records")
        for items in (self.books, self.dex_quotes):
            counts = defaultdict(set)
            for item in items:
                if item.time_ms in counts[item.market]:
                    raise ValueError("quote timestamps must be unique within each market and venue")
                counts[item.market].add(item.time_ms)
        return self


class ReplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    size: Positive = 1
    capital_usd: Positive = 10_000
    cex_latency_ms: Time = 50
    dex_latency_ms: Time = 160
    max_quote_age_ms: Annotated[int, Field(gt=0)] = 1_000
    cex_fee_bps: Nonnegative = 4
    dex_fee_bps: Nonnegative = 5
    hedge_bps: Nonnegative = 2
    min_expected_pnl_usd: Nonnegative = 0
    revert_cost_fraction: Annotated[float, Field(ge=0, le=1)] = 0.7
