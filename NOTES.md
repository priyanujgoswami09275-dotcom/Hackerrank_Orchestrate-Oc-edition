# PramaanTrace development notes

## Session setup and document decisions

- Read `AGENTS.md`, `agent_trace_instructions.md`, `problem_statement.md`, `README.md`, `CLAUDE.md`, and `PRD.md` in the requested order.
- The requested `architecture.md` path is absent; the repository has `Architecture .md` (capitalized, with a space), which was read as the apparent intended architecture document.
- `AGENTS.md` §6.8 requires `evaluation/evaluation_report.md` and `evaluation/usage_report.md` inside `code.zip`. `problem_statement.md` also specifies `evaluation/` in the package; `README.md`, `PRD.md`, and `Architecture .md` instead refer to `code/evaluation/`. Follow AGENTS.md for the package path. The evaluation harness source remains under `code/evaluation/`.
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

## M4 — deterministic baseline

- Added a rule-based intent check, policy engine, as-of state assessor, planner, output validator/writer, and `code/run.py`. The empty `code/main.py` and `code/evaluation/main.py` starter files remain untouched; `dataset/output.csv` remains untouched.
- Added `--requests` to `code/run.py` so the same baseline can be run on the 32 public sample requests for evaluation as well as the full evaluation set. No case- or evidence-specific branches were added.
- Public-sample intent classification is 32/32 after adding affirmative closure/removal and prior-deletion verification phrasings. `reported_status` is not consulted.
- Initial sample scoring exposed a false-match bug: placeholder `"null"` customer references were indexed as identifiers, making many unrelated records appear linked. Filtered null-like sentinels in the loader and identity resolver, and added regression tests. Activity detail matching now also requires identifier token boundaries to prevent `user_01` matching `user_010`.
- Full run: `python3 code/run.py` produced and structurally validated 518 rows at repository-root `output.csv`: COMPLETE=119, INCOMPLETE=377, NOT_APPLICABLE=22.
- Sample baseline score after the above fixes: status accuracy 71.88% (23/32); step-level accuracy 32.12% (62/193); field-level accuracy 42.12% (569/1351 aligned fields); sequence accuracy 3.12% (1/32). Sample ordering passed. These are measured baseline results, not a claim of strong accuracy.
- Remaining visible-sample failures include unsupported resource linkage when no cutoff-visible identity-bearing record exists, missing retained/security records in some plans, and a few state/policy mismatches. Image/PDF evidence remains uninspected and is not used by the baseline. These are open limitations; do not paper over them with case-specific mappings.
- Verification: `python3 -m unittest discover -s code/tests -v` passed all 24 tests. The baseline validator confirmed every cited evidence reference exists and is no later than its request's `audit_at`.
- Diagnostic process caveat: one broad structured-evidence text search displayed a record from a capture later than one sample request's cutoff. That observation was not used in the implementation or output; it must not be relied on or cited. Subsequent baseline queries remained gated internally by `audit_at`.

## What was tried or reverted

- The first sample-score attempt compared the 518 evaluation-case output directly with 32 sample cases; the IDs are distinct, so it correctly reported the sample rows missing. Added a request-file option and reran the baseline on `sample_deletion_requests.csv`; no code path or labels were reverted.

## M4b — local media reader and completion-condition checks

