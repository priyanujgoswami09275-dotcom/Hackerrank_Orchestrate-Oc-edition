from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import zipfile
import json
import csv

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

import tools.submission_guard as submission_guard  # noqa: E402
from tools.submission_guard import (  # noqa: E402
    GuardCheck,
    _exit_code,
    _format_result,
    check_archive,
    check_log,
    check_output_csv,
)


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


def _run_guard(root: Path, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = CODE / "tools" / "submission_guard.py"
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        capture_output=True,
        check=False,
        text=True,
        env=env,
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


def test_incomplete_output_must_include_findings_remediation_and_verification(
    tmp_path: Path,
) -> None:
    _dataset(tmp_path)
    (tmp_path / "output.csv").write_text(
        "case_id,deletion_status,steps_json\nfixture_case,INCOMPLETE,[]\n",
        encoding="utf-8",
    )

    result = check_output_csv(tmp_path, expected_rows=1)

    incomplete_check = next(
        check for check in result if check.name == "INCOMPLETE plans include all phases"
    )
    assert not incomplete_check.passed
    assert "fixture_case" in incomplete_check.detail


def test_system_and_resource_ids_must_be_nonempty_strings(tmp_path: Path) -> None:
    _dataset(tmp_path)
    steps = [
        {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": 7,
            "resource_id": 9,
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "fixture_evidence",
        }
    ]
    with (tmp_path / "output.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("case_id", "deletion_status", "steps_json"))
        writer.writerow(("fixture_case", "INCOMPLETE", json.dumps(steps)))

    result = check_output_csv(tmp_path, expected_rows=1)

    ids_check = next(
        check for check in result if check.name == "string system_id/resource_id"
    )
    assert not ids_check.passed


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

    result = check_archive(tmp_path)

    exclusions_check = next(
        check for check in result if check.name == "code.zip exclusions"
    )
    assert not exclusions_check.passed
    assert "dataset/hidden.csv" in exclusions_check.detail


def test_archive_guard_normalizes_backslash_separated_paths(tmp_path: Path) -> None:
    _dataset(tmp_path)
    archive = tmp_path / "code.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("README.md", "readme")
        package.writestr("run.py", "source")
        package.writestr("evaluation/evaluation_report.md", "report")
        package.writestr("evaluation/usage_report.md", "usage")
        package.writestr("dataset\\hidden.csv", "not allowed")

    result = check_archive(tmp_path)

    exclusions_check = next(
        check for check in result if check.name == "code.zip exclusions"
    )
    assert not exclusions_check.passed
    assert "dataset\\hidden.csv" in exclusions_check.detail


_ADMITTING_ENV_VAR = "PRAMAANTRACE_ADMIT_UNRESOLVED_INCOMPLETE"

def _empty_incomplete_fixture(root: Path) -> None:
    _dataset(root)
    (root / "output.csv").write_text(
        "case_id,deletion_status,steps_json\nfixture_case,INCOMPLETE,[]\n",
        encoding="utf-8",
    )


def test_incomplete_plan_admission_defaults_to_strict_fail(tmp_path: Path) -> None:
    _empty_incomplete_fixture(tmp_path)

    result = submission_guard.check_output_csv(tmp_path, expected_rows=1)

    incomplete_check = next(
        check for check in result if check.name == "INCOMPLETE plans include all phases"
    )
    assert not incomplete_check.passed
    assert not incomplete_check.warning


def test_incomplete_plan_admission_optin_prints_warn_and_never_pass(
    tmp_path: Path,
) -> None:
    _empty_incomplete_fixture(tmp_path)

    result = _run_guard(
        tmp_path, env_extra={_ADMITTING_ENV_VAR: "1"}
    )

    assert "FAIL INCOMPLETE plans include all phases" not in result.stdout
    assert "PASS INCOMPLETE plans include all phases" not in result.stdout
    line = next(line for line in result.stdout.splitlines()
                if line.startswith("WARN INCOMPLETE plans include all phases"))
    assert "UNRESOLVED" in line
    assert "fixture_case" in line


def test_incomplete_plan_admission_defaults_to_fail_on_cli(tmp_path: Path) -> None:
    _empty_incomplete_fixture(tmp_path)
    os.environ.pop(_ADMITTING_ENV_VAR, None)

    result = _run_guard(tmp_path)

    assert "FAIL INCOMPLETE plans include all phases" in result.stdout


def test_warning_checks_do_not_fail_exit_code_alone() -> None:
    warning_only = [
        GuardCheck("example check", False, "admitted", True),
    ]

    assert _exit_code(warning_only) == 0
    assert _format_result(warning_only[0]) == "WARN example check: admitted"
    assert "PASS" not in _format_result(warning_only[0])
    assert _exit_code([GuardCheck("example check", False, "bad", False)]) == 1


def _valid_log_entry(title: str, index: int) -> str:
    return (
        f"## [2026-10-25T10:0{index}:00+00:00] {title}\n\n"
        "User Prompt (verbatim, secrets redacted):\nexample prompt\n\n"
        "Agent Response Summary:\ndid the work.\n\n"
        "Actions:\n* something changed\n\n"
        "Context:\ntool=OpenCode\nmodel=glm-5.3-flash-free\n"
        "branch=main\nrepo_root=/tmp/repo\nworktree=/tmp/repo\nparent_agent=none\n"
    )


def _legacy_entries() -> str:
    session_start = (
        "## [2026-10-01T09:00:00+00:00] SESSION START\n\n"
        "tool=OpenCode\nmodel=unknown\n"
        "Repo Root: /tmp/repo\nBranch: main\nWorktree: /tmp/repo\n"
        "Parent Agent: none\nLanguage: py\nTime Remaining: not configured\n"
    )
    correction = (
        "## [2026-10-01T09:05:00+00:00] Session-start timestamp correction\n\n"
        "Correction appended to fix entry 1.\n"
    )
    return session_start + correction + _valid_log_entry("Normal entry", 0)


def test_log_exempted_legacy_entries_pass_with_exemption_notice(
    tmp_path: Path,
) -> None:
    _dataset(tmp_path)
    (tmp_path / "log.txt").write_text(_legacy_entries(), encoding="utf-8")
    exemptions = tmp_path / "code" / "tools" / "log_exemptions.txt"
    exemptions.parent.mkdir(parents=True, exist_ok=True)
    exemptions.write_text(
        "# Documented legacy exemptions; append-only log cannot be edited.\n"
        "1 model=unknown written by an earlier session\n"
        "2 correction annotation without context block\n",
        encoding="utf-8",
    )

    result = check_log(tmp_path)

    assert result.passed
    assert "2 documented legacy exemption(s)" in result.detail


def test_log_entries_outside_exemptions_still_fail(tmp_path: Path) -> None:
    _dataset(tmp_path)
    text = _legacy_entries() + _valid_log_entry("New bad entry", 1).replace(
        "model=glm-5.3-flash-free", "model=unknown"
    )
    (tmp_path / "log.txt").write_text(text, encoding="utf-8")
    exemptions = tmp_path / "code" / "tools" / "log_exemptions.txt"
    exemptions.parent.mkdir(parents=True, exist_ok=True)
    exemptions.write_text(
        "1 legacy model=unknown\n2 correction annotation\n", encoding="utf-8"
    )

    result = check_log(tmp_path)

    assert not result.passed
    assert result.warning is False


def test_log_malformed_entry_not_in_exemptions_still_fails(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "log.txt").write_text(_legacy_entries(), encoding="utf-8")
    exemptions = tmp_path / "code" / "tools" / "log_exemptions.txt"
    exemptions.parent.mkdir(parents=True, exist_ok=True)
    exemptions.write_text("1 model=unknown written by an earlier session\n", encoding="utf-8")

    result = check_log(tmp_path)

    assert not result.passed


def test_log_is_strict_without_an_exemptions_file(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "log.txt").write_text(_legacy_entries(), encoding="utf-8")

    result = check_log(tmp_path)

    assert not result.passed
