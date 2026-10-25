"""Per-run and per-model request, token, retry, and cost accounting."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _empty_totals() -> dict[str, Any]:
    return {
        "network_calls": 0,
        "successful_completions": 0,
        "failed_requests": 0,
        "cache_hits": 0,
        "retries": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_known_usd": 0.0,
        "cost_unreported_calls": 0,
    }


class UsageLedger:
    def __init__(self) -> None:
        self._by_model: dict[str, dict[str, Any]] = defaultdict(_empty_totals)
        self._overall = _empty_totals()

    @staticmethod
    def _key(provider: str, model: str) -> str:
        return f"{provider}/{model}"

    def _increment(self, key: str, name: str, value: int | float) -> None:
        self._overall[name] += value
        self._by_model[key][name] += value

    def record(self, completion: Any, *, cache_hit: bool) -> None:
        key = self._key(completion.provider, completion.actual_model)
        if cache_hit:
            self._increment(key, "cache_hits", 1)
            return

        retries = int(completion.retries)
        self._increment(key, "network_calls", retries + 1)
        self._increment(key, "successful_completions", 1)
        self._increment(key, "retries", retries)
        self._increment(key, "input_tokens", int(completion.prompt_tokens))
        self._increment(key, "output_tokens", int(completion.completion_tokens))
        self._increment(key, "total_tokens", int(completion.total_tokens))
        if completion.cost_usd is None:
            self._increment(key, "cost_unreported_calls", 1)
        else:
            self._increment(key, "cost_known_usd", float(completion.cost_usd))

    def record_failure(
        self, provider: str, model: str, *, attempts: int, retries: int
    ) -> None:
        key = self._key(provider, model)
        self._increment(key, "network_calls", attempts)
        self._increment(key, "failed_requests", 1)
        self._increment(key, "retries", retries)

    @staticmethod
    def _public_totals(totals: dict[str, Any]) -> dict[str, Any]:
        result = dict(totals)
        result["cost_usd"] = (
            None
            if totals["cost_unreported_calls"]
            else totals["cost_known_usd"]
        )
        return result

    def summary(self) -> dict[str, Any]:
        return {
            **self._public_totals(self._overall),
            "by_model": {
                model: self._public_totals(totals)
                for model, totals in sorted(self._by_model.items())
            },
        }
