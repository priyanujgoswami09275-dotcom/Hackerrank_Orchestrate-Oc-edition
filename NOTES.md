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

## M4a — failure analysis and held-out fix

### Reproducible sample split and metrics

Sort sample `case_id` values, then assign 1-based odd positions to A and even
positions to B. Fix development was limited to A; B was held out. These tables
use the harness's matched step tuples, aligned fields, and exact ordered
sequences. The field denominator can exceed the expected-step count when a
candidate has extra steps.

| Run | Split | Status | Steps | Fields | Exact sequences |
|---|---|---:|---:|---:|---:|
| Before fix, structured only | A | 12/16 | 20/93 | 196/651 | 1/16 |
| Before fix, structured only | B | 11/16 | 42/100 | 373/700 | 0/16 |
| Before fix, structured only | All | 23/32 | 62/193 | 569/1,351 | 1/32 |
| After kept fix, structured only | A | 12/16 | 20/93 | 211/651 | 1/16 |
| After kept fix, structured only | B | 11/16 | 43/100 | 406/700 | 1/16 |
| After kept fix, structured only | All | 23/32 | 63/193 | 617/1,351 | 2/32 |
| Final media-enabled run | A | 13/16 | 25/93 | 253/651 | 1/16 |
| Final media-enabled run | B | 11/16 | 43/100 | 406/700 | 1/16 |
| Final media-enabled run | All | 24/32 | 68/193 | 659/1,351 | 2/32 |

The kept, general planner fix adds post-remediation verification for records
and processes that were already compliant in an otherwise incomplete case.
Its structured-only comparison did not reduce any metric on B: B gained one
matched step, 33 aligned fields, and one exact sequence; status was unchanged.
Across all samples it gained one matched step, 48 fields, and one exact
sequence, with no status regression. The change was committed as `7f318e1`.
No M4a fixes were reverted.

The earlier M4b metrics in this file were provisional and used stale,
unversioned OCR cache content. The portable media reader now versions its cache;
the final measurements above supersede those provisional values. Media changes
two sample outputs and corrects one status relative to structured-only. It
does not explain the remaining low step/sequence scores.

### Initial positional sample error buckets (superseded by M4c)

This table was produced by positional alignment. It is retained as history but
is not a reliable attribution of wrong resource/system fields: a missing early
step shifts all later comparisons. The corrected multiset analysis is in M4c
below and is authoritative.

The step-field mismatch counts below are positional comparisons at the same
array index. Missing/extra content-step counts use a multiset comparison that
ignores `step_no`. These categories overlap and must not be summed. Example
descriptions are anonymized patterns, not case-specific rules.

| Rank | Failure bucket | Count | Anonymized example pattern |
|---:|---|---:|---|
| 1 | Missing content steps | 92 | A required absence verification is omitted while the case contains other findings. |
| 2 (tie) | Wrong `resource_id` at aligned positions | 44 | A step is aligned with a different record than the expected subject-linked copy. |
| 2 (tie) | Wrong `system_id` at aligned positions | 44 | A record is attributed to a neighboring or differently named system. |
| 4 | Wrong operation at aligned positions | 37 | A retained/exposed-identifier condition is represented by a different operation. |
| 5 | Wrong state at aligned positions | 35 | The operation is paired with the wrong state, often due to an incomplete record-state reconstruction. |
| 6 | Extra content steps | 20 | A predicted check/remediation has no corresponding expected step. |
| 7 | Wrong `evidence_id` at aligned positions | 17 | A citation differs from the expected capture even though both may be temporally valid. |
| 8 | Wrong phase at aligned positions | 11 | A step is placed in a different phase than the expected ordered plan. |
| — | Wrong `step_no` at aligned positions | 0 | Numbering remains consecutive; the main issue is content and linkage. |

Additional overlapping buckets:

