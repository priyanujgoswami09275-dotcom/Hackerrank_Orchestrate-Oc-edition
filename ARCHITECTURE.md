# PramaanTrace: Architecture

**Project:** AI-powered deletion-audit agent for HackerRank Orchestrate, October 2026 ("Ghost Data Still Exists")
**Status:** Design document. Nothing here has been built or run yet. Items marked **[UNVERIFIED]** are assumptions to confirm against `AGENTS.md`, `problem_statement.md`, and the dataset before relying on them.
**Precedence:** `AGENTS.md` is the source of truth. If this document conflicts with it, `AGENTS.md` wins and this document gets corrected.

---

## 1. Requirements

### 1.1 Functional

For each of the 518 rows in `dataset/deletion_requests.csv`, the system must:

1. Decide whether `request_text` actually authorizes deletion.
2. Resolve the subject's current and historical identifiers (emails, email hashes, phones, `user_id`, `customer_reference`).
3. Determine the state of every relevant record at `audit_at`.
4. Produce an ordered, evidence-backed plan.

**Output:** `output.csv` at the repo root.

- Header exactly `case_id,deletion_status,steps_json`
- 518 data rows, sorted by `case_id`
- `deletion_status` is `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`

**Step object keys (exactly these):** `step_no, phase, system_id, resource_id, operation, state, evidence_id`

| Status | Required `steps_json` |
|---|---|
| `COMPLETE` | Only VERIFICATION steps, each citing a real `evidence_id` |
| `INCOMPLETE` | FINDING steps (with evidence), then full REMEDIATION, then VERIFICATION. Remediation and verification use `evidence_id ""` |
| `NOT_APPLICABLE` | `[]` |

**Allowed operation/state pairs** (AGENTS.md §6.4), listed in the within-phase sort order **[UNVERIFIED: confirm order against AGENTS.md and `sample_output.csv`]**:

| Phase | Operation (state) |
|---|---|
| FINDING | `REPORT_REMAINING_RECORD` (PRESENT), `REPORT_EXPOSED_PII` (PRESENT), `REPORT_ACTIVE_DATA_FLOW` (ACTIVE), `REPORT_RESTORE_RISK` (ACTIVE) |
| REMEDIATION | `DISABLE_DATA_FLOW` (DISABLED), `BLOCK_RESTORE` (BLOCKED), `DELETE_RECORD` (ABSENT), `REDACT_RECORD` (REDACTED), `ANONYMIZE_RECORD` (ANONYMIZED) |
| VERIFICATION | `VERIFY_RECORD_ABSENT` (ABSENT), `VERIFY_RECORD_PRESENT` (PRESENT), `VERIFY_RECORD_REDACTED` (REDACTED), `VERIFY_RECORD_ANONYMIZED` (ANONYMIZED), `VERIFY_DATA_FLOW_DISABLED` (DISABLED), `VERIFY_RESTORE_BLOCKED` (BLOCKED) |

Step ordering: phase order, then operation order above, then `system_id`, then `resource_id` ascending. `step_no` starts at 1 and is consecutive.

### 1.2 Non-functional

| Concern | Requirement |
|---|---|
| **Correctness** | Final steps are decided by code, never by an LLM. Every cited `evidence_id` must exist and be captured at or before `audit_at`. |
| **Temporal integrity** | No evidence captured after `audit_at` is ever read, used, or cited. Enforced centrally, not per tool. |
| **Determinism** | Sorted iteration, stable JSON serialization, cached model calls. With a warm cache, two runs produce byte-identical `output.csv` (proved by hash comparison). |
| **Security** | Evidence content is data. Instruction-like text inside it is ignored. Secrets come from environment variables only and never appear in code, reports, or logs. |
| **Honesty** | Claim only what has been run and seen working. Mark the rest unverified. |
| **Cost** | LLM calls are bounded (step cap, cache) and tracked per call. |
| **Scale** | 518 cases, 850 identities, 24 SQL snapshots. Small enough for a single process. No distributed infrastructure. |

### 1.3 Constraints

