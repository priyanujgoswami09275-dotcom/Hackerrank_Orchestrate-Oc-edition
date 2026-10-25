#!/usr/bin/env python3
"""Check the submission artifacts without replacing the pipeline validator."""

from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from typing import Any, Iterable, Mapping

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from package_submission import SECRET_VALUE_PATTERNS  # noqa: E402
from pramaantrace.constants import PHASE_ORDER  # noqa: E402
from pramaantrace.planner import step_sort_key  # noqa: E402
from pramaantrace.store import parse_timestamp  # noqa: E402
from pramaantrace.validator import STATE_BY_OPERATION, validate_rows  # noqa: E402

OUTPUT_FIELDS = ("case_id", "deletion_status", "steps_json")
EXPECTED_ROWS = 518
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
CACHE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "virtualenv",
    "virtualenvs",
    "env",
    "node_modules",
    "__pycache__",
    "dataset",
    "datasets",
}
LOG_ENTRY = re.compile(r"^## \[([^\]]+)\] (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class GuardCheck:
    name: str
    passed: bool
    detail: str = ""


def _check(name: str, passed: bool, detail: str = "") -> GuardCheck:
    return GuardCheck(name, passed, detail)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), tuple(reader.fieldnames or ())


def _load_table(root: Path, filename: str) -> list[dict[str, str]]:
    return _read_csv(root / "dataset" / filename)[0]