| Bucket | Count | Anonymized example / interpretation |
|---|---:|---|
| Wrong deletion status | 8 cases: 6 expected COMPLETE predicted INCOMPLETE; 2 expected INCOMPLETE predicted COMPLETE | A surviving or incompletely treated copy is missed, or an unresolved state is treated as compliant. |
| Retained-state verification omitted | 29 steps: 17 PRESENT, 8 ANONYMIZED, 4 REDACTED | A retained legal/audit/analytics record is not included in the checklist when another record makes the case incomplete. |
| Required privacy treatment omitted | 6 steps: 3 exposed-PII findings, 2 redactions, 1 anonymization | A retained record with prohibited identifiers does not get the full finding/remediation/check sequence. |
| Replica-drift finding missed | 0 of 4 expected replica-cited remaining-record findings | The public examples where the primary is absent and a replica remains were found; two such cases also have cutoff-visible sync evidence. |
| Active data-flow / restore risk missed | 1 of 6 expected flows and 2 of 3 expected restorable backups | Every detected risk has the ordered finding, disable/block, and verification triple; the missed risks account for absent expected plan steps. |
| Absence-proof rule | 10/10 public COMPLETE absence citations were artifact-backed and at/before `audit_at`: 4 complete-listing omissions and 6 explicit zero-row/404 results | A text-search miss alone is not proof. The test is `test_absence_citations_are_temporal_and_artifact_backed`; a complete SQL/JSON listing or explicit not-found result is required. |
| Media contribution | 2 sample outputs changed; 1 status corrected; media-linked evidence in 8/518 requests | Media helps a small subset and is not the dominant source of sample step errors. |

### Completion conditions and unresolved coverage

- Condition c is exercised by public examples requiring retained-record
  redaction/anonymization and by the synthetic tombstone-with-prohibited-fields
  test. The stable subject reference is retained while disallowed identifiers
  trigger an incomplete plan.
- Condition d is covered synthetically: a missing record under a retention
  rule makes the verdict `INCOMPLETE`. No public sample demonstrates this
  missing-retained-record situation. The allowed operation vocabulary has no
  finding/remediation pair for restoring it; the implementation does not invent
  an operation and emits no fabricated step for that condition. This behavior
  and sample coverage remain explicitly unverified against a canonical example.
- The synthetic replica test compares a primary deletion listing with a
  replica record and a sync event on both sides of `audit_at`; future captures
  are gated out. The synthetic connector/backup test checks phase and operation
  order for both risks.
- Intent uses affirmative multilingual deletion/erasure/purge/suppression,
  account closure/removal, residual-copy removal, and deletion-verification
  patterns. Negated/withdrawn requests and keep-active phrases veto
  authorization; access/export/correction/update/marketing-opt-out phrases
  are non-deletion actions. It never consults `reported_status`. Public labels
  contain 10 COMPLETE and 22 INCOMPLETE requests and zero NOT_APPLICABLE
  requests: non-NOT_APPLICABLE intent is correct on 32/32; NOT_APPLICABLE is
  untestable at 0/0. The 22 NOT_APPLICABLE predictions in the 518-case run
  have no public labels.

### Remaining issues and next work

The highest-volume errors are incomplete step discovery and system/resource
linkage, followed by operation/state selection. Some can be addressed with
more general evidence adapters, stronger record joins, and state reconciliation
across topologies. A tool-using LLM might help investigate ambiguous text and
cross-artifact links, but it cannot override the temporal gate or repair a
planner finding that the deterministic verifier cannot reproduce. No LLM was
started in M4a. The 32 public cases are a weak estimate for the 518 evaluation
requests.

### Runtime and media portability

For this resumed session, the local Codex config reports
`model = "openai/gpt-6-luna"`; the full baseline made zero model calls. The
portable media fallback is Vision first, then Tesseract when installed; scanned
PDF fallback also requires PyPDFium2. Apple Vision and selectable-PDF extraction
were exercised on this macOS host. Tesseract is not installed here, so the
portable OCR route is unit/mock-tested but not end-to-end verified. The
cache-disabled full run and warm-cache run both produced the same standalone
`output.csv`; the CSV does not require the private OCR cache.

## What was tried or reverted

- No M4a change was reverted. The candidate before and after the retained-state
  verification fix is preserved by comparing the pre-fix source revision with
  the current structured-only run.
- Earlier media score observations based on unversioned OCR cache entries were
  superseded after the cache-key version change; no case-specific patch was
  retained from those observations.

## M4c — corrected diagnostics, status review, and intent audit

### Diagnostic method and corrected buckets

The split still sorts public sample IDs and assigns 1-based odd positions to A
and even positions to B. **This M4c review is not a fully blind held-out
experiment:** I inspected all eight wrong-status cases, including B, before the
support-rule trial. A/B figures below are reported, but B is descriptive rather
than independent generalization evidence.

