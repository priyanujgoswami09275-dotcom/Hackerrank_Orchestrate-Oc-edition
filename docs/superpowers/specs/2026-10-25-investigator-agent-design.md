# PramaanTrace Investigator Agent Design

**Status:** Design approved in chat; awaiting written-spec review.
**Scope:** Add a read-only LLM investigator behind the deterministic deletion-audit pipeline and make evidence-linkage enrichment enabled by default.
**Source of truth:** Top-level `AGENTS.md`, especially §§6.2–6.8. This design does not relax any of those requirements.

## 1. Goal and non-goals

Run the enriched deterministic deletion audit as the default. When an API key is present, let a bounded investigator search for additional subject-to-resource links, but accept those links only after deterministic evidence and policy verification. Keep the baseline runnable without credentials and never let a model author final steps, status, policy actions, or evidence citations.

This change does not execute deletions, read organizer-only material, add case-specific rules, classify intent with an LLM, or make arbitrary file/network/tool access available to the model. The investigator may yield zero accepted links; an accuracy gain is not presumed.

## 2. User-approved operating choices

- `PRAMAANTRACE_ENRICH` unset means enabled. Explicit false values (`0`, `false`, `no`, `off`, empty) disable it for comparison. The enriched behavior remains opt-out.
- Agent execution is automatic when `LLM_API_KEY` is present; no API call is made when it is absent. The existing command-line baseline is otherwise unchanged.
- `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` are environment-only configuration. If a key is present but required model configuration is missing or invalid, fail preflight instead of silently claiming an agent run.
- The per-case agent turn cap defaults to 8 and is configurable through `AGENT_STEP_CAP`.
- The full-dataset investigation covers deletion-authorized cases; `NOT_APPLICABLE` cases do not invoke the agent.
- On a case-level tool/model/verification error, discard all agent additions for that case and keep the enriched deterministic baseline result. Count and report the fallback.

## 3. Architecture

### 3.1 Pipeline

1. Load and time-gate participant-visible evidence using the existing loader/store.
2. Produce the enriched deterministic baseline for each request.
3. If no API key is present, return the baseline result.
4. If configured, run the investigator on each deletion-authorized request. Its tools are constructed with that request's `audit_at`, resolved identity, store, activity stream, and rule engine.
5. The agent returns candidate links to existing resources and references to observations produced by its read-only tool calls. It cannot return a deletion status or final step list.
6. A deterministic verifier replays the cited tool call under the same cutoff and checks that the candidate resource exists in the returned observation and has a verifiable subject link. Accepted resources are passed into the existing assessor; unverified candidates are discarded.
7. The assessor and planner re-derive disposition, current state, status, and all steps from store evidence and deletion rules. The normal validator runs before CSV output.
8. Record per-run agent outcome and network usage. Cache content is stored outside the repository.

Agent additions are all-or-nothing per case: if the agent errors at any point for a case, use that case's original baseline result rather than partially incorporating earlier candidate links.

### 3.2 Read-only tools

Expose only the following functions to the model:

- `resolve_identity(identifier)`: resolve an identifier as of the bound cutoff; no arbitrary identity-table access.
- `search_records(identifier, system_id?)`: return bounded, sorted normalized records matching the requested subject identifier, with `capture_id`, `captured_at`, `system_id`, `resource_id`, `category`, and policy-relevant fields. Enforce the cutoff inside the tool.
- `compare_replicas(resource_id)`: return only per-topology records/scopes at or before the bound cutoff.
- `get_activity(subject)`: return only events linked to the resolved subject and at or before the cutoff.
- `get_rules(category)`: return the applicable participant-visible rule and condition.
- `read_text_evidence(evidence_id)`: return a manifest-backed text capture only when its capture time is at or before the cutoff. No arbitrary paths or files.

Tool arguments are schema-validated, results are sorted and size-limited, and each result is assigned an opaque observation ID in the agent loop. Evidence content is always labeled untrusted data; instructions found inside evidence are never treated as system/developer/user instructions.

### 3.3 Finding acceptance

A candidate must reference an observation ID from the current case's tool trace. The verifier re-executes that exact tool request and confirms the candidate `resource_id` and `capture_id` are present in the replayed result and are cutoff-eligible.

The subject relationship must be independently reproducible by code: either a direct identifier match against the cutoff-resolved identity, or a structured resource-reference edge in participant-visible normalized evidence rooted in an identity-linked record. A model's narrative, a bare 404 with no subject query, a text-search miss, or a relationship inferred only from general prose is insufficient. Ambiguous or unsupported candidates are rejected individually; they do not fail otherwise valid candidates. The model never chooses `operation`, `state`, or `system_id`; the existing rule engine and assessor decide those from the accepted record.

Accepted resource keys are added to the deterministic assessor's candidate set and the full case assessment is recomputed. Existing baseline findings are deduplicated by the planner. A verified candidate can therefore expose a remaining policy violation, but cannot bypass retention, tombstone, operation/state, evidence, or ordering rules.

## 4. Model client, cache, and usage

