# PramaanTrace evaluation report

## Scope and method

The public evaluator contains 32 labeled requests. All scores below compare
predictions with `dataset/sample_output.csv`; hidden labels and organizer-only
files were not used. The evaluation harness reports deletion-status accuracy,
matched step tuples, aligned-field accuracy, and exact ordered-sequence
accuracy. The 32 samples are a weak estimate of behavior on the 518 evaluation
requests. The baseline does not use sample labels or case-specific branches.
Variant-by-variant scores, positional exact-step results, and the safeguard
ablation are detailed in `ablation_report.md`; measured changes and keep/revert
decisions are in `decision_log.md`.

The fixed split sorts sample `case_id` values and assigns 1-based odd positions
to A and even positions to B. M4a development used A. During M4c, all eight
wrong-status examples were inspected before the support-rule trial, so B was
not a blind holdout for that round; its scores are reported as descriptive
checks, not independent generalization evidence.

## Sample evaluation

| Run | Split | Status accuracy | Step accuracy | Field accuracy | Exact sequence |
|---|---|---:|---:|---:|---:|
| Before fix, structured only | A | 75.00% (12/16) | 21.51% (20/93) | 30.11% (196/651) | 6.25% (1/16) |
| Before fix, structured only | B | 68.75% (11/16) | 42.00% (42/100) | 53.29% (373/700) | 0.00% (0/16) |
| Before fix, structured only | All | 71.88% (23/32) | 32.12% (62/193) | 42.12% (569/1,351) | 3.12% (1/32) |
| After kept fix, structured only | A | 75.00% (12/16) | 21.51% (20/93) | 32.41% (211/651) | 6.25% (1/16) |
| After kept fix, structured only | B | 68.75% (11/16) | 43.00% (43/100) | 58.00% (406/700) | 6.25% (1/16) |
| After kept fix, structured only | All | 71.88% (23/32) | 32.64% (63/193) | 45.67% (617/1,351) | 6.25% (2/32) |
| Final media-enabled baseline | A | 81.25% (13/16) | 26.88% (25/93) | 38.86% (253/651) | 6.25% (1/16) |
| Final media-enabled baseline | B | 68.75% (11/16) | 43.00% (43/100) | 58.00% (406/700) | 6.25% (1/16) |
| Final media-enabled baseline | All | 75.00% (24/32) | 35.23% (68/193) | 48.78% (659/1,351) | 6.25% (2/32) |

Rows above are milestone history; the media row predates the M4c intent
correction, which moved three more sample statuses to correct. Current-build
measurements for both flag states are in the enrichment section below.

The field denominator reflects the harness's aligned positions, including
extra candidate steps; it is not the number of expected fields alone. M4c's
corrected per-case multiset diff uses
`(phase, system_id, resource_id, operation, state, evidence_id)` and ignores
`step_no`. It finds 80 unpaired missing expected steps, 8 unpaired extra
steps, and 12 one-field `evidence_id` mismatches. Before pairing one-field
differences, the exact content multiset has 92 missing and 20 extra tuples.
The prior positional counts for wrong `system_id` and `resource_id` were
alignment artifacts and are withdrawn. From `code/`, run
`python3 evaluation/failure_analysis.py` for the per-case unmatched tuples.

Media changed two sample predictions and corrected one status. On the full
request set, media-derived evidence was linked to 8 of 518 cases. This is a
measured modest contribution, not evidence that the OCR association heuristics
generalize.

## Evidence-linkage enrichment (PRAMAANTRACE_ENRICH)

The enrichment pass is an opt-out evidence-linkage layer around the same
deterministic planner. Enrichment is enabled when the flag is unset (the new
default); setting a false-like value disables it for baseline comparisons. The
layer adds:

- system-name normalization for evidence services whose export labels differ
  from the canonical plan systems (`support_replica` → `support_platform`,
  `search_index_service` → `search_service`);
- structured JSON-lines log parsing merged into the same key/value path as
  plain log lines, with trace pairing extended to subject-reference echoes;
- support-attachment ownership read from handover-files' subject column, which
  the support record policy rule requires;
- window-anchored closing `VERIFY_RECORD_ABSENT`: an observed absence only
  enters the plan when its capture inside the request window belongs to this
  request's own operation;
