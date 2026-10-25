# PramaanTrace Investigator Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved read-only investigator with deterministic link verification, enable linkage enrichment by default, run the full evaluation, and update the final output/reports.

**Architecture:** The existing enriched baseline remains authoritative. A standard-library OpenAI-compatible client runs a capped tool loop only when credentials are configured; case-scoped tools enforce `audit_at`. Candidate resource links are replayed and verified in code, then reassessed by the existing policy engine and planner. API/cache failures fall back to the whole enriched baseline result for that case.

**Tech Stack:** Python 3.10+, standard library (`urllib`, `sqlite3`, `hashlib`, `json`), existing `pytest` suite and evaluation harness, OpenAI-compatible chat completions.

**Spec:** `docs/superpowers/specs/2026-10-25-investigator-agent-design.md`

## Global Constraints

- Use only participant-facing data under `dataset/`; never use organizer-only truth, hidden labels, or case-family shortcuts.
- `output.csv` must contain exactly `case_id,deletion_status,steps_json`, with one row per request sorted by `case_id`.
- Allowed statuses are `COMPLETE`, `INCOMPLETE`, and `NOT_APPLICABLE`; a non-deletion request has `NOT_APPLICABLE` and `[]`.
- Every step has exactly `step_no,phase,system_id,resource_id,operation,state,evidence_id`; steps are ordered FINDING, REMEDIATION, VERIFICATION and use only allowed operation/state pairs.
- Never read, use, or cite evidence captured after the case's `audit_at`; tools enforce this inside the data access layer.
- LLM output may only suggest candidate links; deterministic code decides subject linkage, policy, state, status, and steps.
- `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` come from environment variables only. Optional cost rates are `LLM_INPUT_COST_PER_1M` and `LLM_OUTPUT_COST_PER_1M`. Never log or package credentials, prompts, raw tool output, or the cache.
- Agent cap defaults to 8 model completions per deletion-authorized case; no API key means no network calls and enriched-baseline output.
- The response cache is stored outside the repository and excluded from `code.zip`.
- Final artifacts include root `output.csv`, `code/evaluation/evaluation_report.md`, and `code/evaluation/usage_report.md`; the archive excludes `dataset/`, `.env`, and caches.

## Review Focus

- **Cutoff boundary:** a record/text/activity at `audit_at` is included; one after it is excluded. Pin this in tool tests.
- **Cross-subject or ambiguous links:** matching another user's identifier or multiple subjects must not add resources. Pin this in identity-tool and verifier tests.
- **Prompt injection in evidence:** instruction-like evidence cannot change tools, cutoff, or policy. Pin this in an investigator-loop test.
- **API failure and malformed responses:** bounded retries and per-case all-or-nothing baseline fallback must be visible in summaries. Pin this in client/pipeline tests.
- **Cache accounting:** a cache hit must avoid a network request and must not count cached usage/cost twice. Pin this in client/usage tests.

---

### Task 1: Make evidence-linkage enrichment the default

**Files:**
- Modify: `code/pramaantrace/loader.py:258-268`
- Test: `code/tests/test_enrichment_default.py`

**Interfaces:**
- `enrich_enabled() -> bool` returns `True` when `PRAMAANTRACE_ENRICH` is unset; explicit false-like values (`0`, `false`, `no`, `off`, empty) return `False`; explicit true-like values (`1`, `true`, `yes`) return `True`.

- [ ] **Step 1: Write the failing test** for unset, explicit false, and explicit true environment values using pytest `monkeypatch`.
- [ ] **Step 2: Run `python3 -m pytest code/tests/test_enrichment_default.py -q`** and confirm the unset-value assertion fails against the current default-off implementation.
- [ ] **Step 3: Implement the unset-versus-empty distinction** in `enrich_enabled()` without changing explicit true/false parsing.
- [ ] **Step 4: Run the targeted test, then `python3 -m pytest code/tests -q`**; all tests must pass.
- [ ] **Step 5: Run `python3 code/evaluate.py` with the variable unset and `PRAMAANTRACE_ENRICH=0 python3 code/evaluate.py`.** Confirm unset matches the enriched result (status 29/32, missing 32, extra 0) and explicit false matches the preserved baseline (status 27/32, missing 80, extra 2).
- [ ] **Step 6: Commit** as `fix(config): default evidence linkage enrichment on`.

