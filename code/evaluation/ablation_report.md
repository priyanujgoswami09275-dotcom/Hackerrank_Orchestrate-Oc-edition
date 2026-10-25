# Ablation report

Run date: 2026-10-25. Scores below use the 32 public requests and
`dataset/sample_output.csv`; the full 518-case set has no participant-visible
labels, so no full-dataset accuracy is claimed. All measured candidate CSVs
passed `validate_rows`.

## Metrics and variants

- **Status**: exact deletion-status matches / 32.
- **Tuple steps**: multiset matches ignoring `step_no`; precision is
  matched/predicted and recall is matched/expected.
- **Positional exact steps**: exact seven-field step objects at the same array
  index, including `step_no`, divided by the sum of per-case maximum expected
  and predicted step counts (193 for both measured baseline variants).
- **Fields**: exact fields at aligned positions / aligned fields, as reported by
  the evaluation harness. **Sequence**: exact ordered step arrays / 32.
- A means `PRAMAANTRACE_ENRICH=0` (rule baseline); B means the default enriched
  deterministic rules and linkage. Both used local media extraction and made
  zero model calls.

| Variant | Model calls / tokens | Status | Tuple-step precision / recall | Positional exact steps | Fields | Sequences | Fallback | Gain over rules + linkage |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Rules only (`PRAMAANTRACE_ENRICH=0`) | 0 / 0 | 27/32 (84.38%) | 113/115 (98.26%) / 113/193 (58.55%) | 68/193 (35.23%) | 638/1,351 (47.22%) | 2/32 (6.25%) | N/A | −2 statuses; −48 matched tuples; −54 positional steps; −349 fields; −10 sequences |
| Rules + linkage (`PRAMAANTRACE_ENRICH=1`) | 0 / 0 | 29/32 (90.62%) | 161/161 (100%) / 161/193 (83.42%) | 122/193 (63.21%) | 987/1,351 (73.06%) | 12/32 (37.50%) | N/A | Baseline for agent comparison |
| Rules + agent, verifier/validator off | Not run / not measured | — | — | — | — | — | — | No safe supported mode; bypassing code verification was not justified |
| Rules + agent + verifier + output validator (prior 32-case run) | 97 network calls / 172,870 tokens (148,681 input + 24,189 output); $0 reported | 29/32; byte-identical to rules + linkage | 161/161 / 161/193 | 122/193 | 987/1,351 | 12/32 | 15/32 (46.88%) | No measurable gain; 17 investigations completed, 36 candidates accepted, 0 rejected; 28 retries and 13 failed requests |
| Rules + agent + verifier + output validator (full run) | 1,527 network attempts / 0 input + 0 output tokens; $0 reported | Not scoreable against hidden labels; output byte-identical to baseline | Same public-sample baseline; no new sample score | Same | Same | Same | 509/509 (100%) | No measurable gain; agent output dropped |

The full run reported 509 attempted authorized cases, 0 completed, 509
fallbacks, 1,018 retries, 509 failed requests, 0 cache hits, and 0 accepted or
rejected candidates. The requested model was
`nvidia/nemotron-3.5-super-vl:free` through OpenRouter. The output hash remained
`35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`, exactly
matching `output_baseline.csv`. The agent did not improve the sample or the
full-run output; the submission prediction file remains baseline-only.

## Safeguard ablation

| Safeguard | Result | Decision |
|---|---|---|
| Candidate verifier enabled | In the prior sample agent run, 36 candidates were accepted and none rejected; the final CSV was still byte-identical to baseline. | Keep enabled. It is the boundary that prevents model proposals from becoming unsupported resource links. |
| Candidate verifier disabled | Not run. The full run produced no successful responses/candidates, so there was no meaningful proposal set to compare; bypassing the verifier would weaken safety without an accuracy experiment. | Do not disable. |
| Output contract validator enabled | Baseline and agent CLI outputs pass the validator; the submission guard also re-ran it on all 518 rows. | Keep enabled. |
| Output contract validator disabled | Not run; it is not an optional runtime variant. | Do not disable. |

The prior sample run did not preserve raw per-case traces for three sample
cases. Its aggregate usage is available above. The full-run cache contains 0
responses, so no raw successful full-run traces exist to report. A second
warm-cache full-run hash comparison was not performed; the only measured
full-run hash equals the preserved baseline.

## Custom cases

These are synthetic participant-created fixtures, not copies of public samples.
The named tests passed in the full unit suite.

| Case | Test | Expected behavior |
|---|---|---|
| Historical email | `test_historical_request_email_finds_current_subject_record` | Resolve the old request email through cutoff-visible audit history and find the remaining profile. |
| Retention/legal hold | `test_active_legal_hold_record_is_verified_as_retained` | Preserve the held record and verify `PRESENT`; do not delete it. |
| Replica drift | `test_absent_primary_with_present_replica_is_incomplete` | A complete primary listing does not hide the same subject-linked record still present in a read replica. |
| Sync recreation | `test_sync_recreated_replica_is_gated_by_audit_time` | A replica captured after `audit_at` does not affect the earlier answer; once cutoff-visible it is reported. |
| Instruction-like request | `test_instruction_like_request_text_cannot_override_evidence_or_validation` | Ignore text asking the agent to claim `COMPLETE`; report the evidence-backed remaining record and pass `validate_rows`. |
| Retained-record identifiers (condition c) | `test_retained_tombstone_with_prohibited_identifiers_is_incomplete` | Keep the stable subject reference but report/redact prohibited direct identifiers. |
| Missing retained record (condition d) | `test_missing_required_retained_record_is_incomplete_without_new_operation` | Return `INCOMPLETE` when a complete listing proves the required hold record is missing; do not invent an unsupported operation. |

The existing operation vocabulary has no step to restore a missing required
retained record. That limitation remains explicit rather than being hidden by a
fabricated remediation.
