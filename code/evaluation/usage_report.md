# PramaanTrace model and usage report

## Final full-dataset run that produced the submitted output

The run that produced the submitted `output.csv` ran the deterministic
pipeline with the investigator disabled: no `LLM_API_KEY` was configured in
its environment, so it made **0 model calls**, consumed **0 tokens**, and had
**$0.00** model cost. The intent-negation correction from the final session is
included in this run.

| Provider / model | Network attempts | Retries | Failed requests | Input tokens | Output tokens | Total tokens | Reported total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| none (investigator disabled; deterministic pipeline only) | 0 | 0 | 0 | 0 | 0 | 0 | $0.00000000 |
| **Overall** | **0** | **0** | **0** | **0** | **0** | **0** | **$0.00000000** |

- Authorized cases attempted by the agent: 0 of 509; 0 investigations; 0
  fallbacks needed; the agent contributed no rows.
- Two consecutive runs produced byte-identical output (SHA-256
  `6447f3edd32d631689402866973b9ef05aee39a0d2438682dd202f15b99bd7bd`), and a
  leakage re-check with `dataset/sample_output.csv` removed reproduced the
  same bytes.
- Average tokens per request and per network attempt: 0.

## Prior 518-case agent run (historical; superseded)

An earlier 518-case run with the investigator enabled attempted 509
deletion-authorized cases and made 0 successful model calls: every attempt
failed and all 509 cases fell back to the deterministic baseline. A
final-session single connectivity diagnostic identified the root cause:
OpenRouter's free-models-per-day rate limit (HTTP 429,
`X-RateLimit-Remaining: 0`); the key was never printed.

| Provider / model | Network attempts | Retries | Failed requests | Input tokens | Output tokens | Total tokens | Reported total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenRouter / `nvidia/nemotron-3.5-super-vl:free` | 1,527 | 1,018 | 509 | 0 | 0 | 0 | $0.00000000 |

- Authorized cases attempted: 509 of 518; 0 investigations completed; 509
  baseline fallbacks (100%); 0 accepted candidates and 0 rejected candidates.
- Cache hits/responses: 0 / 0 (nothing to reuse for a warm-cache run).
- Its output was byte-identical to the then-current baseline and had no agent
  contribution; it was superseded by the final run above after the intent
  correction.
- Cost is the provider-reported value in the run summary; failed requests had
  no reported token usage. Retries are included in the 1,527 network attempts.

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
- Several AI coding tools and models worked on this repository across sessions
  (the append-only `log.txt` records harness/model lines, including early
  entries with `model=unknown` placeholders from before the convention was
  fixed). Those coding-assistant calls are development tooling, not
  prediction-pipeline usage, and are not counted in the totals above.
- No credentials, API keys, or sensitive configuration values are included.