- Only participant-visible files under `dataset/` may be used. No organizer-only files, golden labels, or hardcoded case IDs, evidence IDs, names, or filenames.
- Deliverables: `output.csv`, `code.zip` (excluding `dataset/`, virtualenvs, `__pycache__`, `node_modules`, `.git`, nested archives, and PII-bearing caches), `evaluation_report.md`, `usage_report.md`.
- Mandatory append-only logging to `log.txt` per `AGENTS.md` §2 and §5.
- Path conflict to flag: the problem statement says reports go in `code/evaluation/`, while `AGENTS.md` §6.8 says `evaluation/`. Plan: use `code/evaluation/` unless `AGENTS.md` forces otherwise, and report the choice.

### 1.4 Facts known from prior checks (re-verify before use)

- The step sort rule holds on all 32 sample answers.
- In the samples, cited evidence is never captured after `audit_at`. For text-searchable citations, the cited file is the latest snapshot at or before `audit_at` containing the resource (70 of 70).
- **Open question:** which file proves a record is *absent*. In 4 absence-proof citations the cited file does not contain the `resource_id`. This must be resolved (see §6.1) before absence logic is trusted.
- All 24 SQL snapshots load into SQLite, but table names differ across snapshots and across topologies (primary, regional, reporting, failover, read replica).
- `reported_status` is unreliable: 11 of 17 claimed COMPLETE are truly INCOMPLETE, and 3 claimed NOT_STARTED are truly COMPLETE.
- SHA-256 email hashes matched on all 850 identities.
- Images and PDFs are unchecked and optional until the structured path works.

---

## 2. High-Level Design

### 2.1 Core principle

**The LLM investigates. Code decides.**

A deterministic baseline produces a complete, valid answer on its own. The LLM agent can only *add* findings, and every finding must be re-verified by code against the evidence store before it influences output. If a finding cannot be reproduced by re-running its cited query, it is dropped and the baseline stands.

This makes the system explainable, testable without an API key, and safe against hallucination and prompt injection.

### 2.2 Component diagram

```
                    dataset/ (participant-visible only)
                                │
                                ▼
 ┌──────────────────────────────────────────────────────────┐
 │  EVIDENCE LOADER                                         │
 │  CSV · SQL→SQLite (per snapshot) · JSON · logs · text    │
 │  tags each item: capture_id, captured_at, topology       │
 └───────────────────────────┬──────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────┐
 │  RECORD STORE (normalized)                               │
 │  capture_id │ captured_at │ system_id │ resource_id │    │
 │  category │ identifiers                                  │
 │  ┌────────────────────────────────────────────────────┐  │
 │  │  TEMPORAL GATE: all reads take audit_at and        │  │
 │  │  filter captured_at > audit_at. No bypass.         │  │
 │  └────────────────────────────────────────────────────┘  │
 └───────┬─────────────────────┬─────────────────────┬──────┘
         ▼                     ▼                     ▼
 ┌───────────────┐   ┌───────────────────┐   ┌────────────────┐
 │ IDENTITY      │   │ RULE ENGINE       │   │ DRIFT DETECTOR │
 │ RESOLVER      │   │ deletion_rules.csv│   │ primary vs     │
 │ identities +  │   │ + conditions      │   │ replicas       │
 │ audit log     │   │ (holds, ownership)│   │                │
 └───────┬───────┘   └─────────┬─────────┘   └───────┬────────┘
         └─────────────┬───────┴─────────────────────┘
                       ▼
 ┌──────────────────────────────────────────────────────────┐
 │  INTENT CHECK  →  STATE ASSESSOR  →  PLANNER             │
 │  (deterministic)                                         │
 └───────────────────────────┬──────────────────────────────┘
                             │  baseline plan
        ┌────────────────────┴─────────────────────┐
        │ (Phase 2, optional)                      │
        ▼                                          │
 ┌─────────────────────┐   findings   ┌────────────┴─────────┐
 │ INVESTIGATOR AGENT  │ ───────────► │ FINDING VERIFIER     │
 │ LLM tool loop,      │              │ re-runs cited query; │
 │ step cap 8          │ ◄─ tools ─── │ drops unsupported    │
 │ via cached client   │   (gated)    └────────────┬─────────┘
 └─────────────────────┘                           │ verified findings
                                                   ▼
 ┌──────────────────────────────────────────────────────────┐
 │  PLAN MERGER → VALIDATOR → output.csv writer             │
 └──────────────────────────────────────────────────────────┘
        │
        ▼
 output.csv      EVAL HARNESS (vs sample_output.csv)      reports
```