- Inventory from `evidence_files.csv`: 15 local media files total (11 PNG and 4 PDF). The 518-case run linked media-derived records to 8 distinct requests across 7 media files. Two public sample requests had identity-linked media evidence; enabling media changed those two sample outputs.
- Media handling is implemented in `code/pramaantrace/loader.py`. The manifest timestamp is checked against the requests' maximum `audit_at` before a media path is opened; each resulting capture is stored with its manifest `captured_at`, and all later text/record access still passes through the store's mandatory temporal gate.
- On this macOS runtime, Apple Vision and PDFKit are available through Swift. Apple Vision OCR was run on the PNGs; pypdf extracted selectable text from the PDFs. Scanned PDFs use Vision OCR as a fallback. Extracted text and OCR layout coordinates are cached outside the repository, keyed by a SHA-256 of the asset bytes. A unit test confirms the warm cache does not invoke OCR a second time, and another confirms a post-cutoff media path is not opened.
- OCR initially linked a connector to the wrong nearby row when using plain extracted-text distance. Replaced that association with Vision bounding-box row proximity; ambiguous and non-adjacent mentions are ignored. A generic attachment-content check also separates customer-uploaded attachments from support conversations, avoiding an incorrect redaction classification.
- Sample score, structured-only → media-enabled: status 23/32 (71.88%) → 24/32 (75.00%); step-level 62/193 (32.12%) → 66/193 (34.20%); field-level 569/1,351 (42.12%) → 604/1,351 (44.71%); exact sequence 1/32 (3.12%) → 1/32 (3.12%). Sample ordering passed both runs. This is a measured but small gain; 32 samples remain a weak estimate of 518-case performance.
- Full media-enabled run validated 518 output rows: COMPLETE=120, INCOMPLETE=376, NOT_APPLICABLE=22. Two consecutive runs with the warm external cache produced the same SHA-256: `cb76153310c39a58d7b8c54996d01e28004489a7e6e29c1c9d306f933b535454`.
- Added custom condition tests. A retained tombstone with prohibited direct identifiers is INCOMPLETE and plans redaction. An active held record is verified as retained. If a required retained record is absent from the latest complete listing, the verdict is INCOMPLETE. The allowed operation vocabulary has no way to report or restore that missing retained record, so the current output has no fabricated step for that failure; this remains a contract limitation.
- Added `code/check_source_literals.py`; it dynamically checks source against participant-visible request IDs, evidence IDs, and evidence manifest paths. Added a packaging script that zips only the contents of `code/`, excludes data, caches, credentials, build artifacts, and archives, verifies the archive, and prints its listing. `code/README.md` is packaged; archive-root `evaluation/` corresponds to source `code/evaluation/`.
- Runtime model metadata for this session reports `claude-opus-4-8`; the media-enabled full baseline itself made no LLM calls. Vision and PDF extraction were executed locally. No API key was needed.

## M4a — failure analysis and held-out fixes

- M4a had not been completed before this follow-up; there was no bucket table.
- Re-ran the media-enabled sample baseline and evaluator. Reproduced metrics are status 24/32, steps 64/193, fields 606/1,358 aligned fields, and sequence 1/32. The structured-only run is 23/32, 62/193, 569/1,351, and 1/32. These do not reproduce the previously reported media numbers of 66/193 steps and 604/1,351 fields; the current media-enabled output was byte-identical on two sample runs.
- Fixed split: sort public sample cases by `case_id`; A is positions 1, 3, 5, … and B is positions 2, 4, 6, …. Baseline metrics before fixes:

  | Split | Status | Steps | Fields | Exact sequences |
  |---|---:|---:|---:|---:|
  | A | 13/16 | 22/93 | 233/658 | 1/16 |
  | B | 11/16 | 42/100 | 373/700 | 0/16 |
  | All | 24/32 | 64/193 | 606/1,358 | 1/32 |

- Kept fix 1: for an `INCOMPLETE` case, the planner now includes verification checks for already-compliant retained records and disabled processes, alongside checks for records/processes needing remediation. All verification evidence IDs in an incomplete plan are empty, as required for future checks. Added a synthetic regression test for a remaining profile plus an already-compliant legal-hold record.
- Fix 1 metrics:

  | Split | Status | Steps | Fields | Exact sequences |
  |---|---:|---:|---:|---:|
  | A | 13/16 | 22/93 | 245/665 | 1/16 |
  | B | 11/16 | 43/100 | 406/700 | 1/16 |
  | All | 24/32 | 65/193 | 651/1,365 | 2/32 |

- The fix improved field and sequence scores on both halves and step score on B without reducing any metric; status was unchanged. The rise in the field denominator reflects additional planned verification steps. This change is contract-driven, not sample-specific.
- The sample set contains 10 expected `COMPLETE` and 22 expected `INCOMPLETE` cases, with no `NOT_APPLICABLE` examples. The intent classifier predicts all 32 as deletion-authorizing, so sample specificity is untested; the 22 `NOT_APPLICABLE` rows in the 518-case baseline have no public labels to validate against.
