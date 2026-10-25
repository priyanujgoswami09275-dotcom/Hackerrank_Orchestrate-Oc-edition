"""Environment-only configuration for the optional investigator client."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


class AgentConfigurationError(ValueError):
    """Raised when a configured agent cannot be started safely."""


def _optional_rate(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        rate = float(raw)
    except ValueError as exc:
        raise AgentConfigurationError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(rate) or rate < 0:
        raise AgentConfigurationError(f"{name} must be a non-negative number")
    return rate


@dataclass(frozen=True)
class AgentConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    step_cap: int = 8
    cache_path: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "pramaantrace" / "llm-cache.sqlite3"
    )
    input_cost_per_1m: float | None = None
    output_cost_per_1m: float | None = None
    timeout_seconds: float = 45.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentConfig | None":
        values = os.environ if env is None else env
        api_key = values.get("LLM_API_KEY", "").strip()
        if not api_key:
            return None

        base_url = values.get("LLM_BASE_URL", "").strip().rstrip("/")
        model = values.get("LLM_MODEL", "").strip()
        if not base_url or not model:
            raise AgentConfigurationError(
                "LLM_API_KEY requires both LLM_BASE_URL and LLM_MODEL"
            )
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise AgentConfigurationError("LLM_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise AgentConfigurationError("LLM_BASE_URL must not contain credentials")
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise AgentConfigurationError("LLM_BASE_URL must use HTTPS outside loopback")

        raw_cap = values.get("AGENT_STEP_CAP", "8").strip()
        try:
            step_cap = int(raw_cap)
        except ValueError as exc:
            raise AgentConfigurationError("AGENT_STEP_CAP must be an integer from 1 to 64") from exc
        if not 1 <= step_cap <= 64:
            raise AgentConfigurationError("AGENT_STEP_CAP must be an integer from 1 to 64")

        cache_path = Path(
            values.get(
                "PRAMAANTRACE_LLM_CACHE",
                str(Path.home() / ".cache" / "pramaantrace" / "llm-cache.sqlite3"),
            )
        ).expanduser()
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            step_cap=step_cap,
            cache_path=cache_path,
            input_cost_per_1m=_optional_rate(values, "LLM_INPUT_COST_PER_1M"),
            output_cost_per_1m=_optional_rate(values, "LLM_OUTPUT_COST_PER_1M"),
        )