### 2.3 Data flow for one case

1. Load the request row: `case_id`, `request_text`, `audit_at`, request email, `reported_status`.
2. **Intent check:** does the text authorize deletion? If not, emit `NOT_APPLICABLE` with `[]`.
3. **Resolve identity** as of `audit_at`: all emails, hashes, phones, `user_id`, `customer_reference`.
4. **Collect candidate records** across all systems, using only evidence with `captured_at <= audit_at`. Use the latest snapshot per system at or before `audit_at`.
5. **Apply rules** per record: expected disposition (delete, redact, anonymize, retain), including conditions.
6. **Assess risk:** enabled connectors, backups with restore allowed, replica drift, later syncs that recreate data.
7. **Classify:** `COMPLETE` if every required disposition is already met at `audit_at`, else `INCOMPLETE`.
8. **Plan:** build FINDING, REMEDIATION, and VERIFICATION steps with dependency ordering (disable or block before changing dependent records).
9. **Validate and write.**

### 2.4 Layout

```
repo root
├── output.csv
├── log.txt                      # append-only, per AGENTS.md
├── README.md
├── NOTES.md                     # tried / reverted / why (interview prep)
└── code/
    ├── pramaantrace/
    │   ├── cli.py               # one-command entry points
    │   ├── config.py            # env vars, step cap, paths
    │   ├── loader/              # csv, sql, json, log, text loaders
    │   ├── store/               # record store + temporal gate
    │   ├── identity.py
    │   ├── rules.py
    │   ├── drift.py
    │   ├── intent.py
    │   ├── assess.py            # state at audit_at
    │   ├── planner.py
    │   ├── validator.py
    │   ├── agent/
    │   │   ├── loop.py
    │   │   ├── tools.py
    │   │   ├── verifier.py
    │   │   └── llm_client.py    # cache + usage tracking
    │   └── writer.py
    ├── prompts/
    ├── config/
    ├── tests/
    └── evaluation/
        ├── harness.py
        ├── evaluation_report.md
        └── usage_report.md
```

---

## 3. Deep Dive

### 3.1 Evidence loader and record store

**Inputs and handling:**

| Source | Handling |
|---|---|
| CSV | Parse to rows, tag with file-level `captured_at` |
| SQL snapshots (24) | Load each into its own in-memory SQLite DB; record `capture_id`, `captured_at`, `topology` |
| JSON, logs, text | Parse to records; keep raw text for `read_text_evidence` |
| Images, PDFs | **Deferred.** Optional after the structured path works |

**Schema normalization.** Table names differ across snapshots and topologies, so schema is not assumed. A per-topology adapter maps source tables and columns to the canonical record shape. Adapters are explicit config, not guesses, and an unmapped table raises a loud error rather than being silently skipped. **[UNVERIFIED: the real table and column variants must be enumerated from the 24 snapshots.]**

**Canonical record:**

```
Record {
  capture_id, captured_at, topology,
  system_id, resource_id, category,
  identifiers: { emails[], email_hashes[], phones[], user_id, customer_reference },
  attributes: {...}          # e.g. legal_hold, retention_until, shared_with, restore_allowed, enabled
}
```

**Temporal gate.** `RecordStore` exposes no unfiltered read. Every query method requires `audit_at` and applies `captured_at <= audit_at` internally. Agent tools receive a store handle already bound to the case's `audit_at`, so a tool cannot widen the window even if the model asks it to.

**Latest snapshot rule.** For a given system and resource, "state at `audit_at`" comes from the latest snapshot at or before `audit_at` (matches 70 of 70 text-searchable sample citations).

### 3.2 Identity resolver

- Sources: `user_identities` plus `user_audit_log`.
- Output: every identifier valid as of `audit_at`, including historical emails and phones, so an old request email still resolves.
- Matching keys: lowercase-normalized email, SHA-256 of the normalized email, phone (normalized), `user_id`, `customer_reference`.
- Audit-log replay: apply changes in time order up to `audit_at` only, so identifiers added after `audit_at` are excluded.
- Ambiguity handling: if an identifier maps to more than one user, flag the case instead of guessing. **[UNVERIFIED: whether this occurs in the data.]**

