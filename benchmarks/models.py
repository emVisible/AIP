"""Pricing model and token estimation for the AIP cost benchmark (SPEC App. E).

Tokens are estimated as len(json)/4 — a rough but deterministic proxy.
Real-API mode should replace `est_tokens` with actual model token usage.
Pricing is illustrative (USD per 1M tokens); adjust to your providers.
"""
import json
import math


# USD per 1M tokens.
PRICING = {
    "llm": {"input": 5.00, "output": 15.00},
    "small": {"input": 0.25, "output": 1.25},
}

# Context-building constants (tokens). Representative of a real page/toolset;
# tune to your deployment. AIP event packets stay small by construction.
CONTEXT = {
    "A": {"system": 500, "page": 1500, "out": 60},      # long-context agent
    "B": {"system": 300, "tools": 3000, "page": 1200, "out": 60},  # MCP agent
    "C": {"event_overhead": 80, "out": 30},             # AIP + Context-on-Demand
}


def est_tokens(obj) -> int:
    if obj is None:
        return 0
    if isinstance(obj, str):
        return max(1, math.ceil(len(obj) / 4))
    return max(1, math.ceil(len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"))) / 4))


def usd(tokens_in: int, tokens_out: int, tier: str) -> float:
    if tier == "none":
        return 0.0
    price = PRICING[tier]
    return tokens_in / 1e6 * price["input"] + tokens_out / 1e6 * price["output"]