### Task 2: Add model configuration, OpenAI-compatible client, response cache, and usage ledger

**Files:**
- Create: `code/pramaantrace/agent/__init__.py`
- Create: `code/pramaantrace/agent/config.py`
- Create: `code/pramaantrace/agent/client.py`
- Create: `code/pramaantrace/agent/cache.py`
- Create: `code/pramaantrace/agent/usage.py`
- Test: `code/tests/test_agent_client.py`

**Interfaces:**
- `AgentConfig.from_env(env: Mapping[str, str]) -> AgentConfig | None`: `None` when `LLM_API_KEY` is absent; when present, require valid `LLM_BASE_URL` and `LLM_MODEL`; parse `AGENT_STEP_CAP` as an integer in `1..64`, default `8`; accept optional `LLM_INPUT_COST_PER_1M` and `LLM_OUTPUT_COST_PER_1M` rates for cost fallback.
- `ChatCompletion`: immutable response with `message`, `finish_reason`, `actual_model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, and `cost_usd | None`.
- `OpenAICompatibleClient.complete(messages, tools, response_format=None) -> ChatCompletion`: POST JSON to `<LLM_BASE_URL>/chat/completions` with the configured model, temperature 0, bounded timeout, and two retries for transient errors.
- `ResponseCache.get(key: str) -> dict | None` and `ResponseCache.put(key: str, response: dict) -> None`; cache key includes endpoint, model, prompt version, tools, and messages, never the API key.
- `cache_key(endpoint: str, model: str, prompt_version: str, tools: list[dict], messages: list[dict]) -> str` returns a deterministic SHA-256 key over canonical JSON.
- `UsageLedger.record(completion, *, cache_hit: bool) -> None` and `UsageLedger.summary() -> dict`: network calls, cache hits, retries, tokens, and cost grouped by provider/model and overall.

- [ ] **Step 1: Write failing tests** for no-key configuration, incomplete-key configuration, cap parsing, cache key stability, cache-hit behavior, usage accounting, and an OpenAI-compatible HTTP success/error exchange against a local test HTTP server.
- [ ] **Step 2: Run `python3 -m pytest code/tests/test_agent_client.py -q`** and confirm failures identify the missing config/client/cache interfaces.
- [ ] **Step 3: Implement the config, SQLite cache, client, and ledger** using only the standard library; do not print request or credential data.
- [ ] **Step 4: Run the targeted tests**; confirm a cache hit causes no second HTTP request and usage/cost is recorded once.
- [ ] **Step 5: Run `python3 -m pytest code/tests -q`**; preserve the existing suite.
- [ ] **Step 6: Commit** as `feat(agent): add cached OpenAI-compatible client and usage ledger`.

### Task 3: Implement case-scoped temporal investigation tools

**Files:**
- Create: `code/pramaantrace/agent/tools.py`
- Test: `code/tests/test_agent_tools.py`
- Use: `code/pramaantrace/store.py`, `identity.py`, `rules.py`, `loader.py`

**Interfaces:**
- `CaseToolbox(request, identity, store, activities, rule_engine, manifest)` binds every operation to `request["audit_at"]` and the single resolved subject.
- `CaseToolbox.schemas() -> list[dict]` returns schemas for `resolve_identity`, `search_records`, `compare_replicas`, `get_activity`, `get_rules`, and `read_text_evidence`.
- `CaseToolbox.dispatch(name: str, arguments: Mapping[str, Any]) -> dict` validates arguments, returns bounded/sorted JSON-safe data, and rejects unknown tools.
- `ToolObservation` stores `observation_id`, tool name, exact arguments, and result; IDs are deterministic within one case (`obs_0001`, ...).

- [ ] **Step 1: Write failing tests** proving at-cutoff records/text/activity are returned, post-cutoff items are excluded, unknown evidence IDs and arbitrary paths are rejected, and cross-subject identity resolution returns no data.
- [ ] **Step 2: Run `python3 -m pytest code/tests/test_agent_tools.py -q`** and confirm failures occur because `CaseToolbox` is absent.
- [ ] **Step 3: Implement the six read-only tools** with a maximum of 25 returned records/events per call and evidence IDs/capture times on each returned item.
- [ ] **Step 4: Add the cutoff-boundary regression case** (`captured_at == audit_at` included; `captured_at > audit_at` excluded) and run the targeted tests.
- [ ] **Step 5: Run `python3 -m pytest code/tests -q`**.
- [ ] **Step 6: Commit** as `feat(agent): add cutoff-bound case investigation tools`.

### Task 4: Implement the bounded investigator loop and prompt

**Files:**
- Create: `code/pramaantrace/agent/loop.py`
- Create: `code/prompts/investigator_system.txt`
- Test: `code/tests/test_agent_loop.py`
- Use: Tasks 2 and 3 interfaces.

**Interfaces:**
- `CandidateLink(resource_id: str, capture_id: str, observation_id: str)` is the only model-produced prediction structure.
- `InvestigationResult(candidates: tuple[CandidateLink, ...], observations: tuple[ToolObservation, ...], turns: int)` stores the case-local trace.
- `Investigator(client, step_cap: int).investigate(request, toolbox) -> InvestigationResult` dispatches only declared read-only tool calls, counts each completion toward the cap, and parses the final response as schema-validated JSON `{"candidates": [...]}`.

- [ ] **Step 1: Write failing tests** for valid tool-call/observation/final-candidate flow, turn-cap exhaustion, malformed final JSON, unknown tool rejection, invalid arguments, and instruction-like text in a text observation.
- [ ] **Step 2: Run `python3 -m pytest code/tests/test_agent_loop.py -q`** and confirm the expected missing-interface failures.
- [ ] **Step 3: Implement the versioned system prompt and loop**; label evidence as untrusted, include only request context needed for investigation, and make no final-step/status fields part of the response schema.
- [ ] **Step 4: Run the targeted tests**; confirm tool output is appended as data and cannot alter the fixed tool registry or cutoff.
- [ ] **Step 5: Run `python3 -m pytest code/tests -q`**.
- [ ] **Step 6: Commit** as `feat(agent): add bounded read-only investigator loop`.

### Task 5: Verify candidate links and reassess with the deterministic planner

**Files:**
- Create: `code/pramaantrace/agent/verifier.py`
- Create: `code/pramaantrace/agent/pipeline.py`
- Modify: `code/pramaantrace/baseline.py:436-526,840-857`
- Test: `code/tests/test_agent_verifier.py`
- Test: `code/tests/test_agent_pipeline.py`
- Use: Tasks 2–4 interfaces.

**Interfaces:**
- `verify_candidate_links(request, identity, candidates, observations, toolbox, store) -> tuple[tuple[str, str, str], ...]` replays each candidate's exact observation request and returns only verified `(system_id, resource_id, category)` keys.
- Link proof is either an exact direct identifier match against the cutoff-resolved identity or a structured reference edge rooted in a directly linked record; a narrative claim or bare unlinked 404 is not proof.
- Extend `assess_case(..., *, additional_resource_keys: Iterable[tuple[str, str, str]] = ())` to assess only verifier-supplied additional keys through the existing state/rule/step path.
- `run_agent_pipeline(bundle, investigator) -> AgentRunResult` runs the existing baseline per request, skips the agent for NOT_APPLICABLE, reruns assessment with accepted keys, and discards all additions for a case on an agent-loop error. `AgentRunResult` contains `rows`, `attempted_cases`, `completed_cases`, `fallback_cases`, `accepted_candidates`, `rejected_candidates`, and `usage_summary`.

- [ ] **Step 1: Write failing tests** for a supported direct link, a supported structured edge, a fake observation ID, a cross-subject edge, an ambiguous edge, a bare unlinked 404, a post-cutoff observation, and all-or-nothing fallback after an agent error.
- [ ] **Step 2: Run the targeted verifier/pipeline tests** and confirm they fail because the verifier and pipeline do not exist.
- [ ] **Step 3: Implement deterministic replay verification**; the candidate's capture/resource must appear in the replayed result and link proof must be independently established from normalized evidence.
- [ ] **Step 4: Add `additional_resource_keys` to `assess_case()`** and recompute complete plans through the existing rule engine and planner; never copy model operations, states, status, or evidence IDs.
- [ ] **Step 5: Implement the per-case pipeline** and verify a runtime failure returns exactly that case's original baseline result.
- [ ] **Step 6: Run targeted tests and `python3 -m pytest code/tests -q`**; validate all generated fixture rows with `validate_rows`.
- [ ] **Step 7: Commit** as `feat(agent): verify candidate links before deterministic reassessment`.

### Task 6: Wire automatic credential detection into the CLI and document operation

**Files:**
- Modify: `code/run.py:22-95`
- Modify: `code/README.md:1-133`
- Test: `code/tests/test_agent_cli.py`
- Use: Tasks 1–5 interfaces.

**Interfaces:**
- No `LLM_API_KEY`: invoke the enriched deterministic baseline with no network request.
- Configured key plus complete settings: construct client/cache/ledger/investigator and invoke `run_agent_pipeline` automatically.
- `--disable-agent`: force baseline-only output even when credentials exist; it does not disable enrichment.
- CLI summary prints agent enabled/disabled, deletion-authorized cases attempted, completed cases, fallbacks, accepted/rejected candidate counts, and status counts; never prints secrets or evidence content.

- [ ] **Step 1: Write failing CLI tests** for no-key/no-network baseline, configured auto-agent invocation, `--disable-agent`, and incomplete config failing before output is written.
- [ ] **Step 2: Run `python3 -m pytest code/tests/test_agent_cli.py -q`** and confirm the new behavior fails.
- [ ] **Step 3: Wire configuration and pipeline into `run.py`** while retaining existing output validation and writer behavior.
- [ ] **Step 4: Update README** with default enrichment behavior, automatic agent behavior when environment credentials are configured, required env vars, `--disable-agent`, cache location/privacy, and the command to source the uncommitted `.env` manually where applicable.
- [ ] **Step 5: Run CLI tests and `python3 -m pytest code/tests -q`**; confirm no credential or prompt content appears in captured output.
- [ ] **Step 6: Run `python3 code/run.py` without credentials** and confirm enriched baseline validation and status counts.
- [ ] **Step 7: Commit** as `feat(cli): auto-run investigator when configured`.

### Task 7: Evaluate sample/full runs, update reports, and package

**Files:**
- Modify: `code/evaluation/evaluation_report.md`
- Modify: `code/evaluation/usage_report.md`
- Modify: `code/README.md` if run instructions need final measured details
- Generate: root `output.csv`
- Generate: root `code.zip`
- Use: `code/evaluation/harness.py`, `code/evaluation/failure_analysis.py`, `code/package_submission.py`

- [ ] **Step 1: Generate 32-case baseline-only and agent-enabled predictions** with identical media inputs, using the existing `sample_deletion_requests.csv`; keep all predictions outside the model context.
- [ ] **Step 2: Run `python3 code/evaluation/harness.py <baseline-samples.csv>` and the same command for agent samples.** Record status accuracy, step precision/recall, field accuracy, sequence accuracy, and per-case differences; do not claim improvement unless measured.
- [ ] **Step 3: Run `python3 code/evaluation/failure_analysis.py <agent-samples.csv>`** and reconcile accepted, rejected, fallback, missing, and extra steps with the report.
- [ ] **Step 4: With configured environment credentials, run the full 518-case command** and require `validate_rows`/CLI validation to pass; check status totals sum to 518.
- [ ] **Step 5: Run the same full command warm-cache** and compare SHA-256 hashes of both outputs; investigate any difference before proceeding.
- [ ] **Step 6: Update evaluation and usage reports** from measured results: baseline/agent sample deltas, participant-created tests, limitations, provider/model, network calls, cache hits, retries, input/output/total tokens, averages, actual or estimated costs, fallback/error counts, and final output hash.
- [ ] **Step 7: Run `python3 -m pytest code/tests -q`, the source-literal scan, output validation, and `python3 code/package_submission.py`**; inspect archive contents for dataset, `.env`, cache, nested archive, or credentials.
- [ ] **Step 8: Commit** the final validated `output.csv`, reports, and README only after every verification passes. Keep the generated `code.zip` as a local submission artifact; it is intentionally ignored by git.

## Execution Notes

- All implementation and API calls remain gated on review of this plan and explicit confirmation to execute it inline.
- Use the already configured environment values without printing them. The full LLM run is authorized, but do not create or log any credential material.
- If the provider omits cost in a completion, calculate it from configured per-million rates when available; otherwise state that cost was not reported rather than fabricating a number.
- The sample set has only 32 labels. Report zero or negative LLM gain honestly; accepted candidate links must remain evidence-backed even if this means the agent changes no output rows.
