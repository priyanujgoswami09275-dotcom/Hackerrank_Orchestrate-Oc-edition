from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

import run as run_cli  # noqa: E402
from pramaantrace.agent.config import AgentConfig  # noqa: E402
from pramaantrace.agent.pipeline import AgentRunResult  # noqa: E402
from pramaantrace.loader import DatasetBundle  # noqa: E402
from pramaantrace.store import RecordStore  # noqa: E402


def _request() -> dict[str, str]:
    return {
        "case_id": "fixture_case",
        "email": "subject@example.test",
        "requested_at": "2026-09-15T11:00:00Z",
        "reported_status": "NOT_STARTED",
        "reported_at": "2026-09-15T11:00:00Z",
        "audit_at": "2026-09-15T12:00:00Z",
        "request_text": "Please export my data.",
    }


def _bundle(requests: list[dict[str, str]]) -> DatasetBundle:
    return DatasetBundle(
        root=ROOT,
        store=RecordStore(),
        tables={
            "deletion_requests.csv": requests,
            "deletion_rules.csv": [],
            "evidence_files.csv": [],
            "system_activity.csv": [],
            "user_identities.csv": [],
            "user_audit_log.csv": [],
        },
    )


def _baseline_rows(bundle: DatasetBundle) -> list[dict[str, Any]]:
    return [
        {"case_id": row["case_id"], "deletion_status": "NOT_APPLICABLE", "steps": []}
        for row in bundle.tables["deletion_requests.csv"]
    ]


@pytest.fixture
def stub_dataset(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    requests = [_request()]
    monkeypatch.setattr(run_cli, "read_csv_rows", lambda _path: requests)
    monkeypatch.setattr(run_cli, "load_dataset", lambda *_args, **_kwargs: _bundle(requests))
    monkeypatch.setattr(run_cli, "run_baseline", _baseline_rows)
    return requests


def test_no_api_key_runs_enriched_baseline_without_constructing_client(
    stub_dataset: list[dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(run_cli, "OpenAICompatibleClient", lambda *_a, **_k: pytest.fail("client constructed"))
    output = tmp_path / "no-key.csv"

    exit_code = run_cli.main(["--output", str(output)])

    assert exit_code == 0
    assert output.is_file()
    assert "Investigator: disabled (LLM_API_KEY not set)" in capsys.readouterr().out


def test_configured_credentials_auto_run_agent_and_print_safe_summary(
    stub_dataset: list[dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AgentConfig(
        api_key="fixture-secret-that-must-not-print",
        base_url="https://provider.example/v1",
        model="fixture/model",
    )
    monkeypatch.setattr(
        run_cli.AgentConfig,
        "from_env",
        classmethod(lambda _cls: config),
    )
    constructed: list[Any] = []

    class FakeClient:
        def __init__(self, received: AgentConfig) -> None:
            constructed.append(received)
            self.usage_ledger = object()

    class FakeInvestigator:
        def __init__(self, client: Any, step_cap: int) -> None:
            self.client = client
            self.step_cap = step_cap

    pipeline_calls: list[tuple[Any, Any]] = []

    def _pipeline(bundle: Any, investigator: Any) -> AgentRunResult:
        pipeline_calls.append((bundle, investigator))
        return AgentRunResult(
            rows=_baseline_rows(bundle),
            attempted_cases=1,
            completed_cases=1,
            fallback_cases=0,
            accepted_candidates=2,
            rejected_candidates=3,
            usage_summary={"network_calls": 7, "cache_hits": 1},
        )

    monkeypatch.setattr(run_cli, "OpenAICompatibleClient", FakeClient)
    monkeypatch.setattr(run_cli, "Investigator", FakeInvestigator)
    monkeypatch.setattr(run_cli, "run_agent_pipeline", _pipeline)
    output = tmp_path / "agent.csv"

    exit_code = run_cli.main(["--output", str(output)])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert output.is_file()
    assert len(constructed) == 1
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0][1].step_cap == 8
    assert "Investigator: enabled" in stdout
    assert "attempted=1, completed=1, fallbacks=0" in stdout
    assert "Investigator candidates: accepted=2, rejected=3" in stdout
    assert "network calls=7, cache hits=1" in stdout
    assert "fixture-secret-that-must-not-print" not in stdout
    assert "subject@example.test" not in stdout


def test_disable_agent_skips_client_even_when_credentials_configured(
    stub_dataset: list[dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fixture-secret")
    monkeypatch.setattr(
        run_cli.AgentConfig,
        "from_env",
        classmethod(lambda _cls: pytest.fail("configuration parsed while agent disabled")),
    )
    monkeypatch.setattr(run_cli, "OpenAICompatibleClient", lambda *_a, **_k: pytest.fail("client constructed"))
    output = tmp_path / "disabled.csv"

    exit_code = run_cli.main(["--disable-agent", "--output", str(output)])

    assert exit_code == 0
    assert output.is_file()
    assert "Investigator: disabled by --disable-agent" in capsys.readouterr().out


def test_invalid_agent_configuration_fails_before_output_is_written(
    stub_dataset: list[dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fixture-secret")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    output = tmp_path / "invalid.csv"

    with pytest.raises(SystemExit) as error:
        run_cli.main(["--output", str(output)])

    assert error.value.code == 2
    assert not output.exists()
