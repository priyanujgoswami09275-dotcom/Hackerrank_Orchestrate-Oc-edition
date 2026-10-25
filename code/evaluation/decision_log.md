# Decision log

Measurements use only the public 32-case sample and participant-facing input
files. The current root `output.csv` is the selected deterministic baseline;
`output_baseline.csv` preserves it separately.

| Change / trial | Measured result | Decision | Why |
|---|---|---|---|
| Rules-only baseline (`PRAMAANTRACE_ENRICH=0`, media on) | 27/32 statuses; 113/115 tuple precision, 113/193 tuple recall; 68/193 exact positional steps; 638/1,351 fields; 2/32 sequences. | Keep as ablation comparator. | It is deterministic and provides the rules-only reference, but linkage omission loses 2 statuses and 48 expected tuples versus the enriched run. |
| Enriched identity/linkage rules (`PRAMAANTRACE_ENRICH=1`, media on) | 29/32 statuses; 161/161 tuple precision, 161/193 tuple recall; 122/193 positional exact steps; 987/1,351 fields; 12/32 sequences. | Keep as final baseline. | It improves every reported sample metric over rules-only. The 32-case result is descriptive, not a blind estimate for 518 cases. |
| Support `customer_reference` as shared support context rather than prohibited direct PII (M4d) | Historical trial: status 24/32 → 27/32, B status 11/16 → 13/16, and B tuple recall 43/100 → 68/100. | Kept under the updated gate: status or tuple steps must improve overall without regressing either on B. | The policy retains shared support context; direct contact fields, not the stable customer reference, determine whether identifiers remain exposed. Earlier field-only keep/revert scoring was superseded by the tuple criterion. |
| Agent with verifier on, public sample (prior session) | CSV byte-identical to enriched baseline; 17 investigations completed, 15 fell back, 36 candidates accepted, 0 rejected; 97 network calls, 28 retries, 13 failed requests, 148,681 input + 24,189 output tokens, $0 reported. | Drop agent-derived predictions. | No status or tuple-step gain; source remains available for audit, but the submission CSV uses the baseline. |
| Agent with verifier and output validator on, full dataset | 518 rows validated; 509 authorized cases attempted, 0 completed, 509 fallbacks; 1,527 network attempts, 1,018 retries, 509 failed requests; 0 cache responses, 0 tokens, $0 reported. Output SHA-256 equals baseline. | Drop agent-derived predictions; no retry. | No measurable gain and 100% fallback. A second warm-cache run was not made because no responses were cached and the first run had no successful calls. |
| Agent/verifier/validator off ablations | Not run. No successful model responses or candidate traces were available; the code has no safe no-verifier mode. | Not run; keep safeguards on. | Disabling checks would weaken policy/evidence guarantees without a meaningful candidate set to measure. |
| Submission guard and malformed-output/adversarial tests | see step 4/5 rows; kept. | Keep guard and tests. Keep log append-only; do not rewrite legacy entries. | The failure is surfaced honestly. Historical `model=unknown`/unverified metadata predates this turn and cannot be repaired without violating the append-only requirement. |
| Single OpenRouter connectivity diagnostic (final session) | HTTP 429 `free-models-per-day`, `X-RateLimit-Remaining: 0`, 0 tokens, key redacted. | Stop agent work; keep baseline-only predictions. | The provider's free-tier daily limit is the root cause of the 509 failed requests; no header/model-ID defect exists to fix, and purchasing credits is out of scope. No retry of the 518-case run. |
| Intent negation patterns for explicit non-deletion phrasing (final session) | Failing test reproduced "…information request, not a request to erase it." authorizing deletion; after the fix, full-set diff: exactly 1 flip (`case_539` → non-deletion), 0 sample flips; sample metrics unchanged (29/32 status, 161/161 precision, 161/193 recall, 987/1,351 fields, 12/32 sequences). | Kept. | The reviewed wording is unambiguous; the fix is general and label-free. Full-set NOT_APPLICABLE is 10, including `case_539` as `NOT_APPLICABLE, []`. |
| Zero-match audit (final session) | 12 of the previous 13 zero-match cases have 0 pre-cutoff identifier hits for all identity values (and 0 at any time, diagnostic-only), no citable links; `case_53`'s `support_1034` is post-cutoff-only, `case_61`'s `object_19` has no stored record; all attributed `data_flow_*` lines name unrelated owners via `correlation_key`. | List the 12 as UNRESOLVED in the reports; no code-only fix is justified. | No participant-visible evidence exists to cite; inventing evidence or post-cutoff citations would violate the contract. |
| Guard opt-out and legacy-log exemptions (final session) | Strict guard fails only the INCOMPLETE-plan check for the 12 unresolved cases (exit 1); with `PRAMAANTRACE_ADMIT_UNRESOLVED_INCOMPLETE=1` it prints `WARN ... UNRESOLVED` for those IDs (never PASS) and exits 0; `code/tools/log_exemptions.txt` documents 14 append-only legacy entries, and the log check passes stating them. | Kept strict-by-default guard with the two narrow opt-outs. | An explicit, default-off admission preserves honesty; the append-only log's historical entries cannot be edited, so a documented, enumerated exemption is the narrow remedy. |
| Final regeneration with intent fix (final session) | Two consecutive full runs: identical SHA-256 `6447f3edd32d631689402866973b9ef05aee39a0d2438682dd202f15b99bd7bd`; 518 rows; COMPLETE=133, INCOMPLETE=375, NOT_APPLICABLE=10; sample-label-removal run byte-identical; validator PASS; 111 tests pass. | Commit as the submitted output. | Deterministic run with investigator disabled; no agent contribution; the hash change from the previous baseline is solely the documented `case_539` flip. |

## Custom-case additions and coverage

The synthetic cases in `code/tests/test_custom_cases.py` cover an old-email
request, an active legal hold, a primary/replica disagreement, sync recreation
across the cutoff, and an instruction-like request asking for a false
`COMPLETE` verdict. The adversarial request still yields an evidence-backed
remaining-record finding and passes `validate_rows`. `test_completion_conditions.py`
covers a tombstone retaining its stable reference while direct identifiers need
redaction (condition c), and a required retained record missing from a complete
listing (condition d). The latter is `INCOMPLETE`; the allowed operation set has
no restoration operation, so no invented step is emitted.

## Unverified items

- The prior sample agent run has aggregate call/token totals but no preserved
  raw per-case traces. The full run has no successful response content, so
  three successful full-run trace excerpts cannot be produced.
- `AGENT_CALL_BUDGET` behavior and per-case budget skips were not measured.
- No verifier-off experiment was run; it would bypass a safety boundary.
- The 32 public cases are a weak estimate for the 518 evaluation requests, and
  split B is not a blind holdout.
