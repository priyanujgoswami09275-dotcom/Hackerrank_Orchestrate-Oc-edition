from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import stat
import sys
from threading import Thread
from typing import Any, Iterator

import pytest

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))


def _agent_module(name: str) -> Any:
    try:
        return importlib.import_module(f"pramaantrace.agent.{name}")
    except ImportError as exc:
        pytest.fail(f"missing investigator agent module {name}: {exc}")


class _Handler(BaseHTTPRequestHandler):
    responses: list[tuple[int, dict[str, Any]]] = []
    calls: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        type(self).calls.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        status, payload = (
            type(self).responses.pop(0)
            if type(self).responses
            else (200, _completion_payload())
        )
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _completion_payload(*, include_cost: bool = True) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
    }
    if include_cost:
        usage["cost"] = 0.0002
    return {
        "id": "completion-fixture",
        "model": "fixture/model-returned",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "{\"candidates\": []}"},
            }
        ],
        "usage": usage,
    }


@contextmanager
def _local_server() -> Iterator[ThreadingHTTPServer]:
    _Handler.responses = []
    _Handler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _config(env: dict[str, str]) -> Any:
    config_module = _agent_module("config")
    return config_module.AgentConfig.from_env(env)


def _client_config(server: ThreadingHTTPServer, tmp_path: Path, **extra: str) -> Any:
    env = {
        "LLM_API_KEY": "fixture-token-not-a-credential",
        "LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "LLM_MODEL": "fixture/model-requested",
        "PRAMAANTRACE_LLM_CACHE": str(tmp_path / "llm-cache.sqlite3"),
    }
    env.update(extra)
    return _config(env)


def test_missing_api_key_disables_agent_configuration() -> None:
    assert _config({}) is None


def test_api_key_requires_endpoint_and_model_and_parses_turn_cap() -> None:
    config_module = _agent_module("config")
    with pytest.raises(config_module.AgentConfigurationError):
        _config({"LLM_API_KEY": "fixture-token"})

    config = _config(
        {
            "LLM_API_KEY": "fixture-token",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL": "fixture/model",
        }
    )
    assert config.step_cap == 8

    configured = _config(
        {
            "LLM_API_KEY": "fixture-token",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL": "fixture/model",
            "AGENT_STEP_CAP": "12",
        }
    )
    assert configured.step_cap == 12


def test_cache_key_is_canonical_and_covers_model_prompt_tools_and_messages() -> None:
    cache_module = _agent_module("cache")
    key = cache_module.cache_key(
        "https://provider.example/v1",
        "fixture/model",
        "prompt-v1",
        [{"type": "function", "function": {"name": "search_records"}}],
        [{"role": "user", "content": "find records"}],
    )
    same_key = cache_module.cache_key(
        "https://provider.example/v1",
        "fixture/model",
        "prompt-v1",
        [{"function": {"name": "search_records"}, "type": "function"}],
        [{"content": "find records", "role": "user"}],
    )
    changed_key = cache_module.cache_key(
        "https://provider.example/v1",
        "fixture/other-model",
        "prompt-v1",
        [{"type": "function", "function": {"name": "search_records"}}],
        [{"role": "user", "content": "find records"}],
    )

    assert key == same_key
    assert key != changed_key


def test_sqlite_response_cache_round_trips_json(tmp_path: Path) -> None:
    cache_module = _agent_module("cache")
    cache = cache_module.ResponseCache(tmp_path / "cache.sqlite3")
    response = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 2}}

    assert cache.get("hash-1") is None
    cache.put("hash-1", response)
    assert cache.get("hash-1") == response


def test_cache_creation_does_not_change_existing_parent_permissions(
    tmp_path: Path,
) -> None:
    if os.name != "posix":
        pytest.skip("POSIX mode-bit assertion")
    cache_module = _agent_module("cache")
    parent = tmp_path / "existing-cache-dir"
    parent.mkdir()
    parent.chmod(0o755)

    cache_module.ResponseCache(parent / "cache.sqlite3")

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755


def test_cached_completion_avoids_second_request_and_does_not_double_count_usage(
    tmp_path: Path,
) -> None:
    agent = _agent_module("client")
    usage_module = _agent_module("usage")
    with _local_server() as server:
        config = _client_config(server, tmp_path)
        ledger = usage_module.UsageLedger()
        client = agent.OpenAICompatibleClient(config, usage_ledger=ledger)
        messages = [{"role": "user", "content": "hello"}]

        first = client.complete(messages, tools=[])
        second = client.complete(messages, tools=[])

        assert first.message == second.message
        assert len(_Handler.calls) == 1
        assert _Handler.calls[0]["path"] == "/v1/chat/completions"
        assert _Handler.calls[0]["authorization"] == "Bearer fixture-token-not-a-credential"
        assert _Handler.calls[0]["body"]["model"] == "fixture/model-requested"
        assert _Handler.calls[0]["body"]["temperature"] == 0
        summary = ledger.summary()
        assert summary["network_calls"] == 1
        assert summary["cache_hits"] == 1
        assert summary["input_tokens"] == 10
        assert summary["output_tokens"] == 3
        assert summary["total_tokens"] == 13
        assert summary["cost_usd"] == pytest.approx(0.0002)


def test_transient_server_error_retries_and_records_retry_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _agent_module("client")
    usage_module = _agent_module("usage")
    monkeypatch.setattr("pramaantrace.agent.client.time.sleep", lambda _seconds: None)
    with _local_server() as server:
        _Handler.responses = [(503, {"error": "retry"}), (200, _completion_payload())]
        ledger = usage_module.UsageLedger()
        client = agent.OpenAICompatibleClient(
            _client_config(server, tmp_path), usage_ledger=ledger
        )

        completion = client.complete([{"role": "user", "content": "hello"}], tools=[])

        assert completion.finish_reason == "stop"
        assert completion.retries == 1
        assert len(_Handler.calls) == 2
        assert ledger.summary()["retries"] == 1


def test_client_fails_after_two_transient_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _agent_module("client")
    monkeypatch.setattr("pramaantrace.agent.client.time.sleep", lambda _seconds: None)
    with _local_server() as server:
        _Handler.responses = [
            (503, {"error": "retry-1"}),
            (503, {"error": "retry-2"}),
            (503, {"error": "retry-3"}),
        ]
        client = agent.OpenAICompatibleClient(_client_config(server, tmp_path))

        with pytest.raises(agent.LLMClientError):
            client.complete([{"role": "user", "content": "hello"}], tools=[])

        assert len(_Handler.calls) == 3


def test_cost_falls_back_to_configured_per_million_rates(tmp_path: Path) -> None:
    agent = _agent_module("client")
    with _local_server() as server:
        _Handler.responses = [(200, _completion_payload(include_cost=False))]
        client = agent.OpenAICompatibleClient(
            _client_config(
                server,
                tmp_path,
                LLM_INPUT_COST_PER_1M="2",
                LLM_OUTPUT_COST_PER_1M="4",
            )
        )

        completion = client.complete([{"role": "user", "content": "hello"}], tools=[])

        assert completion.cost_usd == pytest.approx(0.000032)
