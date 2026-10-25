# PramaanTrace model and usage report

## Full-dataset run that produced the candidate output

The 518-case candidate run used the optional investigator through OpenRouter.
Every model request failed and every authorized case fell back to the
deterministic baseline. The resulting CSV validated and is byte-identical to
the separately preserved baseline; no agent-derived steps were selected. A
final-session follow-up diagnostic confirmed the root cause: OpenRouter's
free-models-per-day rate limit (HTTP 429, `X-RateLimit-Remaining: 0`).

| Provider / model | Network attempts | Retries | Failed requests | Input tokens | Output tokens | Total tokens | Reported total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenRouter / `nvidia/nemotron-3.5-super-vl:free` | 1,527 | 1,018 | 509 | 0 | 0 | 0 | $0.00000000 |
| **Overall** | **1,527** | **1,018** | **509** | **0** | **0** | **0** | **$0.00000000** |

- Authorized cases attempted: 509 of 518; 0 investigations completed; 509
  baseline fallbacks (100%); 0 accepted candidates and 0 rejected candidates.
- Cache hits/responses: 0 / 0.
- Average per network attempt: 0 input tokens, 0 output tokens, 0 total tokens,
  and $0.00000000 reported cost.
- Average per audited request (518): 0 input tokens, 0 output tokens, 0 total
  tokens, and $0.00000000 reported cost.
- Cost is the provider-reported value in the run summary; failed requests had
  no reported token usage. Retries are included in the 1,527 network attempts.
- Candidate output SHA-256:
  `35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`.
  It exactly matches `output_baseline.csv`.

## Prior public-sample agent run (reported separately)

The earlier 32-case agent run also produced a byte-identical CSV to the enriched
deterministic baseline. It recorded 97 network calls, 28 retries, 13 failed
requests, 148,681 input tokens, 24,189 output tokens (172,870 total), and $0.00
reported cost. 17 investigations completed, 15 fell back, 36 candidate links
were accepted, and 0 were rejected. These sample-run usage values are not added
to the full-dataset totals above.

## Final-session diagnostic (reported separately)

| Provider / model | Calls | Succeeded | Input tokens | Output tokens | Reported cost |
|---|---:|---:|---:|---:|---:|
| OpenRouter / `nvidia/nemotron-3.5-super-vl:free` | 1 | 0 (HTTP 429, free-models-per-day) | 0 | 0 | $0.00000000 |

The single diagnostic call used the environment-configured key (never printed)
and returned the provider's free-tier daily-limit error with
`X-RateLimit-Remaining: 0`. No tool call was attempted and no agent run was
started on the 518-case set in the final session. All prediction output
therefore remains the deterministic baseline; there is no measurable agent
gain, and the provider's rate limit is documented as the reason the
investigator made no successful calls at any point.

## Caveats

- No second warm-cache full run exists; the full-run cache had no responses
  to reuse.
- Raw traces for three sample cases were never captured (the provider
  returned no successful completion in any run).
- `AGENT_CALL_BUDGET` skips were not observable because no call succeeded.
- The coding-assistant models/tools recorded in `log.txt` are not counted as
  prediction-pipeline usage here.
- No credentials, API keys, or sensitive configuration values are included.