- evidence-named cross-resource references: when subject-linked evidence
  itself names a second resource (for example a search document naming its
  source account), that resource joins the closing checklist when the
  workflow claims to have deleted it inside the window;
- unique-wave account derivation: when the subject's known resources were
  queued for the same deletion and the activity stream contains exactly one
  account `DELETE_RECORD` row near those anchors' claim rows, that row is the
  operation's account; ambiguous neighbourhoods stay unreported.

Official harness measurements (sample predictions regenerated through the
same media-enabled pipeline; rows describe the current build with the flag
unset and set):

| Run | Split | Status accuracy | Step precision | Step recall | Field accuracy | Exact sequence |
|---|---|---:|---:|---:|---:|---:|
| Enrichment opt-out | A | 87.50% (14/16) | 97.83% (45/46) | 48.39% (45/93) | 37.79% (246/651) | 6.25% (1/16) |
| Enrichment opt-out | B | 81.25% (13/16) | 98.55% (68/69) | 68.00% (68/100) | 56.00% (392/700) | 6.25% (1/16) |
| Enrichment opt-out | All | 84.38% (27/32) | 98.26% (113/115) | 58.55% (113/193) | 47.22% (638/1351) | 6.25% (2/32) |
| Enriched default | A | 93.75% (15/16) | 100.00% (77/77) | 82.80% (77/93) | 74.19% (483/651) | 37.50% (6/16) |
| Enriched default | B | 87.50% (14/16) | 100.00% (84/84) | 84.00% (84/100) | 72.00% (504/700) | 37.50% (6/16) |
| Enriched default | All | 90.62% (29/32) | 100.00% (161/161) | 83.42% (161/193) | 73.06% (987/1351) | 37.50% (12/32) |
| Agent-enabled | All | 90.62% (29/32) | 100.00% (161/161) | 83.42% (161/193) | 73.06% (987/1351) | 37.50% (12/32) |

The separate positional exact-step score is 68/193 (35.23%) with enrichment
off and 122/193 (63.21%) with enrichment on. It counts exact seven-field step
objects, including `step_no`, at the same array index, using the per-case
maximum expected/predicted step count as its denominator. Tuple matching
ignores `step_no`; field accuracy is the harness's aligned-field score.

The per-case multiset diff under enrichment finds 32 unpaired missing
expected steps, 0 extra predicted steps, and 0 one-field mismatches. The
residual 32 steps are accept-loss cases where no participant-visible
evidence connects the prediction to the subject:

- 18 empty-evidence account `VERIFY_RECORD_ABSENT` closing steps: nine belong
  to deletion waves whose in-window account row is not unique against the
  subject's anchors, and nine are cited absences whose readback rows carry no
  query key, leaving no participant-visible link between those 404 results and
  the person.
- 7 cited analytics `VERIFY_RECORD_ANONYMIZED` steps: the analytics profiles
  in the cited evidence carry no subject key, so the mapping is not
  participant-visible.
- 7 empty-evidence audit `VERIFY_RECORD_PRESENT` steps: the cited audit
  records are captured after the case's `audit_at` or do not exist in
  participant-visible data, so the temporal gate correctly refuses them.

These residual classes were measured explicitly (per-case diff in
`evaluation/failure_analysis.py` output) rather than assumed; no case-family
shortcut, hidden-label, or organizer-only shortcut was used to generate any
prediction. `output.csv` itself is produced from `deletion_requests.csv`
only.

### Investigator sample comparison

The agent-enabled run used the same 32 sample requests and media extraction as
the enriched deterministic run. Its output CSV was byte-identical to the
baseline: status accuracy remained 29/32, step precision 100% (161/161), step
recall 83.42% (161/193), field accuracy 73.06% (987/1,351), exact sequence
accuracy 37.50% (12/32), with 32 missing and zero extra steps. The investigator
therefore produced no measured sample accuracy or output delta; no gain is
claimed.

The run attempted all 32 authorized cases: 17 completed investigation,
15 fell back to the enriched baseline, 36 candidate links passed deterministic
verification, and zero candidates were rejected. The provider reported
97 network calls, 28 retries, 13 failed requests, 148,681 input tokens,
24,189 output tokens, and 172,870 total tokens. Reported cost was $0.00 for
the configured free model. These usage values describe the sample comparison,
not the later full-dataset run.

