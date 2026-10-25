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
and $0 reported. **No measurable gain: the prediction file is baseline-only.**

## Remaining failures and unverified items

Three public COMPLETE labels remain predicted INCOMPLETE where no cutoff-visible
evidence safely links the expected resource; the enriched sample diff has 32
missing tuples and no extras. The operation vocabulary cannot describe
restoring a missing retention-required record, so the system returns INCOMPLETE
without inventing a step. Full-set accuracy cannot be calculated without labels.
The 32-case sample is small; raw successful model traces, budget skips,
`AGENT_CALL_BUDGET`, a second warm-cache run, and an end-to-end Tesseract fallback
remain unverified. The submission guard also flags 15 legacy log-format issues;
the transcript is append-only and those entries were not rewritten.

## AI tools and model attribution

`log.txt` records both OpenCode and Codex tool labels and model strings including
Claude Opus 4.8, GLM-5.3 / GLM-5.3-flash-free, MiniMax M3.1 Flash, and OpenAI
GPT-6 Luna. Some older entries explicitly say `unknown` or `unverified`, so
those turns cannot be attributed more precisely; one discrepancy entry mentions
`xkiro/qwen3.8-max:free` as unverified, not as confirmed use. The prediction
model requested for the full run was `nvidia/nemotron-3.5-super-vl:free` through
OpenRouter; its requests failed and produced no usable responses. No credentials
are recorded.
