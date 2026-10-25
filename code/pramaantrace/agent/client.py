"""Cached OpenAI-compatible chat-completions client using urllib only."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .cache import ResponseCache, cache_key
from .config import AgentConfig
from .usage import UsageLedger


class LLMClientError(RuntimeError):
    """A network or response error without request/credential contents."""


@dataclass(frozen=True)
class ChatCompletion:
    message: dict[str, Any]
    finish_reason: str
    actual_model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    provider: str
    retries: int = 0


class OpenAICompatibleClient:
    def __init__(
        self,
        config: AgentConfig,
        *,
        cache: ResponseCache | None = None,
        usage_ledger: UsageLedger | None = None,
        prompt_version: str = "investigator-v1",
    ) -> None:
        self.config = config
        self.cache = cache or ResponseCache(config.cache_path)
        self.usage_ledger = usage_ledger or UsageLedger()
        self.prompt_version = prompt_version
        self.endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        self.provider = urlparse(config.base_url).hostname or "unknown-provider"

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatCompletion:
        key = cache_key(
            self.endpoint,
            self.config.model,
            self.prompt_version,
            tools,
            messages,
            response_format=response_format,
        )
        cached = self.cache.get(key)
        if cached is not None:
            completion = self._parse_completion(cached, retries=0)
            self.usage_ledger.record(completion, cache_hit=True)
            return completion

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "temperature": 0,
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read()
                decoded = json.loads(raw.decode("utf-8"))
                completion = self._parse_completion(decoded, retries=attempts - 1)
            except HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code <= 599
                if transient and attempts < 3:
                    time.sleep(min(2 ** (attempts - 1), 4))
                    continue
                self.usage_ledger.record_failure(
                    self.provider,
                    self.config.model,
                    attempts=attempts,
                    retries=attempts - 1,
                )
                raise LLMClientError(f"chat completion failed with HTTP {exc.code}") from None
            except (URLError, TimeoutError, OSError) as exc:
                if attempts < 3:
                    time.sleep(min(2 ** (attempts - 1), 4))
                    continue
                self.usage_ledger.record_failure(
                    self.provider,
                    self.config.model,
                    attempts=attempts,
                    retries=attempts - 1,
                )
                raise LLMClientError("chat completion network request failed") from None
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                self.usage_ledger.record_failure(
                    self.provider,
                    self.config.model,
                    attempts=attempts,
                    retries=attempts - 1,
                )
                raise LLMClientError("chat completion returned an invalid response") from None

            self.cache.put(key, decoded)
            self.usage_ledger.record(completion, cache_hit=False)
            return completion

        raise LLMClientError("chat completion retry loop exhausted")

    def _parse_completion(self, response: Any, *, retries: int) -> ChatCompletion:
        if not isinstance(response, dict):
            raise ValueError("response must be an object")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("response has no completion choice")
        message = choices[0].get("message")
        usage = response.get("usage", {})
        if not isinstance(message, dict) or not isinstance(usage, dict):
            raise ValueError("response message or usage is invalid")

        prompt_tokens = self._nonnegative_int(usage.get("prompt_tokens", 0))
        completion_tokens = self._nonnegative_int(usage.get("completion_tokens", 0))
        total_tokens = self._nonnegative_int(
            usage.get("total_tokens", prompt_tokens + completion_tokens)
        )
        cost = usage.get("cost")
        if cost is None:
            if (
                self.config.input_cost_per_1m is not None
                and self.config.output_cost_per_1m is not None
            ):
                cost = (
                    prompt_tokens * self.config.input_cost_per_1m
                    + completion_tokens * self.config.output_cost_per_1m
                ) / 1_000_000
        if cost is not None:
            cost = float(cost)
            if not math.isfinite(cost) or cost < 0:
                raise ValueError("response cost is invalid")

        return ChatCompletion(
            message=message,
            finish_reason=str(choices[0].get("finish_reason", "")),
            actual_model=str(response.get("model") or self.config.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            provider=self.provider,
            retries=retries,
        )

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        number = int(value)
        if number < 0:
            raise ValueError("token counts must be non-negative")
        return number
