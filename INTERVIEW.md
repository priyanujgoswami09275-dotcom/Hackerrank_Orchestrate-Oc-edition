# Interview cheat sheet — Ghost Data Still Exists

## Architecture and decision authority

The pipeline reconstructs identity from the current snapshot plus cutoff-visible
identity history, loads participant-visible SQL/JSON/text/media evidence into a
normalized store, and applies policy rules to the evidence state at `audit_at`.
The deterministic planner emits findings, ordered remediation, and verification
steps; `validate_rows` checks the output contract before serialization. An
optional LLM investigator can suggest resource links only. Deterministic code
replays its tool observations, checks identity or an evidence-backed resource
reference, reassesses policy, and retains the baseline on any failure. The model
never chooses final status or steps.

## Temporal and replica safeguards

`RecordStore.query`, `read_text`, and `query_scopes` all require `audit_at` and
exclude later captures. Media paths are not opened unless their manifest time is
eligible. Case-scoped tools carry the same cutoff, and candidate verification
replays them through the gated store. Replica snapshots retain topology and
capture time: a complete primary listing does not make a still-present
read-replica record absent. A sync recreation affects the answer only once its
capture/event is cutoff-visible. Synthetic tests cover both replica drift and
sync timing.

## Measured result and agent decision

On 32 public cases, rules plus linkage scored 29/32 statuses, 161/161 tuple-step
precision, 161/193 tuple recall, 122/193 positional exact steps, 987/1,351
fields, and 12/32 sequences. This is a weak estimate for 518; split B is not a
blind holdout. The prior sample agent CSV was byte-identical to baseline. The
full OpenRouter run with `nvidia/nemotron-3.5-super-vl:free` made 1,527 network
attempts; all 509 authorized cases fell back, with zero tokens/cached responses
and $0 reported. A final-session single connectivity diagnostic reproduced the
cause: HTTP 429 "free-models-per-day" with `X-RateLimit-Remaining: 0`, so the
investigator never completed one successful call at any point. The run that
produced the submitted output made 0 model calls.
**No measurable gain: the prediction file is baseline-only.**

## Remaining failures and unverified items

Three public COMPLETE labels remain predicted INCOMPLETE where no cutoff-visible
evidence safely links the expected resource; the enriched sample diff has 32
missing tuples and no extras. On the full set, 12 deletion-authorized cases
(`case_264`, `case_265`, `case_267`, `case_271`, `case_272`, `case_416`,
`case_417`, `case_517`, `case_519`, `case_521`, `case_53`, `case_61`) are
UNRESOLVED: every resolved identifier returns 0 hits before the cutoff (and, as
a diagnostic-only check, 0 hits at any time), the two activity-linked leads are
post-cutoff-only (`support_1034` for case_53) or have no stored record at all
(`object_19` for case_61), and every attributed `data_flow_*` line names an
unrelated owner via its explicit `correlation_key`. A 13th zero-match case,
`case_539`, was an intent-classifier bug ("This is an information request, not
a request to erase it."): fixed with general negation patterns, exactly 1 flip
of 518 texts, now `NOT_APPLICABLE, []`. The operation vocabulary cannot describe
restoring a missing retention-required record, so the system returns INCOMPLETE
without inventing a step. Full-set accuracy cannot be calculated without labels.
The 32-case sample is small; raw successful model traces, budget skips,
`AGENT_CALL_BUDGET`, a second warm-cache run, and an end-to-end Tesseract
fallback remain unverified. The submission guard is strict by default, passes
the artifact checks with documented legacy-log exemptions
(`code/tools/log_exemptions.txt`, 14 append-only entries), and exposes an
explicit env opt-out (`PRAMAANTRACE_ADMIT_UNRESOLVED_INCOMPLETE=1`, default
OFF) that prints the unresolved case IDs as `WARN ... UNRESOLVED` — never PASS;
strict mode reports them as FAIL.

## AI tools and model attribution

`log.txt` records both OpenCode and Codex tool labels and model strings including
Claude Opus 4.8, GLM-5.3 / GLM-5.3-flash-free, MiniMax M3.1 Flash, and OpenAI
GPT-6 Luna. Some older entries explicitly say `unknown` or `unverified`, so
those turns cannot be attributed more precisely; one discrepancy entry mentions
`xkiro/qwen3.8-max:free` as unverified, not as confirmed use. The prediction
model requested for the full run was `nvidia/nemotron-3.5-super-vl:free` through
OpenRouter; its requests failed and produced no usable responses. The final
session ran in OpenCode as `glm-5.3-flash-free`. No credentials are recorded.
