#!/usr/bin/env python3
"""Fail if source embeds case IDs, evidence IDs, or evidence file names."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
SOURCE_SUFFIXES = {".py", ".swift", ".md", ".json", ".toml", ".yaml", ".yml"}
EXCLUDED_PARTS = {
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "cache",
    ".cache",
}


def source_files(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in SOURCE_SUFFIXES
        and not any(
            part in EXCLUDED_PARTS
            for part in path.relative_to(source_root).parts
        )
    )


def forbidden_dataset_literals(dataset_root: Path) -> set[str]:
    requests_path = dataset_root / "deletion_requests.csv"
    manifest_path = dataset_root / "evidence_files.csv"
    with requests_path.open("r", encoding="utf-8-sig", newline="") as handle:
        case_ids = {
            row["case_id"].strip()
            for row in csv.DictReader(handle)
            if row.get("case_id", "").strip()
        }
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    evidence_ids = {
        row["file_id"].strip()
        for row in manifest
        if row.get("file_id", "").strip()
    }
    evidence_names = {
        value
        for row in manifest
        for value in (
            row.get("file_path", "").strip(),
            Path(row.get("file_path", "")).name,
        )
        if value
    }
    return case_ids | evidence_ids | evidence_names


def scan_source_literals(
    source_root: Path,
    dataset_root: Path,
) -> list[tuple[str, str]]:
    forbidden = forbidden_dataset_literals(dataset_root)
    findings: list[tuple[str, str]] = []
    for path in source_files(source_root):
        content = path.read_text(encoding="utf-8", errors="replace")
        for literal in sorted(forbidden):
            if literal in content:
                findings.append((path.relative_to(source_root).as_posix(), literal))
    return findings


def main() -> int:
    findings = scan_source_literals(CODE, ROOT / "dataset")
    if findings:
        print("Hardcoded dataset literals found:")
        for path, literal in findings:
            print(f"  {path}: {literal}")
        return 1
    print(
        "Source literal scan: PASS "
        "(case IDs, evidence IDs, and evidence filenames are not embedded)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