### Full-dataset agent run

The full run used `nvidia/nemotron-3.5-super-vl:free` via OpenRouter. It
validated 518 output rows but attempted 509 deletion-authorized cases with 0
completed investigations and 509 baseline fallbacks (100%). It made 1,527
network attempts, including 1,018 retries; 509 requests failed, with 0 cache
hits, 0 input tokens, 0 output tokens, and $0.00 reported cost. It proposed or
accepted no candidate links. The resulting `output.csv` is byte-identical to
`output_baseline.csv` (SHA-256
`35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`), so the
agent predictions were dropped and the deterministic baseline is selected.
The full request set has no public labels; only sample accuracy is scoreable.

No separate successful connectivity/tool-call trace was captured, the cache
contains no responses, and raw traces for three sample cases were not retained.
A second warm-cache full-run comparison was not performed. Budget skips and
`AGENT_CALL_BUDGET` behavior were not measured. Do not interpret failed network
attempts as a measured agent accuracy result.


## Failure analysis and custom cases

Milestone history first: the eight wrong statuses (baseline before M4c)
comprised six expected COMPLETE predicted INCOMPLETE and two expected
INCOMPLETE predicted COMPLETE.

Under the enrichment build exactly three sample statuses remain wrong:
all expect COMPLETE but predict INCOMPLETE with empty step lists. These cases
have zero participant-visible matches for every identity value (current email,
historical email, phone, email hash, and stable user reference) in every
pre-cutoff capture, and zero in-window activity links; the expected citations
are captures outside those audits' cutoffs. The planner keeps its honest
INCOMPLETE fallback rather than citing evidence its own temporal gate rejects.

The earlier support-message customer-reference interpretations, analytics
attribution issues, and backup restore-field mismatches were resolved by the
support-ownership rule, trace-pairing, and readback canonicalization later
work; a support-reference rule trial first improved status counts but lowered
field accuracy on B and all samples, so it was reverted under the then-current
field/no-regression criterion. It was later re-evaluated under the tuple-based
keep gate and kept in M4d: status improved 24/32 → 27/32, B status 11/16 →
13/16, and B tuple recall 43/100 → 68/100. This follow-up supersedes the earlier
revert decision; the current support policy treats the stable customer
reference as shared context rather than prohibited direct PII.

The 29 expected retained/already-compliant checks (pre-M4c milestone
history; the current enriched residual is itemized in the enrichment section)
comprise 23 unpaired missing steps and 6 citation-only mismatches. Public
samples do not show a required retained record missing; condition d is
synthetic-test-only and unverified against public labels. Among expected
sample risks, the baseline found 5/6
active flows and 1/3 restorable backups. Every detected risk had the ordered
finding/remediation/verification triple. It found 4/4 expected
primary-absent/replica-present findings and 3/3 expected sync-linked
recreations. The corrected bucket table, status review, and anonymized
examples are in `NOTES.md`.

Participant-created tests in `code/tests/` cover:

1. **Historical email:** resolve a prior email through the identity audit log
   and find a current subject record.
2. **Legal hold:** preserve and verify a present retention-required record.
3. **Replica drift and sync recreation:** treat a replica copy or a cutoff-visible
   sync recreation as present; exclude evidence after `audit_at`.
4. **Condition c, prohibited identifiers:** retain the stable subject reference
   in a tombstone, but require redaction when prohibited direct identifiers
   remain.
5. **Condition d, missing retained record:** return INCOMPLETE when a required
   retained record is absent, without inventing an unsupported operation.
6. **Active connector and restorable backup:** verify finding/remediation/
   verification order and empty evidence IDs for proposed future work.
7. **Case-scoped tools:** include records at `audit_at`, exclude later records,
   reject other-subject identifiers and arbitrary evidence paths.
8. **Verifier and fallback:** accept a directly linked or structured-reference
   candidate only after replay; reject fake observations, cross-subject and
   ambiguous edges, bare 404s, and post-cutoff evidence; preserve the exact
   baseline row on agent failure.
