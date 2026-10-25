#!/usr/bin/env python3
"""Run the PramaanTrace deletion audit and write repo-root output.csv."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.agent.client import OpenAICompatibleClient  # noqa: E402
from pramaantrace.agent.config import AgentConfig, AgentConfigurationError  # noqa: E402
from pramaantrace.agent.loop import Investigator  # noqa: E402
from pramaantrace.agent.pipeline import AgentRunResult, run_agent_pipeline  # noqa: E402
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
    parser.add_argument(
        "--disable-agent",
        action="store_true",
        help="skip LLM investigation even when credentials are configured",
    )
    args = parser.parse_args(argv)

    agent_config = None
    if not args.disable_agent:
        try:
            agent_config = AgentConfig.from_env()
        except AgentConfigurationError as exc:
            parser.error(str(exc))

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
    agent_result: AgentRunResult | None = None
    if agent_config is None:
        rows = run_baseline(bundle)
    else:
        investigator = Investigator(
            OpenAICompatibleClient(agent_config),
            step_cap=agent_config.step_cap,
        )
        agent_result = run_agent_pipeline(bundle, investigator)
        rows = agent_result.rows
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
    if agent_result is not None:
        print("Investigator: enabled")
        print(
            "Investigator cases: "
            f"attempted={agent_result.attempted_cases}, "
            f"completed={agent_result.completed_cases}, "
            f"fallbacks={agent_result.fallback_cases}"
        )
        print(
            "Investigator candidates: "
            f"accepted={agent_result.accepted_candidates}, "
            f"rejected={agent_result.rejected_candidates}"
        )
        usage = agent_result.usage_summary
        if usage:
            print(
                "Model usage: "
                f"network calls={usage.get('network_calls', 0)}, "
                f"cache hits={usage.get('cache_hits', 0)}, "
                f"input tokens={usage.get('input_tokens', 0)}, "
                f"output tokens={usage.get('output_tokens', 0)}"
            )
            cost = usage.get("cost_usd")
            if cost is None:
                print(
                    "Model cost: not fully reported "
                    f"({usage.get('cost_unreported_calls', 0)} call(s) missing provider cost/rates)"
                )
            else:
                print(f"Model cost: ${cost:.8f}")
    elif args.disable_agent:
        print("Investigator: disabled by --disable-agent")
    else:
        print("Investigator: disabled (LLM_API_KEY not set)")
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