`code/evaluation/failure_analysis.py` compares each case as a multiset of
`(phase, system_id, resource_id, operation, state, evidence_id)` tuples and
ignores `step_no`. It reports the full unmatched expected/predicted tuples for
each case. It pairs only unmatched steps that differ in exactly one content
field; it does not infer a resource/system mismatch from a shifted array index.
`python3 evaluation/failure_analysis.py` runs this diagnostic against a
temporary sample baseline without changing `output.csv`.

| Rank | Corrected bucket | Count | Anonymized example |
|---:|---|---:|---|
| 1 | Unpaired missing expected content steps | 80 | An expected absent-record verification has no corresponding candidate step. |
| 2 | One-field `evidence_id` mismatches | 12 | A compliant verification has an empty future-work citation because the candidate classified the case INCOMPLETE, while the expected COMPLETE answer cites a timely snapshot. |
| 3 | Unpaired extra candidate content steps | 8 | A candidate reports and remediates a support message that the expected answer treats as already redacted. |
| — | Isolated wrong `resource_id` pairs | 0 | No unmatched pair differed only in resource ID. Some unpaired steps may involve linkage, but cannot safely be assigned this label. |
| — | Isolated wrong `system_id` pairs | 0 | No unmatched pair differed only in system ID; multi-field unpaired steps are not attributed speculatively. |
| — | Isolated wrong operation/state/phase pairs | 0 | No unmatched pair differed only in operation, state, or phase. |

Other overlapping diagnostic buckets:

| Bucket | Count | Anonymized example / interpretation |
|---|---:|---|
| Wrong status | 8 cases: 6 expected COMPLETE → predicted INCOMPLETE; 2 expected INCOMPLETE → predicted COMPLETE | A positive cutoff-visible lookup or an unblocked restore is not translated into the expected incomplete verdict; a resource with no safe subject link prevents a complete verdict. |
| Retained/already-compliant state handling | 29 expected checks: 23 unpaired missing, 6 citation-only mismatches | A policy-required retained audit record or already-anonymized analytics profile needs a target-state verification even when another record makes the plan incomplete. |
| Replica drift missed | 0/4 expected primary-absent/replica-present findings missed | A primary listing is absent while a timely read/failover replica still contains the record; the baseline reports the copy. |
| Sync recreation missed | 0/3 expected sync-linked sample findings missed | A copy reappears through a sync event at or before the audit cutoff; later events remain excluded. |
| Active connector/data-flow risk missed | 1/6 expected findings | An enabled flow without a candidate record link is not found; each flow that is found receives the finding/disable/verification triple. |
| Backup restore risk missed | 2/3 expected findings | A backup event uses a deletion-block field rather than the `restore_allowed` field currently consumed by the planner. |
| Invalid absence-proof citations | 0/10 public COMPLETE absence citations | Four citations are complete-listing omissions and six are explicit zero-row/404 results; none is a text-search miss alone. |
| Media contribution | 2 sample outputs changed, 1 status corrected, 8/518 full requests linked to media | OCR evidence changes one small number of public predictions; it does not address most structured-record linkage errors. |

Before pairing one-field differences, the strict content multiset shows 92
missing expected tuples and 20 extra candidate tuples. The 12 citation-only
pairs explain 12 of each, leaving 80 genuinely unpaired expected steps and
8 unpaired extras. The prior positional counts of 44 wrong system IDs and 44
wrong resource IDs were alignment artifacts and are withdrawn. The evaluator's
reported step metric still includes `step_no`; exact content matching without
numbering is 101/193, while the evaluator's numbered tuple score remains
68/193.

The 29 expected target-state checks for retained/already-compliant records are
not all wholly absent: 23 are unpaired missing checks (14
`VERIFY_RECORD_PRESENT`, 8 `VERIFY_RECORD_ANONYMIZED`, 1
`VERIFY_RECORD_REDACTED`), and 6 are citation-only mismatches across the three
expected-COMPLETE support cases (3 PRESENT and 3 REDACTED checks). The old
statement that all 29 were simply omitted is therefore too broad.

### The eight wrong statuses and their evidence

Labels below are anonymized by pattern and sorted public-sample order, not
embedded in implementation logic. All cited captures listed are at or before
their request's `audit_at`; post-cutoff evidence was excluded from every store
query.