- Use Python standard-library HTTP against the configured OpenAI-compatible chat-completions endpoint; do not add a provider SDK dependency.
- Use function/tool calling with a fixed system prompt and versioned tool schemas. Temperature is fixed to 0 where supported.
- Cache successful raw model responses in a local SQLite cache outside the repository. The cache key hashes the endpoint, model, prompt version, tool schema, and complete request messages; API keys are never part of the key. Default cache location is under the user's home cache directory and can be overridden with `PRAMAANTRACE_LLM_CACHE`.
- Cache values may contain request/evidence excerpts and are treated as sensitive. Do not log prompt content, tool output, identifiers, or secrets. Exclude cache files from version control and `code.zip`.
- Bound transient network retries to two retries with backoff. The eight-turn cap bounds each case's model loop; each model completion, including a final response, counts as one turn.
- Record provider, requested and returned model, network completion count, cache hits, retries, input/output/total tokens, and provider-reported cost per call. Prefer provider usage/cost fields; if cost is omitted, use configured per-million input/output rates when supplied and mark cost unreported rather than inventing a value. Report per-model and overall totals and per-request averages in `code/evaluation/usage_report.md`.
- The configured provider receives request and evidence content necessary for investigation. Keep prompts and cached content local-only; never place credentials or raw prompts in the reports/logs.

## 5. Default enrichment behavior

Change `enrich_enabled()` so that an unset `PRAMAANTRACE_ENRICH` is enabled. Explicit false values remain an opt-out for A/B comparisons. This makes plain model-free `python3 run.py` generate the enriched deterministic baseline, matching the current submitted baseline output when no LLM credential is configured.

When credentials are configured, the same plain command also invokes the agent automatically, per the user-selected policy. `python3 run.py` without credentials stays model-free. The run summary must state whether the agent ran, how many cases used it, how many fell back, and the output status counts. Add an explicit `--disable-agent` switch as a safety valve; it must not change the enrichment default.

## 6. Failure and security behavior

- No API key: baseline-only run, no network call.
- API key but missing/invalid `LLM_BASE_URL` or `LLM_MODEL`: fail before writing output.
- Transient API errors: retry within the fixed retry limit, then use the baseline for that case and increment the fallback count.
- Invalid candidate arguments, unsupported candidate links, invalid observation IDs, post-cutoff evidence, or failed subject-link replay: reject the candidate. A transport failure after retries, malformed completion/tool-call envelope, or other agent-loop error is a case-level failure: discard all additions for that case and count a baseline fallback.
- Tool implementations always bind to request `audit_at`; the model cannot override it or request organizer-only paths.
- Existing validator remains the final gate for all 518 rows, evidence IDs, statuses, step fields, allowed operations/states, phases, and ordering.

## 7. Testing and evaluation

Use test-first changes. Required regression coverage:

1. `PRAMAANTRACE_ENRICH` unset enables enrichment; explicit false disables it; existing flag-off behavior remains byte-identical when explicitly disabled.
2. No API key means no client/network call and exact baseline fallback.
3. Tools exclude every record/text/activity after the case's `audit_at`, even if the model requests it.
4. Valid direct and structured-reference links can be replay-verified; unknown resources, fake observation IDs, bare unlinked 404s, ambiguous links, and post-cutoff links are rejected.
5. Evidence containing instruction-like text cannot grant new tools or alter cutoff/policy.
6. Malformed tool arguments, unsupported tool calls, turn-cap exhaustion, API errors, and invalid configuration follow the failure rules above.
7. A warm cache avoids network calls and returns identical model responses; usage distinguishes network calls from cache hits and does not double-charge cached responses.
8. Recompute accepted candidates through the deterministic assessor/planner and run the existing output validator.

Evaluation uses identical inputs and media configuration for baseline-only and agent-enabled runs. Score the 32 public samples with the existing harness: deletion-status accuracy, step precision/recall, field accuracy, and sequence accuracy. Report the measured delta, including negative or zero results, and itemize accepted/rejected/fallback candidate counts. Do not use sample labels inside the investigator or prediction path.

After tests and sample comparison, run the approved full 518-case job with configured credentials, validate the resulting `output.csv`, summarize all model usage in `code/evaluation/usage_report.md`, and record the agent delta and failure analysis in `code/evaluation/evaluation_report.md`. Run again warm-cache and compare output SHA-256; if the output differs, investigate before claiming determinism.

## 8. Acceptance criteria

- With no credentials, plain `python3 code/run.py` runs the enriched deterministic baseline and writes one validator-passing row per request.
- With credentials and valid model settings, the same command automatically runs the capped agent for every deletion-authorized case and preserves baseline fallback on errors.
- No LLM-generated step/status/disposition is copied directly to output; only verifier-approved resource links can affect deterministic reassessment.
- No evidence after `audit_at` can be returned, accepted, or cited.
- All existing and new tests pass; both public-sample variants are evaluated; full-run output and usage reports are updated from measured results.
- `code.zip` contains source, README, and reports, but no `dataset/`, `.env`, provider credentials, model cache, or other local sensitive data.