### 3.3 Rule engine

- Source: `deletion_rules.csv`, applied per record category.
- Conditions are evaluated explicitly, not skipped. Examples from the spec:
  - Support attachment: delete only if it belongs only to the subject. If shared, do not delete.
  - Legal hold or retention window: `RETAIN`.
  - Account: tombstone keeps stable `user_id`, removes name, email, phone, email hash.
- Output per record: `required_disposition ∈ {DELETE, REDACT, ANONYMIZE, RETAIN}` plus the rule ID that produced it.
- Rules are data-driven. No case-specific branches.

### 3.4 Drift detector

- Compares the same logical resource across topologies (primary vs regional, reporting, failover, read replica) at the latest snapshot at or before `audit_at`.
- Drift classes:
  1. **Absent on primary, present on replica:** remaining record, remediation needed on the replica.
  2. **Deleted, then recreated by a later sync** (sync events at or before `audit_at`): record is PRESENT again.
  3. **Present on primary, absent on replica:** informational.
- Replica snapshots may have different capture times. Each is gated and evaluated independently.

### 3.5 Risk assessment

| Risk | Detection | Finding | Remediation | Verification |
|---|---|---|---|---|
| Active connector or data flow | Enabled connector touching subject data | `REPORT_ACTIVE_DATA_FLOW` | `DISABLE_DATA_FLOW` | `VERIFY_DATA_FLOW_DISABLED` |
| Backup restore allowed | Backup with restore permitted | `REPORT_RESTORE_RISK` | `BLOCK_RESTORE` | `VERIFY_RESTORE_BLOCKED` |
| Remaining record | Record present where rules require removal | `REPORT_REMAINING_RECORD` | `DELETE_RECORD` | `VERIFY_RECORD_ABSENT` |
| Exposed PII | PII in a record that should be redacted | `REPORT_EXPOSED_PII` | `REDACT_RECORD` or `ANONYMIZE_RECORD` | `VERIFY_RECORD_REDACTED` / `VERIFY_RECORD_ANONYMIZED` |

**Ordering constraint:** disable connectors and block restores before changing dependent records. The planner encodes this as a dependency edge, though the sort rule (operation order) already places `DISABLE_DATA_FLOW` and `BLOCK_RESTORE` first within REMEDIATION.

### 3.6 Intent check

- Decides `NOT_APPLICABLE` when `request_text` does not authorize deletion (for example, an access request, a question, or a withdrawn request).
- Baseline: rule-based phrase and structure classification, version-controlled.
- `reported_status` is never an input to this decision.
- **[UNVERIFIED]** Whether the NOT_APPLICABLE cases are separable by simple rules is unknown. If not, an LLM classification step with cached output may be added here, behind the same validator.

### 3.7 State assessor and classification

For each required disposition, determine the state at `audit_at` from evidence:

- All dispositions satisfied → `COMPLETE`. Emit only VERIFICATION steps, each citing the evidence that proves the state.
- Any unsatisfied → `INCOMPLETE`. Emit FINDING (evidence cited), the full REMEDIATION plan, then VERIFICATION steps.

`reported_status` and activity results (`SUCCESS`, etc.) are treated as claims. They may be shown to the agent as context but never decide the outcome.

### 3.8 Planner

- Builds the step list, then sorts by: phase, operation order, `system_id`, `resource_id`.
- Assigns consecutive `step_no` from 1.
- Evidence rules: FINDING and `COMPLETE`-case VERIFICATION cite a real `evidence_id`; REMEDIATION and INCOMPLETE-case VERIFICATION use `""`.
- Uses only allowed operation/state pairs. The pair table is a constant and the validator rejects anything else.

### 3.9 Investigator agent (Phase 2, built after the baseline report)

**Purpose:** find things the baseline misses (ambiguous identity matches, unusual record locations, text evidence needing interpretation). It never writes final steps.

**Tools** (all bound to `audit_at` at construction):

