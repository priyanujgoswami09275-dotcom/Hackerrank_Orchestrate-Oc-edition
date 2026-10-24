#!/usr/bin/env python3
"""Create and audit code.zip from this directory's contents."""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from check_source_literals import scan_source_literals


CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
ARCHIVE = ROOT / "code.zip"
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "build",
    "dist",
    "target",
    "out",
    "data",
    "dataset",
    "datasets",
    "corpus",
}
ARCHIVE_SUFFIXES = {
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".rar",
    ".bz2",
    ".xz",
}
SECRET_NAME_PARTS = ("secret", "credential", "auth")
SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def should_exclude(relative_path: Path) -> bool:
    parts = relative_path.parts
    if any(part in EXCLUDED_DIRS or "cache" in part.casefold() for part in parts):
        return True
    name = relative_path.name.casefold()
    if name.startswith(".env") or name in {"id_rsa", "id_ed25519"}:
        return True
    if any(token in name for token in SECRET_NAME_PARTS):
        return True
    if relative_path.suffix.casefold() in ARCHIVE_SUFFIXES | {
        ".pyc",
        ".pyo",
        ".pem",
        ".p12",
        ".pfx",
        ".key",
        ".der",
    }:
        return True
    return False


def candidate_files() -> list[Path]:
    return sorted(
        path
        for path in CODE.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not should_exclude(path.relative_to(CODE))
    )


def verify_required_files(files: list[Path]) -> None:
    relative = {path.relative_to(CODE).as_posix() for path in files}
    required = {
        "README.md",
        "evaluation/evaluation_report.md",
        "evaluation/usage_report.md",
    }
    missing = sorted(required - relative)
    if missing:
        raise ValueError(
            "required submission files are missing: " + ", ".join(missing)
        )


def verify_no_secret_values(files: list[Path]) -> None:
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(text) for pattern in SECRET_VALUE_PATTERNS):
            raise ValueError(
                f"secret-like value detected in package candidate: "
                f"{path.relative_to(CODE).as_posix()}"
            )


def verify_archive(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as package:
        names = sorted(package.namelist())
        for name in names:
            relative = Path(name)
            if should_exclude(relative):
                raise ValueError(f"excluded content found in archive: {name}")
            if name.startswith("code/") or "dataset" in relative.parts:
                raise ValueError(f"unexpected archive root/content: {name}")
        if any(Path(name).suffix.casefold() in ARCHIVE_SUFFIXES for name in names):
            raise ValueError("nested archive found in code.zip")
        expected = {path.relative_to(CODE).as_posix() for path in candidate_files()}
        if set(names) != expected:
            raise ValueError("archive listing differs from filtered code tree")
        return names


def main() -> int:
    files = candidate_files()
    try:
        literal_findings = scan_source_literals(CODE, ROOT / "dataset")
        if literal_findings:
            raise ValueError(
                "source literal scan failed: "
                + ", ".join(
                    f"{path} contains {literal}"
                    for path, literal in literal_findings
                )
            )
        verify_required_files(files)
        verify_no_secret_values(files)
        with zipfile.ZipFile(
            ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as package:
            for path in files:
                package.write(path, path.relative_to(CODE).as_posix())
        names = verify_archive(ARCHIVE)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"packaging error: {exc}", file=sys.stderr)
        return 2

    print(f"Created: {ARCHIVE}")
    print(f"Archive entries: {len(names)}")
    for name in names:
        print(f"  {name}")
    print("Exclusions and secret-like-content checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