| Group | Expected → predicted | Trigger / rule condition | Cutoff-visible snapshot and interpretation |
|---|---|---|---|
| A–B | COMPLETE → INCOMPLETE (2) | No record key was discovered. The expected subject-linked `USER_PROFILE` is absent under rule_01 (`Always` → DELETE). | Both expected absence checks cite the failover account listing captured 2026-09-02 23:00Z; audits are 2026-09-03 11:30Z and 2026-09-04 15:00Z. No timely identity-bearing record/activity link was found, so the baseline emitted no verification. No hold/retention exception or present replica explains the expected COMPLETE state. |
| C | COMPLETE → INCOMPLETE (1) | The same linkage failure affects an absent `USER_PROFILE` under rule_01 and an already-compliant `ANALYTICS_PROFILE` under rule_07 (ANONYMIZE when attributable). | The expected absence citation is the 2026-09-02 23:00Z account listing. A later inventory capture at 2026-09-05 07:18:01Z is still before the 2026-09-07 10:20Z audit; the anonymized analytics record is captured 2026-09-07 09:45Z. The baseline did not connect either resource to the subject. No legal hold or replica conflict explains the status. |
| D | INCOMPLETE → COMPLETE (1) | An identity-linked analytics lookup has `rows=1` at 2026-09-15 11:59:39Z, before the 12:00Z audit. Rule_07 asks whether the record is still attributable; the normalized record is linked through extracted identifiers, but the prohibited-identifier check only examines selected attributes and treats it as already anonymized. | The expected sample calls for REPORT_REMAINING_RECORD / DELETE_RECORD. That remediation conflicts with rule_07's ANONYMIZE action if the item is an attributable analytics profile. It may be a category-adapter issue, but this appears in one sample only; no fix was retained. |
| E | INCOMPLETE → COMPLETE (1) | Rule_14 governs the backup archive. The timely event says `restore_candidate_evaluated` and `deletion_block=false`; the planner only checks `restore_allowed`, which is absent, and therefore misses the restore risk. | The event capture is 2026-09-15 11:59:39Z, before the 12:00Z audit. No later backup record for this resource is available by the cutoff. The sample expects REPORT_RESTORE_RISK / BLOCK_RESTORE / VERIFY_RESTORE_BLOCKED. This alternate backup-state schema occurs in one sample, so it remains unverified and was not patched. |
| F–H | COMPLETE → INCOMPLETE (3) | Rule_05 retains shared support context and requires REDACT. The current check treats a subject-matching `customer_reference` as prohibited even though the expected state is redacted and direct contact fields are absent. | All three expected states cite the service export captured 2026-09-15 11:44:55Z, before the 12:00Z audits. It is the latest support-message record found at those cutoffs. The later 12:00Z bundle does not contain a later support-message record. No legal hold, ownership exception, or replica drift is indicated. |

Root causes are therefore: missing evidence-backed subject/resource linkage (3
cases), support-message customer-reference interpretation (3), an analytics
attribution/category/operation mismatch (1), and an alternate backup restore
field (1). The support-reference trial removed that field from the prohibited
identifier check. It improved status accuracy but worsened held-out and overall
field accuracy, so it was reverted under the round's no-regression rule. The
analytics and backup patterns each occur in one public sample and were not
implemented as dataset-specific fixes. The three unlinked cases have no safe
generic resource join in the cutoff-visible records; deriving IDs from their
names or sample labels would be an unsupported shortcut.

### Fix trials and split scores

| Run | Split | Status | Steps | Fields | Exact sequences |
|---|---|---:|---:|---:|---:|
| Final baseline before M4c edits | A | 13/16 | 25/93 | 253/651 | 1/16 |
|  | B | 11/16 | 43/100 | 406/700 | 1/16 |
|  | All | 24/32 | 68/193 | 659/1,351 | 2/32 |
| Temporary support-reference trial | A | 14/16 | 25/93 | 246/651 | 1/16 |
|  | B | 13/16 | 43/100 | 392/700 | 1/16 |
|  | All | 27/32 | 68/193 | 638/1,351 | 2/32 |
| Final after revert and intent correction | A | 13/16 | 25/93 | 253/651 | 1/16 |
|  | B | 11/16 | 43/100 | 406/700 | 1/16 |
|  | All | 24/32 | 68/193 | 659/1,351 | 2/32 |

The support-reference trial was reverted: B status rose by two cases, but B
field accuracy fell from 406/700 to 392/700 and overall field accuracy fell
from 659/1,351 to 638/1,351. The final policy code is unchanged by that trial.
The later intent correction does not affect the public sample, which has no
NOT_APPLICABLE labels; its A, B, and all-sample metrics are unchanged, not
claimed as a scored improvement.

