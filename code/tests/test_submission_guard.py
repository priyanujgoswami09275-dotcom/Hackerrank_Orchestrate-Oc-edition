from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import zipfile
import json
import csv

CODE = Path(__file__).resolve().parents[1]


def _dataset(root: Path) -> None:
    dataset = root / "dataset"
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / "deletion_requests.csv").write_text(
        "case_id,audit_at\nfixture_case,2026-10-01T00:00:00Z\n",
        encoding="utf-8",
    )
    (dataset / "evidence_files.csv").write_text(
        "file_id,file_path,captured_at\n"
        "fixture_evidence,evidence/fixture.json,2026-10-01T00:00:00Z\n",
        encoding="utf-8",
    )
    (dataset / "system_activity.csv").write_text(
        "activity_id,event_time\n", encoding="utf-8"
    )
    (dataset / "user_audit_log.csv").write_text(
        "audit_id,event_time\n", encoding="utf-8"
    )


def _run_guard(root: Path) -> subprocess.CompletedProcess[str]:
    script = CODE / "tools" / "submission_guard.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_deliberately_bad_csv_fails_the_output_guard(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "output.csv").write_text(
        "case_id,deletion_status,steps_json\nfixture_case,NOT_APPLICABLE,not-json\n",
        encoding="utf-8",
    )

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "FAIL valid JSON arrays" in result.stdout
    assert "FAIL pipeline validator" in result.stdout


def test_malformed_step_types_report_failures_without_crashing(tmp_path: Path) -> None:
    _dataset(tmp_path)
    steps = [{"operation": [], "phase": [], "state": "PRESENT", "step_no": []}]
    with (tmp_path / "output.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("case_id", "deletion_status", "steps_json"))
        writer.writerow(("fixture_case", "INCOMPLETE", json.dumps(steps)))

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "FAIL allowed operation/state pairs" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_hardcoding_scan_ignores_comments_and_docstrings_but_checks_logic(
    tmp_path: Path,
) -> None:
    _dataset(tmp_path)
    source = tmp_path / "code" / "pramaantrace" / "decision.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        '"""fixture_case is documentation, not decision logic."""\n'
        '# fixture_evidence is a comment, not decision logic.\n'
        'VALUE = "safe-literal"\n',
        encoding="utf-8",
    )

    result = _run_guard(tmp_path)

    assert "PASS dataset-derived hardcoding scan" in result.stdout
    source.write_text('VALUE = "fixture_case"\n', encoding="utf-8")

    result = _run_guard(tmp_path)

    assert "FAIL dataset-derived hardcoding scan" in result.stdout


def test_secret_scan_does_not_print_matched_secret(tmp_path: Path) -> None:
    _dataset(tmp_path)
    fake_secret = "sk-or-v1-" + "a" * 32
    source = tmp_path / "code" / "run.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"TOKEN = {fake_secret!r}\n", encoding="utf-8")

    result = _run_guard(tmp_path)

    assert "FAIL secret scan" in result.stdout
    assert fake_secret not in result.stdout + result.stderr


def test_log_guard_rejects_unknown_model_metadata(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "log.txt").write_text(
        "## [2026-10-25T10:00:00+00:00] SESSION START\n\n"
        "tool=OpenCode\nmodel=unknown\n"
        "Repo Root: test\nBranch: test\nWorktree: test\n"
        "Parent Agent: none\nLanguage: py\nTime Remaining: not configured\n",
        encoding="utf-8",
    )

    result = _run_guard(tmp_path)

    assert "FAIL log format" in result.stdout


def test_archive_guard_rejects_dataset_content(tmp_path: Path) -> None:
    _dataset(tmp_path)
    archive = tmp_path / "code.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("README.md", "readme")
        package.writestr("run.py", "source")
        package.writestr("evaluation/evaluation_report.md", "report")
        package.writestr("evaluation/usage_report.md", "usage")
        package.writestr("dataset/hidden.csv", "not allowed")

    result = _run_guard(tmp_path)

    assert "FAIL code.zip exclusions" in result.stdout