| Tool | Returns |
|---|---|
| `resolve_identity(identifier)` | Resolved identifier set as of `audit_at` |
| `search_records(query, system_id?)` | Records matching, with `evidence_id` and `captured_at` |
| `compare_replicas(resource_id)` | Per-topology presence and drift class |
| `get_activity(subject)` | Activity entries at or before `audit_at` |
| `get_rules(category)` | Matching rules and conditions |
| `read_text_evidence(evidence_id)` | Text of a gated evidence item, wrapped and labeled as untrusted data |

**Loop:** step cap default 8 (configurable). Output is a structured list of findings, each citing the tool call and arguments that support it.

**Finding verifier:** re-runs each finding's cited tool call against the store and checks the claim matches. Unsupported or unreproducible findings are dropped. Surviving findings are passed to the plan merger, which can only add steps that pass the same validator as baseline steps.

**Prompt-injection posture:**
- Evidence text is wrapped in delimiters and labeled as data in the system prompt.
- The model has no tool that writes output, changes the gate, or reads outside the store.
- Even a fully hijacked agent can only emit findings, and the verifier rejects any it cannot reproduce.

**Measuring gain:** run the eval harness on baseline-only and baseline+agent with the same inputs. Report the deltas in case, step, field, and sequence accuracy. Claim the agent helps only if the delta is measured and positive.

### 3.10 LLM client, cache, usage tracking

- Single client wrapper. All model calls go through it.
- Cache key: hash of `(model, prompt, input)`. Cache hit returns the stored response without a network call.
- Per call: record model, provider, input tokens, output tokens, estimated cost.
- Cache may contain subject data, so it is excluded from `code.zip`.
- Keys are read from environment variables only. Never logged.
- Temperature fixed at 0 where supported. A cold run is not guaranteed identical, so determinism is guaranteed by the cache (a warm run is byte-identical).

### 3.11 Validator

Runs on every case before writing. Checks:

- Header, 518 rows, sorted by `case_id`
- `deletion_status` in the allowed set
- `steps_json` parses and has exactly the required keys
- `step_no` consecutive from 1
- Phase order and within-phase sort
- Operation/state pair in the allowed table
- Evidence rules per status (non-empty and real for FINDING and COMPLETE-VERIFICATION, empty otherwise)
- Every cited `evidence_id` exists and has `captured_at <= audit_at`
- `NOT_APPLICABLE` implies `[]`

A failure is a build error, not a warning.

### 3.12 Eval harness

One command compares an output CSV with `dataset/sample_output.csv` (32 cases) and reports:

- **Case status accuracy:** exact match of `deletion_status`
- **Step-level accuracy:** matched steps over expected steps (set match on the full step tuple)
- **Field-level accuracy:** per-field match across aligned steps
- **Sequence accuracy:** exact ordered match of the full `steps_json` per case

Also reports per-case diffs for failure analysis. Custom test cases (at least 3, not copies of the samples) live in `code/tests/` and cover, for example: an old-email request, a legal-hold retention, and a replica that still holds a record deleted on the primary.

### 3.13 Determinism

- Iterate over sorted keys everywhere. No reliance on dict, set, or filesystem order.
- JSON serialization: `sort_keys` for dicts we construct, fixed separators, ASCII-stable. Step key order is fixed to the spec order.
- Cached model calls.
- Proof: run twice with a warm cache and compare SHA-256 of `output.csv`.

---

## 4. Data Model Summary

```
DeletionRequest   case_id, request_text, audit_at, request_email, reported_status
Identity          user_id, emails[], email_hashes[], phones[], customer_reference
Rule              rule_id, category, disposition, condition
Record            capture_id, captured_at, topology, system_id, resource_id,
                  category, identifiers, attributes
Snapshot          capture_id, captured_at, topology, system_id, source_file
Finding           kind, system_id, resource_id, evidence_id, supporting_query
Step              step_no, phase, system_id, resource_id, operation, state, evidence_id
```

---

## 5. Scale, Reliability, Observability

**Load estimate:** 518 cases, 850 identities, 24 SQL snapshots. Everything fits in memory. Preload snapshots once, then evaluate cases in a loop. Cases are independent, so parallelism is possible, but sequential execution is the default for determinism.

