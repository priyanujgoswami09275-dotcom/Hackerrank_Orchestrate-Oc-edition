"""Stable CSV output writer."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


OUTPUT_HEADER = ("case_id", "deletion_status", "steps_json")


def write_output(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda row: str(row["case_id"]))
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(OUTPUT_HEADER)
        for row in ordered:
            steps_json = json.dumps(
                row["steps"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            writer.writerow(
                (row["case_id"], row["deletion_status"], steps_json)
            )
