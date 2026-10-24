# PramaanTrace evaluation report

## Scope and method

The public evaluator contains 32 labeled requests. All scores below compare
predictions with `dataset/sample_output.csv`; hidden labels and organizer-only
files were not used. The evaluation harness reports deletion-status accuracy,
matched step tuples, aligned-field accuracy, and exact ordered-sequence
accuracy. The 32 samples are a weak estimate of behavior on the 518 evaluation
requests. The baseline does not use sample labels or case-specific branches.

The fixed split sorts sample `case_id` values and assigns 1-based odd positions
to A and even positions to B. Fix development used A; B was held out. The only
M4a planner fix adds future verification steps for already-compliant records
and processes in otherwise incomplete cases. It was kept because no B metric
regressed.

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
extra candidate steps; it is not the number of expected fields alone. The final
media-enabled candidate has 92 missing and 20 extra content steps when
comparing step contents without `step_no`. Positional differences include
44 `system_id`, 44 `resource_id`, 37 operation, 35 state, 17 evidence, and 11
phase mismatches; these overlap missing/extra steps.

Media changed two sample predictions and corrected one status. On the full
request set, media-derived evidence was linked to 8 of 518 cases. This is a
measured modest contribution, not evidence that the OCR association heuristics
generalize.

## Failure analysis and custom cases

The eight wrong sample statuses are six expected COMPLETE cases predicted
INCOMPLETE and two expected INCOMPLETE cases predicted COMPLETE. Dominant
step errors are missing findings/verifications and subject-to-resource or
system linkage. Retained-record handling accounts for 29 omitted compliant
state verifications (17 PRESENT, 8 ANONYMIZED, 4 REDACTED) and six omitted
privacy-treatment steps. Among expected sample risks, the candidate found five
of six active flows and one of three restorable backups; each risk it found
has the ordered finding, remediation, and verification. Four expected
replica-cited remaining-record findings were found. The complete ranked
bucket table and anonymized examples are in `NOTES.md`.

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
with zero expected NOT_APPLICABLE cases. The intent classifier authorizes all
32, so non-NOT_APPLICABLE intent is correct on 32/32 and NOT_APPLICABLE
accuracy is untestable at 0/0. The 22 NOT_APPLICABLE outputs among the 518
evaluation requests have no public labels.

## Full-dataset output

The final deterministic baseline validated all 518 requests:

| Status | Cases |
|---|---:|
| COMPLETE | 120 |
| INCOMPLETE | 376 |
| NOT_APPLICABLE | 22 |

The root `output.csv` contains one sorted row per request and passed the output
validator. Warm-cache and cache-disabled full runs both produced SHA-256
`e554553fd4b061b6253b9f3da1f7f2ce8b2a2c251a06650abe62441c1652309f`.
The submission CSV is standalone; it does not require the local OCR cache.

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