**Failure handling:**
- Unmapped schema or unparseable evidence: fail loudly with the file and table name.
- LLM error or timeout: retry with backoff (bounded), then fall back to the baseline for that case. The run does not fail.
- Missing API key: agent stage is skipped and the baseline runs. The run reports that the agent was disabled.
- Validator failure: stop and report the offending case.

**Observability:**
- `log.txt`: append-only session log in the `AGENTS.md` format (exact model ID, no keys, no PII).
- Per-run summary: counts by status, drift cases found, findings proposed vs verified vs dropped.
- `usage_report.md`: provider, model, call count, input and output tokens (total and average), estimated cost.

---

## 6. Trade-off Analysis and Open Risks

| Decision | Chosen | Alternative | Why / cost |
|---|---|---|---|
| Who decides final steps | Code | LLM end-to-end | Reproducible, testable, injection-resistant. Cost: rules must be written and maintained, and the baseline may miss odd cases. |
| Agent role | Findings only, verified by re-running queries | Agent writes steps | Prevents hallucinated evidence. Cost: some correct but unreproducible findings are dropped. |
| Storage | In-memory SQLite plus normalized record store | Pandas only; full DB server | SQL snapshots already target SQLite, and a server is overkill. Cost: adapter work per topology. |
| Schema handling | Explicit per-topology adapters | Auto-detect columns | Auto-detect silently mislabels. Cost: manual mapping across 24 snapshots. |
| Temporal gate | In the store, mandatory | Per-tool filtering | One enforcement point, so no tool can forget it. Cost: store API is stricter. |
| Determinism | Response cache | Temperature 0 only | Temperature 0 does not guarantee identical output. Cost: stale cache risk, so key includes model and prompt. |
| Images/PDFs | Deferred | Build OCR up front | Structured path first. Cost: possible accuracy ceiling if key evidence is in images. |

### 6.1 Open question to resolve first: absence proofs

In 4 sample absence-proof citations, the cited file does not contain the `resource_id`. Candidate explanations to test, in order:

1. The citation points to the latest snapshot of the **system** (which proves absence by being the authoritative listing), not a snapshot containing the resource.
2. The citation points to the **last snapshot that contained the resource**, and absence is shown by a later snapshot.
3. The resource appears under a different identifier form (for example a hashed or renamed key) that text search misses.

Pick the explanation that matches all 4 plus the other absence cases, write the rule in `NOTES.md`, and add a test. Until then, absence-proof citation logic is **unverified**.

### 6.2 Other unverified items

- Exact operation sort order (confirm against `AGENTS.md` and samples)
- Real schema variants across the 24 SQL snapshots
- Whether identifiers can be ambiguous across users
- Whether NOT_APPLICABLE intent is separable by rules
- Whether any key evidence lives only in images or PDFs

---

## 7. Milestones

| # | Milestone | Exit criteria |
|---|---|---|
| 0 | Read `AGENTS.md`, `problem_statement.md`, `README.md`; inspect dataset headers; log SESSION START; post plan and conflicts | Plan posted |
| 1 | Eval harness | One command prints the four accuracy metrics on a CSV |
| 2 | Evidence loader and record store | All 24 snapshots loaded, schema adapters mapped, temporal gate unit-tested |
| 3 | Identity resolver | Old-email cases resolve; audit-log replay respects `audit_at` |
| 4 | Deterministic baseline | Valid 518-row `output.csv`; baseline scores reported. **Pause here.** |
| 5 | Investigator agent and verifier | Gain over baseline measured on samples |
| 6 | Cache and cost tracking | Warm-cache runs hash-identical |
| 7 | Full run, failure analysis, fixes | Findings and fixes recorded |
| 8 | Reports and packaging | `code.zip`, both reports, `NOTES.md` |

---

## 8. What I Would Revisit as the System Grows

- Replace hand-written topology adapters with schema inference plus human-reviewed mappings if the number of sources grows.
- Add image and PDF evidence (OCR plus verifier) if the failure analysis shows missing proofs.
- Make the rule engine fully declarative (rule DSL with test fixtures) if rules multiply.
- Parallelize per-case evaluation behind a deterministic merge if volume exceeds the single-process budget.
- Add a regression suite built from every failure found in the full run.
