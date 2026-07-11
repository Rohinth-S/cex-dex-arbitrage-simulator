"""Measure execution sensitivity with the market path held fixed."""
from .replay import replay_tape, summarize_tape
from .tape import ReplayConfig, Tape


def compare_dex_latency(tape: Tape, config: ReplayConfig, latencies: list[int]) -> list[dict]:
    if not 1 <= len(latencies) <= 8 or len(set(latencies)) != len(latencies):
        raise ValueError("provide 1 to 8 distinct DEX latencies")
    if min(latencies) < 0 or max(latencies) > 60_000:
        raise ValueError("DEX latencies must lie between 0 and 60000 ms")
    if (len(tape.books) + len(tape.dex_quotes)) * len(latencies) > 400_000:
        raise ValueError("latency study exceeds the replay workload budget")
    output = []
    for latency in sorted(latencies):
        variant = config.model_copy(update={"dex_latency_ms": latency})
        summary = summarize_tape(tape, replay_tape(tape, variant), variant)["portfolio"]
        output.append({"dex_latency_ms": latency, **summary})
    return output
