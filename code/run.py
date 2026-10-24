#!/usr/bin/env python3
"""Run the deterministic PramaanTrace baseline and write repo-root output.csv."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.baseline import run_baseline  # noqa: E402
from pramaantrace.loader import load_dataset, read_csv_rows  # noqa: E402
from pramaantrace.validator import validate_rows  # noqa: E402
from pramaantrace.writer import write_output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output.csv",
        help="output CSV path (default: repository-root output.csv)",
    )
    parser.add_argument(
        "--requests",
        type=Path,
        default=ROOT / "dataset" / "deletion_requests.csv",
        help="request CSV to process (default: all evaluation requests)",
    )
    parser.add_argument(
        "--disable-media",
        action="store_true",
        help="run the structured-only baseline for media impact comparisons",
    )
    args = parser.parse_args(argv)

    requests_path = args.requests
    if not requests_path.is_absolute():
        requests_path = ROOT / requests_path
    requests = read_csv_rows(requests_path)
    bundle = load_dataset(
        ROOT,
        media_request_rows=requests,
        include_media=not args.disable_media,
    )
    bundle.tables["deletion_requests.csv"] = requests
    rows = run_baseline(bundle)
    validate_rows(
        requests,
        rows,
        manifest=bundle.tables["evidence_files.csv"],
        activities=bundle.tables["system_activity.csv"],
        audit_rows=bundle.tables["user_audit_log.csv"],
    )
    write_output(args.output, rows)

    counts = Counter(row["deletion_status"] for row in rows)
    print(f"Validated output: {args.output}")
    print(f"Cases: {len(rows)}")
    print(
        "Statuses: "
        + ", ".join(
            f"{status}={counts.get(status, 0)}"
            for status in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
        )
    )
    print("Validation: PASS")
    print(
        "Media reader: "
        + (
            ", ".join(bundle.media_backends)
            if bundle.media_backends
            else (
                "disabled by request"
                if args.disable_media
                else "UNVERIFIED (no media extraction backend available)"
            )
        )
    )
    print(
        f"Media assets extracted: {bundle.media_processed_count}; "
        f"normalized records: {bundle.media_record_count}"
    )
    if bundle.skipped_multimodal:
        print(
            "Media handling: PARTIAL/UNVERIFIED; "
            f"{len(bundle.skipped_multimodal)} cutoff-eligible files not extracted"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
