# PramaanTrace development notes

## Session setup and document decisions

- Read `AGENTS.md`, `agent_trace_instructions.md`, `problem_statement.md`, `README.md`, `CLAUDE.md`, and `PRD.md` in the requested order.
- The requested `architecture.md` path is absent; the repository has `Architecture .md` (capitalized, with a space), which was read as the apparent intended architecture document.
- `AGENTS.md` §6.8 requires `evaluation/evaluation_report.md` and `evaluation/usage_report.md` inside `code.zip`. This takes precedence over the problem statement and README paths, which say `code/evaluation/`. Keep the package paths at `evaluation/`.
- The deliverable is the repository-root `output.csv`. `dataset/output.csv` is a one-line template and is not to be modified.
- The challenge deadline is not configured in the repository.
- The runtime did not expose an authoritative model identifier in the available metadata/environment. The session log records `model=unknown`; no model name was inferred.

## M1 — sample evaluation harness

- Added `code/evaluation/harness.py` without replacing the empty `code/evaluation/main.py` starter.
- Added tests in `code/tests/test_evaluation_harness.py`.
- The public sample's within-phase operation ordering and consecutive step numbering are checked against the order in `AGENTS.md` §6.4.
- Verification run: `python3 code/evaluation/harness.py dataset/sample_output.csv` reported 32/32 status accuracy, 193/193 step accuracy, 1351/1351 field accuracy, 32/32 sequence accuracy, and passed the sort-contract check. This is the harness self-check on the expected file, not a baseline prediction score.
- Verification run: `python3 -m unittest discover -s code/tests -v` passed all 5 tests.
- Absence-citation rule from sample inspection: an omitted resource is supported by a structured, point-in-time system listing (SQL snapshot table or JSON collection listing) only when the artifact is a listing, not merely because a text search misses the identifier. A direct lookup also proves absence when it records an explicit zero-row/404 result. All sample citations must be at or before the case's `audit_at`.
- Four cited complete-case absence steps omit the resource from their artifact: three cite SQL table snapshots and one cites a JSON account-service collection snapshot. Six additional cited absence steps explicitly contain the resource identifier alongside a not-found/zero-row result. The sample includes a later, empty inventory capture that is consistent with the earlier SQL omission citation for one case; therefore “latest snapshot” is a useful selection preference, but the sample does not establish it as a strict requirement for every absence citation. A later contradictory snapshot must not be ignored.
- No changes have been made under `dataset/`.

## M2 — structured evidence loader and gated store

- Added explicit SQLite table adapters for the four observed SQL layouts: account-profile tables, normalized inventory tables, packed `record_json` snapshot tables across primary/replica topologies, and the search-primary table. Unknown SQL tables fail loudly.
- Loaded all 79 structured evidence artifacts (24 SQL, 28 JSON, 26 logs, and 1 text file); deferred the 15 image/PDF artifacts for the later multimodal pass.
- Normalized 3,094 records and preserved 469 point-in-time listing scopes, including empty listings needed to support evidence-backed absence checks.
- Record queries, listing-scope queries, text reads, and capture enumeration all require `audit_at`; tests verify post-cutoff records and text are not returned.
- Verification run: `python3 -m unittest discover -s code/tests -v` passed all 11 tests. SQL adapter coverage was exercised across all 24 SQL evidence files, and an unmapped-table fixture was confirmed to fail loudly.

## M3 — temporal identity resolver

- Added `code/pramaantrace/identity.py`. It replays identity events only through `audit_at`, uses a current identity snapshot only when its `updated_at` is not later than the cutoff, normalizes email/phone values, and derives SHA-256 hashes for visible emails.
- Customer references can be joined only through records returned by the temporally gated evidence store.
- Reverified current snapshot email hashes: 850/850 match SHA-256 of normalized email.
- Evaluation request coverage: 518/518 emails resolve at their respective `audit_at`; 100 are historical-email-only matches; no ambiguous request-email matches were observed.
- Verification run: `python3 -m unittest discover -s code/tests -v` passed all 16 tests, including future-identity cutoff, historical aliases, hash coverage, and cutoff-gated customer-reference joins.

## What was tried or reverted

- No implementation approach has been reverted.
