# PramaanTrace evaluation report

## Scope and method

The public evaluator contains 32 labeled requests. All scores below compare
predictions with `dataset/sample_output.csv`; hidden labels and organizer-only
files were not used. The evaluation harness reports deletion-status accuracy,
matched step tuples, aligned-field accuracy, and exact ordered-sequence
accuracy. The 32 samples are a weak estimate of behavior on the 518 evaluation
requests. The baseline does not use sample labels or case-specific branches.

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

## Failure analysis and custom cases

The eight wrong statuses comprise six expected COMPLETE predicted INCOMPLETE
and two expected INCOMPLETE predicted COMPLETE. The causes group into three
missing resource links, three support-message customer-reference
interpretations, one analytics attribution/category issue, and one backup
restore-field mismatch. A support-reference rule trial improved status counts
but lowered field accuracy on B and all samples, so it was reverted.

The 29 expected retained/already-compliant checks comprise 23 unpaired missing
steps and 6 citation-only mismatches. Public samples do not show a required
retained record missing; condition d is synthetic-test-only and unverified
against public labels. Among expected sample risks, the baseline found 5/6
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

The final deterministic baseline validated all 518 requests:

| Status | Cases |
|---|---:|
| COMPLETE | 122 |
| INCOMPLETE | 387 |
| NOT_APPLICABLE | 9 |

The root `output.csv` contains one sorted row per request and passed the output
validator. Its SHA-256 is
`9745eb17e50948658c8531dc173e64e7b8e381faa44b9700749dd9dc5a8d2bf8`.
Two consecutive warm-cache M4c full runs were byte-identical. The earlier
M4b cache-enabled/cache-disabled comparison also matched, but preceded the
intent correction; a cache-disabled run was not repeated afterward. The
submission CSV is standalone and does not require the local OCR cache.

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
- The current macOS run exercised Apple Vision and selectable-PDF extraction.
  Tesseract is absent on this host; the portable OCR/PDFium fallback is
  unit/mock-tested but not end-to-end verified here.
- The main remaining errors are incomplete record discovery/linkage and
  operation/state selection. The investigator LLM milestone has not started;
  no gain is claimed. Any future agent findings must be re-queried and
  validated by deterministic code.
- The sample set is small and does not establish expected accuracy on 518
  cases.