def _parsed_steps(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    parsed: list[dict[str, Any]] = []
    valid = True
    for row in rows:
        try:
            steps = json.loads(str(row.get("steps_json", "")))
        except (json.JSONDecodeError, TypeError):
            valid = False
            steps = None
        if not isinstance(steps, list):
            valid = False
        parsed.append(
            {
                "case_id": str(row.get("case_id", "")),
                "deletion_status": row.get("deletion_status", ""),
                "steps": steps,
            }
        )
    return parsed, valid


def _step_check(
    rows: Iterable[Mapping[str, Any]], predicate: Any
) -> tuple[bool, str]:
    checked = 0
    for row in rows:
        steps = row.get("steps")
        if not isinstance(steps, list):
            return False, f"{row.get('case_id', '<missing case_id>')}: steps are not an array"
        for step in steps:
            checked += 1
            if not isinstance(step, Mapping) or not predicate(row, step):
                return False, f"{row.get('case_id', '<missing case_id>')}: invalid step"
    return True, f"checked {checked} step(s)"


def _operation_pair_ok(_row: Mapping[str, Any], step: Mapping[str, Any]) -> bool:
    operation = step.get("operation")
    if not isinstance(operation, str) or operation not in STATE_BY_OPERATION:
        return False
    expected_phase, expected_state = STATE_BY_OPERATION[str(operation)]
    return step.get("phase") == expected_phase and step.get("state") == expected_state


def _step_numbers_ok(_row: Mapping[str, Any], step: Mapping[str, Any]) -> bool:
    return type(step.get("step_no")) is int


def _numbers_consecutive(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    for row in rows:
        steps = row.get("steps")
        if not isinstance(steps, list):
            return False, f"{row.get('case_id', '<missing case_id>')}: steps are not an array"
        numbers = [step.get("step_no") if isinstance(step, Mapping) else None for step in steps]
        if any(type(number) is not int for number in numbers) or numbers != list(
            range(1, len(steps) + 1)
        ):
            return False, f"{row.get('case_id', '<missing case_id>')}: numbering is not consecutive from 1"
    return True, "all step numbers are consecutive from 1"


def _ordering_ok(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    for row in rows:
        steps = row.get("steps")
        if not isinstance(steps, list):
            return False, f"{row.get('case_id', '<missing case_id>')}: steps are not an array"
        if any(not isinstance(step, Mapping) for step in steps):
            return False, f"{row.get('case_id', '<missing case_id>')}: step is not an object"
        try:
            phases = [step.get("phase") for step in steps]
            if any(not isinstance(phase, str) or phase not in PHASE_ORDER for phase in phases):
                return False, f"{row.get('case_id', '<missing case_id>')}: unknown phase"
            keys = [step_sort_key(step) for step in steps]
        except (AttributeError, KeyError, TypeError, ValueError):
            return False, f"{row.get('case_id', '<missing case_id>')}: invalid sort key"
        if phases != sorted(phases, key=PHASE_ORDER.index) or keys != sorted(keys):
            return False, f"{row.get('case_id', '<missing case_id>')}: phase or within-phase order is invalid"
    return True, "phase and operation/resource order is valid"


def _evidence_rules_ok(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    for row in rows:
        status = row.get("deletion_status")
        steps = row.get("steps")
        case_id = row.get("case_id", "<missing case_id>")
        if not isinstance(steps, list):
            return False, f"{case_id}: steps are not an array"
        if status == "NOT_APPLICABLE":
            if steps:
                return False, f"{case_id}: NOT_APPLICABLE has steps"
            continue
        if status == "COMPLETE" and not steps:
            return False, f"{case_id}: COMPLETE has no evidence-backed verification"
        for step in steps:
            if not isinstance(step, Mapping):
                return False, f"{case_id}: step is not an object"
            phase = step.get("phase")
            evidence_id = step.get("evidence_id")
            if not isinstance(evidence_id, str):
                return False, f"{case_id}: evidence_id must be a string"
            if status == "COMPLETE":
                if phase != "VERIFICATION" or not evidence_id:
                    return False, f"{case_id}: COMPLETE requires cited VERIFICATION steps only"
            elif phase == "FINDING" and not evidence_id:
                return False, f"{case_id}: FINDING requires evidence_id"
            elif phase in ("REMEDIATION", "VERIFICATION") and evidence_id:
                return False, f"{case_id}: future work must have empty evidence_id"
    return True, "finding and complete-verification citations are nonempty; future-work citations are empty"


def _evidence_cutoff_ok(
    root: Path, requests: list[dict[str, str]], rows: list[dict[str, Any]]
) -> tuple[bool, str]:
    request_map = {row.get("case_id", ""): row for row in requests}
    try:
        evidence_times = {
            row["file_id"]: row["captured_at"]
            for row in _load_table(root, "evidence_files.csv")
        }
        evidence_times.update(
            {
                row["activity_id"]: row["event_time"]
                for row in _load_table(root, "system_activity.csv")
            }
        )
        evidence_times.update(
            {
                row["audit_id"]: row["event_time"]
                for row in _load_table(root, "user_audit_log.csv")
            }
        )
    except (OSError, KeyError, csv.Error, UnicodeDecodeError) as exc:
        return False, f"cannot load participant evidence times: {type(exc).__name__}"

    for row in rows:
        steps = row.get("steps")
        request = request_map.get(str(row.get("case_id", "")))
        if not isinstance(steps, list) or request is None:
            return False, "cannot check a row with invalid steps or unknown case_id"
        for step in steps:
            if not isinstance(step, Mapping):
                return False, f"{row.get('case_id')}: step is not an object"
            evidence_id = step.get("evidence_id", "")
            if not evidence_id:
                continue
            if not isinstance(evidence_id, str):
                return False, f"{row.get('case_id')}: evidence_id must be a string"
            captured_at = evidence_times.get(evidence_id)
            if captured_at is None:
                return False, f"{row.get('case_id')}: cited evidence is not in participant files"
            try:
                if parse_timestamp(captured_at) > parse_timestamp(request["audit_at"]):
                    return False, f"{row.get('case_id')}: cited evidence is after audit_at"
            except (KeyError, ValueError, TypeError):
                return False, f"{row.get('case_id')}: invalid evidence or audit timestamp"
    return True, "all citations are participant-visible by audit_at"


def check_output_csv(root: Path, expected_rows: int = EXPECTED_ROWS) -> list[GuardCheck]:
    output_path = root / "output.csv"
    if not output_path.is_file():
        missing = "output.csv is missing"
        return [
            _check(name, False, missing)
            for name in (
                "output.csv exact header",
                "518 output rows",
                "sorted case_id rows",
                "valid JSON arrays",
                "allowed operation/state pairs",
                "consecutive step_no",
                "phase and within-phase ordering",
                "evidence_id rules",
                "no cited evidence after audit_at",
                "pipeline validator",
            )
        ]

    errors: list[str] = []
    rows: list[dict[str, str]] = []
    header: tuple[str, ...] = ()
    try:
        rows, header = _read_csv(output_path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"cannot read output.csv: {type(exc).__name__}")
    results = [
        _check(
            "output.csv exact header",
            header == OUTPUT_FIELDS,
            "expected case_id,deletion_status,steps_json",
        )
    ]

    try:
        requests = _load_table(root, "deletion_requests.csv")
        manifest = _load_table(root, "evidence_files.csv")
        activities = _load_table(root, "system_activity.csv")
        audit_rows = _load_table(root, "user_audit_log.csv")
    except (OSError, KeyError, csv.Error, UnicodeDecodeError) as exc:
        requests, manifest, activities, audit_rows = [], [], [], []
        errors.append(f"cannot read participant CSVs: {type(exc).__name__}")

    count_ok = len(rows) == expected_rows and len(rows) == len(requests)
    results.append(
        _check(
            "518 output rows",
            count_ok,
            f"output={len(rows)}, expected={expected_rows}, requests={len(requests)}",
        )
    )
    case_ids = [row.get("case_id", "") for row in rows]
    expected_ids = sorted(row.get("case_id", "") for row in requests)
    results.append(
        _check(
            "sorted case_id rows",
            case_ids == sorted(case_ids) and case_ids == expected_ids,
            "case_id order matches the sorted request set" if case_ids == expected_ids else "case_id order or set differs from requests",
        )
    )

    parsed_rows, json_ok = _parsed_steps(rows)
    results.append(_check("valid JSON arrays", json_ok, "steps_json must decode to arrays"))
    operation_ok, operation_detail = _step_check(parsed_rows, _operation_pair_ok)
    results.append(_check("allowed operation/state pairs", operation_ok, operation_detail))
    number_types_ok, _ = _step_check(parsed_rows, _step_numbers_ok)
    numbers_ok, numbers_detail = _numbers_consecutive(parsed_rows)
    results.append(
        _check("consecutive step_no", number_types_ok and numbers_ok, numbers_detail)
    )
    ordered, ordering_detail = _ordering_ok(parsed_rows)
    results.append(_check("phase and within-phase ordering", ordered, ordering_detail))
    evidence_ok, evidence_detail = _evidence_rules_ok(parsed_rows)
    results.append(_check("evidence_id rules", evidence_ok, evidence_detail))
    cutoff_ok, cutoff_detail = _evidence_cutoff_ok(root, requests, parsed_rows)
    results.append(_check("no cited evidence after audit_at", cutoff_ok, cutoff_detail))

    validator_ok = False
    validator_detail = "; ".join(errors)
    if not errors:
        try:
            validate_rows(
                requests,
                parsed_rows,
                manifest=manifest,
                activities=activities,
                audit_rows=audit_rows,
            )
        except Exception as exc:
            validator_detail = f"{type(exc).__name__}; details withheld"
        else:
            validator_ok = True
            validator_detail = "validate_rows passed"
    results.append(_check("pipeline validator", validator_ok, validator_detail))
    return results


def _dataset_literals(root: Path) -> set[str]:
    requests = _load_table(root, "deletion_requests.csv")
    manifest = _load_table(root, "evidence_files.csv")
    values = {
        row.get("case_id", "").strip()
        for row in requests
        if row.get("case_id", "").strip()
    }
    for row in manifest:
        file_id = row.get("file_id", "").strip()
        file_path = row.get("file_path", "").strip()
        if file_id:
            values.add(file_id)
        if file_path:
            values.add(file_path)
            values.add(PurePosixPath(file_path).name)
    return values


class _StringLiteralCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.values: list[str] = []

    def _visit_scope(self, node: ast.AST) -> None:
        for field, value in ast.iter_fields(node):
            if field == "body" and isinstance(value, list) and value:
                first = value[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    value = value[1:]
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.values.append(node.value)


def check_hardcoding(root: Path) -> GuardCheck:
    code_root = root / "code"
    try:
        literals = _dataset_literals(root)
    except (OSError, KeyError, csv.Error, UnicodeDecodeError) as exc:
        return _check("dataset-derived hardcoding scan", False, f"cannot load IDs/filenames: {type(exc).__name__}")
    if not code_root.is_dir():
        return _check("dataset-derived hardcoding scan", False, "code/ is missing")

    excluded = {"tests", "evaluation", "__pycache__", "node_modules", ".venv", "venv"}
    sources = [
        path
        for path in code_root.rglob("*.py")
        if path.is_file() and not any(part in excluded for part in path.relative_to(code_root).parts)
    ]
    violations: list[str] = []
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            violations.append(path.relative_to(root).as_posix() + " (unreadable or invalid Python)")
            continue
        collector = _StringLiteralCollector()
        collector.visit(tree)
        if any(value and any(literal in value for literal in literals) for value in collector.values):
            violations.append(path.relative_to(root).as_posix())
    if violations:
        return _check("dataset-derived hardcoding scan", False, "decision literals found in " + ", ".join(violations))
    return _check("dataset-derived hardcoding scan", True, f"checked {len(sources)} runtime Python file(s); comments, docstrings, tests and evaluation fixtures exempt")


def _archive_exclusions(names: Iterable[str]) -> list[str]:
    violations = []
    for name in names:
        path = PurePosixPath(name)
        parts = {part.casefold() for part in path.parts}
        if (
            parts.intersection(EXCLUDED_PARTS)
            or any("cache" in part for part in parts)
            or path.name.casefold().startswith(".env")
            or path.suffix.casefold() in ARCHIVE_SUFFIXES
            or path.suffix.casefold() in CACHE_SUFFIXES
            or path.suffix.casefold() in {".pyc", ".pyo", ".pem", ".p12", ".pfx", ".key", ".der"}
            or name.startswith("code/")
            or ".." in path.parts
        ):
            violations.append(name)
    return violations


def check_archive(root: Path) -> list[GuardCheck]:
    archive = root / "code.zip"
    if not archive.is_file():
        return [
            _check("code.zip readable", False, "code.zip is missing"),
            _check("code.zip required files", False, "code.zip is missing"),
            _check("code.zip exclusions", False, "code.zip is missing"),
        ]
    try:
        with zipfile.ZipFile(archive) as package:
            names = [name for name in package.namelist() if not name.endswith("/")]
            bad_member = package.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"corrupt member: {bad_member}")
    except (OSError, zipfile.BadZipFile) as exc:
        return [
            _check("code.zip readable", False, type(exc).__name__),
            _check("code.zip required files", False, "archive is unreadable"),
            _check("code.zip exclusions", False, "archive is unreadable"),
        ]
    readable = _check("code.zip readable", True, f"{len(names)} file(s)")
    required = {
        "README.md",
        "run.py",
        "evaluation/evaluation_report.md",
        "evaluation/usage_report.md",
    }
    present = set(names)
    has_source = any(name.startswith("pramaantrace/") and name.endswith(".py") for name in names)
    missing = sorted(required - present)
    if not has_source:
        missing.append("pramaantrace/*.py")
    required_check = _check(
        "code.zip required files",
        not missing,
        "README, source and reports present" if not missing else "missing " + ", ".join(missing),
    )
    excluded = _archive_exclusions(names)
    exclusion_check = _check(
        "code.zip exclusions",
        not excluded,
        "no dataset, environment, cache, or nested archive content" if not excluded else "forbidden entries: " + ", ".join(excluded),
    )
    return [readable, required_check, exclusion_check]


def _text_has_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_VALUE_PATTERNS)


def check_secrets(root: Path) -> GuardCheck:
    code_root = root / "code"
    checked: list[str] = []
    findings: list[str] = []
    if not code_root.is_dir():
        return _check("secret scan", False, "code/ is missing")
    ignored_parts = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
    for path in code_root.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.relative_to(code_root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        checked.append(relative)
        if _text_has_secret(text):
            findings.append(relative)

    log_path = root / "log.txt"
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append("log.txt (unreadable)")
        else:
            checked.append("log.txt")
            if _text_has_secret(text):
                findings.append("log.txt")
    else:
        findings.append("log.txt (missing)")

    archive = root / "code.zip"
    if archive.is_file():
        try:
            with zipfile.ZipFile(archive) as package:
                for name in package.namelist():
                    if name.endswith("/"):
                        continue
                    try:
                        text = package.read(name).decode("utf-8")
                    except (UnicodeDecodeError, OSError, KeyError):
                        continue
                    checked.append("code.zip!" + name)
                    if _text_has_secret(text):
                        findings.append("code.zip!" + name)
        except (OSError, zipfile.BadZipFile):
            findings.append("code.zip (unreadable)")
    else:
        findings.append("code.zip (missing)")

    if findings:
        return _check("secret scan", False, "secret-like content at " + ", ".join(sorted(set(findings))))
    return _check("secret scan", True, f"scanned {len(checked)} code/report/log/archive text file(s); no patterns matched")


def _log_entry_errors(body: str, title: str) -> list[str]:
    errors: list[str] = []
    tool_values = re.findall(r"(?m)^tool=(.*)$", body)
    model_values = re.findall(r"(?m)^model=(.*)$", body)
    for field_name, values in (("tool", tool_values), ("model", model_values)):
        if len(values) != 1 or not values[0].strip():
            errors.append(f"{field_name} field count/value")
            continue
        value = values[0].strip().casefold()
        invalid = {"unknown", "unverified", "ai", "model", "<model>", "placeholder", "your model"}
        if value in invalid or value.startswith("unverified:") or (value.startswith("<") and value.endswith(">")):
            errors.append(f"{field_name} is unknown or a placeholder")

    if title == "SESSION START":
        for field_name in (
            "Repo Root:",
            "Branch:",
            "Worktree:",
            "Parent Agent:",
            "Language:",
            "Time Remaining:",
        ):
            if len(re.findall(rf"(?m)^{re.escape(field_name)}\s*\S.*$", body)) != 1:
                errors.append(f"missing or duplicate {field_name[:-1]}")
    else:
        for marker in (
            "User Prompt (verbatim, secrets redacted):",
            "Agent Response Summary:",
            "Actions:",
            "Context:",
        ):
            if marker not in body:
                errors.append(f"missing {marker.rstrip(':')}")
        for field_name in ("branch", "repo_root", "worktree", "parent_agent"):
            if len(re.findall(rf"(?m)^{field_name}=\S.*$", body)) != 1:
                errors.append(f"missing or duplicate context {field_name}")
    return errors


def check_log(root: Path) -> GuardCheck:
    path = root / "log.txt"
    if not path.is_file():
        return _check("log format", False, "log.txt is missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _check("log format", False, "log.txt is unreadable UTF-8")
    matches = list(LOG_ENTRY.finditer(text))
    if not matches:
        return _check("log format", False, "no timestamped entries")
    errors: list[str] = []
    if text[: matches[0].start()].strip():
        errors.append("content before first entry")
    for index, match in enumerate(matches):
        timestamp, title = match.groups()
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"entry {index + 1}: invalid ISO-8601 timestamp")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        entry_errors = _log_entry_errors(body, title)
        if entry_errors:
            errors.append(f"entry {index + 1}: " + ", ".join(entry_errors))
    if errors:
        return _check("log format", False, f"{len(errors)} format issue(s); " + "; ".join(errors[:4]))
    return _check("log format", True, f"{len(matches)} timestamped entries follow AGENTS.md fields")


def run_checks(root: Path) -> list[GuardCheck]:
    results = check_output_csv(root)
    results.extend(check_archive(root))
    results.append(check_secrets(root))
    results.append(check_hardcoding(root))
    results.append(check_log(root))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (defaults to the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    results = run_checks(root)
    for result in results:
        label = "PASS" if result.passed else "FAIL"
        suffix = f": {result.detail}" if result.detail else ""
        print(f"{label} {result.name}{suffix}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