### Retained-state rule and condition checks

For every evidence-linked record with a known deletion-rule category, assess
the latest state at `audit_at` against the rule's target:

- DELETE: verify ABSENT when absent; otherwise report, propose DELETE, and
  require a future absence verification.
- REDACT/ANONYMIZE: when prohibited identifiers remain, report and remediate;
  otherwise verify the required REDACTED/ANONYMIZED state. In an INCOMPLETE
  plan, already-compliant checks are included with an empty future
  `evidence_id`.
- RETAIN: verify PRESENT when the condition (including hold/retention or
  attachment ownership/sharing) requires retention. A missing required retained
  record makes the verdict INCOMPLETE, but the allowed vocabulary cannot
  describe restoring it, so no operation is invented.
- DATA_FLOW/BACKUP_ARCHIVE: active flows or allowed restores get finding,
  disable/block remediation, and future verification; already-inactive/
  blocked processes get a compliant-state verification.

The planner already implements this rule for discovered resources. Added a
synthetic test that checks PRESENT, REDACTED, ANONYMIZED, and ABSENT targets in
one incomplete plan; it passes without changing sample predictions. Public
samples contain 29 expected retained/already-compliant target checks, but do
not show a required retained record missing. Condition d therefore remains
unverified against a public expected answer; the synthetic missing-hold test
returns INCOMPLETE with no invented step.

At the sample cutoff, the baseline found 4/4 expected primary-absent /
replica-present remaining-record findings and 3/3 expected sync-linked
recreations. It found 5/6 expected active data flows and 1/3 expected
restorable backups. Every risk it did detect had its ordered finding,
remediation, and verification triple. Unit tests separately check replica
drift, sync cutoff behavior, and flow/restore order. The 10 public COMPLETE
absence citations remain artifact-backed and timely: 4 complete-listing
omissions and 6 explicit zero-row/404 results; a text-search miss alone is not
accepted.

### Intent audit and corrected request-language handling

The pre-fix full run predicted 22 NOT_APPLICABLE requests. Manual review of
`request_text` only (not `reported_status`) found 8 clear access/correction/
marketing/keep-active requests and 14 repeated Portuguese requests explicitly
asking for permanent account deletion. The 10 shortest requests classified as
deletion included one login-help request that explicitly says not to close the
account, plus 9 explicit Japanese account-deletion requests. The intent rules
now recognize Portuguese `exclusão` / `excluir`, Portuguese negation, and
negated account closure. Unit tests cover those general phrases.

This correction is not scored by the public sample because all 32 public
requests are labeled as deletion requests. The intent changes are retained
because the reviewed text is unambiguous, but accuracy on hidden N/A labels is
still unverified. The full output now has 9 NOT_APPLICABLE rows rather than
22; no reported-status value was used in this review.

### Final M4c validation

- Full run: 518 rows, COMPLETE=122, INCOMPLETE=387, NOT_APPLICABLE=9.
- Output SHA-256: `9745eb17e50948658c8531dc173e64e7b8e381faa44b9700749dd9dc5a8d2bf8`.
- Two consecutive warm-cache full runs were byte-identical with that SHA-256.
- Sample evaluation remains status 24/32, step 68/193, field 659/1,351,
  exact sequence 2/32.
- Tests: 44 passed. Source-literal scan passed.
- No M5 agent was started. The output remains a deterministic baseline.

### Follow-up verification (2026-10-25)

- The active terminal runtime exposes `ANTHROPIC_MODEL=claude-opus-4-8` and
  `ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8`. This supersedes the earlier
  config/footer discrepancy for this verification turn; the append-only
  correction is recorded in `log.txt`. The prediction pipeline still made
  zero model calls.
- Re-ran the 44-test suite and the one-command sample evaluator: status 24/32,
  steps 68/193, fields 659/1,351, exact sequences 2/32.
- Re-ran the full baseline twice. Both runs validated 518 rows with
  COMPLETE=122, INCOMPLETE=387, NOT_APPLICABLE=9 and produced the same
  SHA-256 listed above.
- Verified the existing 31-entry `code.zip` without rebuilding it. Source
  files and both evaluation reports are present at the archive root layout
  prescribed by packaging the contents of `code/`; dataset, cache, nested
  archive, and secret-like-value checks passed.
