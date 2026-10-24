# PramaanTrace evaluation report

## Evaluation scope

The public evaluator contains 32 cases. Metrics below compare predictions
against `dataset/sample_output.csv`; they do not use hidden labels or organizer
files. The evaluator reports status accuracy, matched step tuples, aligned
field accuracy, and exact ordered-sequence accuracy. The declared operation
sort order and consecutive step numbering passed for every public sample.

The 32-case sample is a weak estimate of behavior on the 518 evaluation
requests. Do not interpret these percentages as a reliable full-dataset
accuracy estimate. The baseline is data-driven and was not tuned with
case-specific branches or hardcoded sample labels.

## Public sample metrics

| Metric | Structured-only baseline | Media-enabled baseline |
|---|---:|---:|
| Case status accuracy | 71.88% (23/32) | 75.00% (24/32) |
| Step-level accuracy | 32.12% (62/193) | 34.20% (66/193) |
| Field-level accuracy | 42.12% (569/1,351) | 44.71% (604/1,351) |
| Exact sequence accuracy | 3.12% (1/32) | 3.12% (1/32) |
| Sample sort contract | PASS | PASS |

Media changed two sample outputs. The measured score gain is modest: one
additional correct status, four additional matched steps, and 35 additional
matching aligned fields; exact-sequence accuracy did not change. Media evidence
was useful, but this result does not establish that the OCR heuristics generalize.

## Full evaluation output

The deterministic media-enabled run processed all 518 requests and validated
the output contract:

| Status | Cases |
|---|---:|
| COMPLETE | 120 |
| INCOMPLETE | 376 |
| NOT_APPLICABLE | 22 |

The root-level `output.csv` has the required header and one sorted row per
request. The validator checked allowed operations/states, exact step keys,
numbering, phase/operation ordering, evidence references, and evidence
timestamps. Two warm-cache full runs produced SHA-256
`cb76153310c39a58d7b8c54996d01e28004489a7e6e29c1c9d306f933b535454`.

## Participant-created custom test cases

These synthetic fixtures are implemented in `code/tests/` and are not copies of
public sample answers:

1. **Historical email lookup:** a request using an older email resolves through
   the audit log and finds a still-present account profile.
2. **Active legal hold:** a policy-required retained record remains present and
   receives an evidence-backed `VERIFY_RECORD_PRESENT` step.
3. **Replica drift:** a complete primary listing omits a profile while a
   read-replica snapshot still contains it; the result is INCOMPLETE.
4. **Retained tombstone with exposed identifiers:** the stable subject
   reference is preserved, but prohibited name/email fields cause an
   `REPORT_EXPOSED_PII` finding and redaction plan.
5. **Missing required retained record:** a later complete listing omits a
   record that remains under active legal hold; the verdict is INCOMPLETE.

The fifth case exposes an output-contract limitation: no allowed finding or
remediation operation describes restoring a missing required retained record.
The implementation reports INCOMPLETE without inventing a new operation.

## Failures found and improvements made

- The first structured-only sample run scored 23/32 on status and missed
  identity-linked media artifacts. Added a local PDF/image reader with a
  per-request cutoff, normalized evidence, and an external SHA-256-keyed cache.
- Plain OCR text order associated a connector with the wrong nearby customer
  row. The media parser now uses Apple Vision bounding-box row alignment and
  declines unsupported/non-adjacent associations.
- Support PDF content was initially interpreted as a support conversation.
  Added generic attachment-context recognition and ownership handling so a
  customer-uploaded attachment follows the attachment rule instead of the
  conversation redaction rule.
- Retained tombstones are checked for prohibited direct identifiers. Missing
  required retained records now force INCOMPLETE when a complete,
  cutoff-visible listing proves absence.
- The sample still has low exact-sequence accuracy. Remaining gaps include
  identity-to-resource linkage when the evidence does not expose a strong join,
  incomplete per-record state reconstruction, and cases whose required
  verification set is broader than the baseline discovers.

## Limitations

- The local media path was verified on macOS using Apple Vision/PDFKit and
  pypdf. A non-macOS run requires Tesseract for image OCR; otherwise the
  pipeline reports eligible files it could not extract.
- OCR and media-to-record association remain heuristic. A normalized media
  record is emitted only for a resource identifier close to an email or stable
  user reference; this can omit evidence whose layout is more complex.
- No investigator LLM was implemented in this milestone. Final output is
  deterministic code output; no LLM gain is claimed.
- 32 public samples are a weak estimate for the 518-case evaluation set.