9. **Instruction-like request:** text asking the system to claim `COMPLETE` and
   omit a remaining record does not override evidence; the result still passes
   the pipeline validator.

The public samples include retained-record verification and redaction/
anonymization behavior, but no public sample demonstrates a required retained
record that is missing. The allowed operation set has no finding or remediation
for restoring such a record; this condition is tested synthetically and remains
unverified against a public expected answer.

Absence-citation inspection verified 10 expected COMPLETE absence citations:
four cite omissions from complete SQL/JSON listings, and six cite explicit
zero-row/404 results. The cited artifacts are at or before `audit_at`. A text
search miss alone is not treated as proof of absence.

The public sample has 10 expected COMPLETE and 22 expected INCOMPLETE requests,
with zero expected NOT_APPLICABLE cases. Public labels therefore cannot score
NOT_APPLICABLE accuracy. Manual review of the 22 pre-fix full-run N/A texts
found 14 repeated Portuguese requests explicitly asking for permanent
deletion, and 8 clear access/correction/marketing/keep-active requests. The 10
shortest deletion-classified requests included one explicit “do not close”
login request and nine explicit Japanese deletion requests. The intent rules
now recognize Portuguese `exclusão`/`excluir`, Portuguese negation, and
negated account closure. This correction does not change public-sample metrics;
N/A accuracy remains unverified against labels.

## Full-dataset output

The final 518-case run used the same deterministic pipeline with the
enrichment pass enabled (`PRAMAANTRACE_ENRICH=1`), and it validated all 518
requests:

| Status | Cases |
|---|---:|
| COMPLETE | 133 |
| INCOMPLETE | 376 |
| NOT_APPLICABLE | 9 |

The root `output.csv` contains one row per request and passed the output
validator. Rows are sorted lexicographically by `case_id`; the evaluator's
sample IDs happen to have consistent widths, while full-dataset IDs do not.
Its SHA-256 is
`35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`.
A second full run in the same session wrote a byte-identical file, and an
independent 518-case trial run to a different path also matched byte for
byte. The submission CSV is standalone and does not require the local OCR
cache.

## Improvements, limitations, and next work

- Filtered null-like customer-reference sentinels and enforced identifier token
  boundaries to avoid unrelated matches.
- Added temporal record/listing/text queries, explicit per-topology SQL
  adapters, and a cutoff-aware identity resolver.
- Added state checks for retained records and privacy-required redaction/
  anonymization, plus the M4a verification-completeness fix.
- Added local media extraction with Apple Vision on macOS and a Tesseract
  fallback when installed. The cache is outside the repository and excluded
  from the archive.
- Added the flag-gated evidence-linkage enrichment pass (system aliases,
  JSON-lines logs, subject-ref trace pairing, support-attachment ownership,
  window-anchored close-outs, cross-resource references, unique-wave account
  derivation): sample status 84.38% → 90.62%, step recall 58.55% → 83.42%,
  field accuracy 47.22% → 73.06%, sequence 6.25% → 37.50%, with 100% step
  precision (no extra steps).
- The current macOS run exercised Apple Vision and selectable-PDF extraction.
  Tesseract is absent on this host; the portable OCR/PDFium fallback is
  unit/mock-tested but not end-to-end verified here.
- The main remaining sample errors are incomplete record discovery/linkage and
  operation/state selection. The investigator's measured sample output was
  byte-identical to the enriched baseline; no sample gain is claimed. Every
  candidate is replayed and verified by deterministic code before reassessment.
- The sample set is small and does not establish expected accuracy on 518
  cases.
- The support-reference M4d trial was later kept under the tuple-based gate;
  the correction and earlier interim revert are explained in the failure
  analysis section above.
- The full agent run had 100% fallback, zero tokens, and no candidate output
  change. A second warm-cache run, per-case budget skips, and three raw sample
  traces were not verified or retained. The 32-case sample is not a blind
  holdout because B cases were inspected during earlier tuning.
- The submission guard passes CSV, pipeline, archive, secret, and hardcoding
  checks but flags 15 pre-existing log-format issues, including unknown or
  unverified model metadata. `log.txt` remains append-only; historic entries
  were not rewritten.
