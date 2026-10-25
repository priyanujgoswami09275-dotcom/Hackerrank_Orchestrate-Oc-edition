# PramaanTrace: Product Requirements Document

**Product:** PramaanTrace, an AI-assisted deletion-audit agent
**Context:** HackerRank Orchestrate, October 2026 hackathon ("Ghost Data Still Exists")
**Status:** Draft v1. Nothing described here has been built or run yet. Items marked **[UNVERIFIED]** are assumptions to confirm against `AGENTS.md`, `problem_statement.md`, and the dataset.
**Precedence:** `AGENTS.md` is the source of truth. If this PRD conflicts with it, `AGENTS.md` wins and this PRD gets corrected.
**Companion document:** `architecture.md` (how it is built). This PRD covers what and why.

---

## 1. Overview

### 1.1 Problem

Organizations receive data-deletion requests (privacy erasure requests). Teams often mark them "complete" based on a ticket status or a job that reported success, while copies of the subject's data still sit in replicas, backups, connectors, support attachments, or recreated-by-sync records. The claimed status and the real state diverge.

In the sample data, 11 of 17 requests claimed COMPLETE are actually INCOMPLETE, and 3 claimed NOT_STARTED are actually COMPLETE. Status fields are not trustworthy, and someone has to audit the evidence.

### 1.2 Product vision

For every deletion request, produce an auditable, evidence-backed verdict: was deletion actually authorized, is it actually done as of the audit date, and if not, what exactly must be done, in what order, with proof.

### 1.3 Goals

1. Correctly classify each of the 518 requests as `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`.
2. For each case, emit an ordered plan whose steps match the required format, ordering, and evidence rules.
3. Never rely on claims (`reported_status`, activity results) as proof, and never use evidence captured after `audit_at`.
4. Be explainable and reproducible: every cited fact traces to a real evidence item, and two runs produce identical output.
5. Deliver the full hackathon package: `output.csv`, `code.zip`, evaluation report, usage report.

### 1.4 Non-goals

- Performing real deletions. The system audits and plans only.
- Using organizer-only files, golden labels, or case-specific shortcuts.
- Hardcoding case IDs, evidence IDs, names, or filenames.
- Letting an LLM write or alter final steps.
- Image and PDF understanding in the first version (optional later).
- A user interface. This is a batch pipeline run from the command line.

---

## 2. Users and Use Cases

| User | What they need |
|---|---|
| **Hackathon judges / evaluators** | A valid `output.csv`, honest accuracy numbers, reproducible code, and a candid account of what works and what does not |
| **Privacy / compliance auditor (the product's conceptual user)** | A verdict they can defend, with each claim linked to dated evidence |
| **Engineer who must remediate** | An ordered plan that disables risk sources before changing dependent records |

### 2.1 Primary scenarios

1. **Old email in the request.** The request names an email the subject no longer uses. The system still finds the subject through historical identifiers.
2. **Deletion reported done, but a replica still holds the record.** Verdict INCOMPLETE with the remaining record found.
3. **Legal hold or retention window.** The record is retained correctly, and the case is judged on the remaining records.
4. **Shared support attachment.** Not deleted because it does not belong only to the subject.
5. **Enabled connector or restorable backup.** Reported as a risk and disabled or blocked before dependent changes.
6. **Request that does not authorize deletion.** Verdict NOT_APPLICABLE with empty steps.
7. **Reported NOT_STARTED, but the evidence shows it is finished.** Verdict COMPLETE with verification proof.

---

## 3. Functional Requirements

Priority: **P0** is required for a valid submission, **P1** is important, **P2** is optional.

### 3.1 Input handling

| ID | Requirement | Pri |
|---|---|---|
| F-1 | Read all 518 rows of `dataset/deletion_requests.csv` | P0 |
| F-2 | Use only participant-visible files under `dataset/` | P0 |
| F-3 | Load CSV, SQL snapshots (into SQLite), JSON, logs, and text evidence | P0 |
| F-4 | Tag every evidence item with `capture_id`, `captured_at`, and topology | P0 |
| F-5 | Normalize differing SQL table names and topologies (primary, regional, reporting, failover, read replica) through explicit adapters; fail loudly on an unmapped table | P0 |
| F-6 | Read images and PDFs | P2 |

### 3.2 Intent decision

| ID | Requirement | Pri |
|---|---|---|
| F-7 | Decide whether `request_text` actually authorizes deletion | P0 |
| F-8 | Emit `NOT_APPLICABLE` with `steps_json = []` when it does not | P0 |
| F-9 | Never use `reported_status` to decide intent | P0 |

### 3.3 Identity resolution

| ID | Requirement | Pri |
|---|---|---|
| F-10 | Match on current and historical emails, SHA-256 email hashes, phones, `user_id`, and `customer_reference` | P0 |
| F-11 | Resolve identifiers valid as of `audit_at` using `user_identities` and `user_audit_log` | P0 |
| F-12 | Resolve correctly when the request email is an old one | P0 |
| F-13 | Flag, rather than guess, when an identifier maps to more than one subject | P1 |

### 3.4 Rule application

| ID | Requirement | Pri |
|---|---|---|
| F-14 | Apply `deletion_rules.csv` per record, including its conditions | P0 |
| F-15 | Support attachment is deleted only if it belongs only to the subject | P0 |
| F-16 | Legal hold or retention window results in RETAIN | P0 |
| F-17 | Account tombstone keeps the stable `user_id` and removes name, email, phone, and email hash | P0 |

### 3.5 State and risk assessment

| ID | Requirement | Pri |
|---|---|---|
| F-18 | Determine the state of every relevant record at `audit_at` from the latest snapshot at or before `audit_at` | P0 |
| F-19 | Treat `reported_status` and activity results as claims, not proof | P0 |
| F-20 | Never read, use, or cite evidence captured after `audit_at` | P0 |
| F-21 | Compare primary and replica snapshots to detect drift (present on replica but absent on primary; recreated by a later sync) | P0 |
| F-22 | Treat an enabled connector or a backup with restore allowed as a risk to be disabled or blocked before changing dependent records | P0 |

### 3.6 Plan generation

| ID | Requirement | Pri |
|---|---|---|
| F-23 | Produce steps with exactly the keys `step_no, phase, system_id, resource_id, operation, state, evidence_id` | P0 |
| F-24 | `step_no` starts at 1 and is consecutive | P0 |
| F-25 | Order by phase (FINDING, REMEDIATION, VERIFICATION), then operation order, then `system_id`, then `resource_id` ascending | P0 |
| F-26 | `COMPLETE`: only VERIFICATION steps, each citing a real `evidence_id` | P0 |
| F-27 | `INCOMPLETE`: FINDING steps with evidence, then the full REMEDIATION plan, then VERIFICATION steps; remediation and verification use `evidence_id ""` | P0 |
| F-28 | Use only the allowed operation/state pairs (`AGENTS.md` §6.4); never invent phases, operations, or states | P0 |

**Allowed operation/state pairs** (listed in the within-phase sort order **[UNVERIFIED: confirm the order against AGENTS.md and `sample_output.csv`]**):

| Phase | Operation (state) |
|---|---|
| FINDING | `REPORT_REMAINING_RECORD` (PRESENT), `REPORT_EXPOSED_PII` (PRESENT), `REPORT_ACTIVE_DATA_FLOW` (ACTIVE), `REPORT_RESTORE_RISK` (ACTIVE) |
| REMEDIATION | `DISABLE_DATA_FLOW` (DISABLED), `BLOCK_RESTORE` (BLOCKED), `DELETE_RECORD` (ABSENT), `REDACT_RECORD` (REDACTED), `ANONYMIZE_RECORD` (ANONYMIZED) |
| VERIFICATION | `VERIFY_RECORD_ABSENT` (ABSENT), `VERIFY_RECORD_PRESENT` (PRESENT), `VERIFY_RECORD_REDACTED` (REDACTED), `VERIFY_RECORD_ANONYMIZED` (ANONYMIZED), `VERIFY_DATA_FLOW_DISABLED` (DISABLED), `VERIFY_RESTORE_BLOCKED` (BLOCKED) |

### 3.7 Output

| ID | Requirement | Pri |
|---|---|---|
| F-29 | Write `output.csv` at the repo root with header exactly `case_id,deletion_status,steps_json` | P0 |
| F-30 | 518 data rows sorted by `case_id` | P0 |
| F-31 | A validator checks every format, ordering, and evidence rule before the file is written; a failure is a build error | P0 |
| F-32 | Every cited `evidence_id` exists and has `captured_at <= audit_at` | P0 |

### 3.8 AI investigator (after the baseline is reported)

| ID | Requirement | Pri |
|---|---|---|
| F-33 | A tool-using LLM agent with a configurable step cap (default 8) investigates cases | P1 |
| F-34 | Tools: `resolve_identity`, `search_records`, `compare_replicas`, `get_activity`, `get_rules`, `read_text_evidence`; each filters out evidence after `audit_at` internally | P1 |
| F-35 | The agent returns structured findings citing tool results; it never writes final steps | P1 |
| F-36 | A verifier re-runs each finding's cited query; unsupported findings are dropped and the baseline stands | P1 |
| F-37 | Evidence text is treated as data; instruction-like text inside it is ignored | P0 |
| F-38 | The agent's gain over the baseline is measured on the sample set and reported honestly, including if the gain is zero or negative | P1 |

### 3.9 Evaluation, logging, and reports

| ID | Requirement | Pri |
|---|---|---|
| F-39 | One-command eval harness against `dataset/sample_output.csv` (32 cases) reporting case status accuracy, step-level, field-level, and sequence accuracy | P0 |
| F-40 | Append a SESSION START entry and a per-turn summary to `log.txt` in the exact `AGENTS.md` format, recording the exact model identifier; append-only; no keys or personal data | P0 |
| F-41 | Cache every model call keyed by a hash of (model, prompt, input); record input tokens, output tokens, and cost per call | P1 |
| F-42 | `evaluation_report.md`: accuracy metrics, at least 3 custom test cases (not copies of samples), failures found, improvements made | P0 |
| F-43 | `usage_report.md` for the final full run: providers and models, call count, input and output tokens (total and average), estimated cost (per model and overall) | P0 |
| F-44 | `NOTES.md` listing what was tried, what was reverted, and why | P1 |

---

## 4. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Determinism** | Sorted iteration, stable JSON serialization, cached model calls. With a warm cache, two consecutive runs produce byte-identical `output.csv`, proved by a hash comparison. |
| **Correctness over coverage** | Final steps are decided by deterministic code, not by an LLM. |
| **Security** | Secrets come from environment variables only and never appear in code, reports, or logs. The model cache is excluded from the package because it may contain personal data. |
| **Honesty** | Report only what has been run and seen working. Unverified claims are labeled as such. Overclaiming is penalized. |
| **Graceful degradation** | With no API key or on LLM failure, the baseline still produces a valid `output.csv`. |
| **Performance** | Whole-dataset run completes on a single machine. **[UNVERIFIED: no target set; the data is small enough for in-memory processing.]** |
| **Reproducibility** | One documented command for setup, eval, and the full run. |

---

## 5. Success Metrics

Targets are not set because the baseline has not been measured. They will be filled in after milestone 4.

| Metric | Definition | Target |
|---|---|---|
| Case status accuracy | Share of the 32 sample cases with the correct `deletion_status` | TBD after baseline |
| Step-level accuracy | Matched steps over expected steps | TBD |
| Field-level accuracy | Per-field match across aligned steps | TBD |
| Sequence accuracy | Share of cases with an exactly matching ordered `steps_json` | TBD |
| Format validity | Share of the 518 output rows passing the validator | **100%** |
| Temporal integrity | Cited evidence captured after `audit_at` | **0** |
| Determinism | SHA-256 of two warm-cache `output.csv` files | **Identical** |
| Agent gain | Accuracy delta, baseline plus agent minus baseline alone, on the same inputs | Report whatever is measured |

A caveat on the sample set: it has only 32 cases, so measured accuracy is a weak estimate of performance on all 518. The evaluation report should say so.

---

## 6. Deliverables

1. `output.csv` at the repo root: 518 rows, validated.
2. `code.zip` containing `README.md` (setup, required environment variables, run command) and `code/` (source, prompts, config). Exclude `dataset/`, virtualenvs, `__pycache__`, `node_modules`, `.git`, nested archives, and any cache holding personal data.
3. `code/evaluation/evaluation_report.md`.
4. `code/evaluation/usage_report.md`.
5. `log.txt` (append-only session log) and `NOTES.md`.

**Path conflict to flag:** the problem statement places the evaluation reports in `code/evaluation/`, while `AGENTS.md` §6.8 says `evaluation/`. The plan is to use `code/evaluation/` unless `AGENTS.md` forces otherwise, and to report the choice.

---

## 7. Milestones and Release Plan

| # | Milestone | Exit criteria |
|---|---|---|
| 0 | Read `AGENTS.md`, `problem_statement.md`, `README.md`; inspect dataset headers; log SESSION START; post plan and conflicts | Plan posted |
| 1 | Eval harness | One command prints the four accuracy metrics |
| 2 | Evidence loader and record store | All 24 snapshots load; schema adapters mapped; temporal gate unit-tested |
| 3 | Identity resolver | Old-email cases resolve; audit-log replay respects `audit_at` |
| 4 | Deterministic baseline | Valid 518-row `output.csv`; baseline scores reported. **Stop here and report before adding the agent.** |
| 5 | Investigator agent and verifier | Gain over baseline measured |
| 6 | Cache and cost tracking | Warm-cache runs are hash-identical |
| 7 | Full run, failure analysis, fixes | Failures and fixes recorded |
| 8 | Reports and packaging | `code.zip`, both reports, `NOTES.md` |

Milestones 1 to 4 run without stopping. The checkpoint after milestone 4 is a deliberate review point.

---

## 8. Risks and Open Questions

| # | Risk / question | Impact | Mitigation |
|---|---|---|---|
| R-1 | **Absence proof is unclear.** In 4 sample absence-proof citations, the cited file does not contain the `resource_id`. | Wrong evidence IDs on absence steps | Test the three candidate explanations in `architecture.md` §6.1 first; write the rule in `NOTES.md`; add a test |
| R-2 | SQL schemas differ across 24 snapshots and topologies | Missed or mislabeled records | Explicit adapters, loud failure on unmapped tables |
| R-3 | Operation sort order is not confirmed | Systematically wrong sequence accuracy | Confirm against `AGENTS.md` and the 32 samples (the sort rule already holds on all 32) |
| R-4 | `NOT_APPLICABLE` intent may not be separable by simple rules | Misclassified cases | Start rule-based and measure; add a cached LLM classification behind the validator if needed |
| R-5 | Key evidence may exist only in images or PDFs | Accuracy ceiling | Check after the structured path works; add as P2 |
| R-6 | Identifiers may be ambiguous across users | Wrong subject matched | Flag rather than guess (F-13) |
| R-7 | Evidence text may contain injected instructions | Agent manipulated | Treat evidence as data, give the agent no write tools, and re-verify every finding |
| R-8 | Small sample set (32 cases) | Overfitting, weak accuracy estimate | Write custom test cases; avoid case-specific logic; state the limitation in the report |
| R-9 | The agent may add cost without improving accuracy | Wasted spend, or worse results | Measure against the baseline; ship it only if the gain is real |

---

## 9. Assumptions

- The dataset under `dataset/` is complete and the participant-visible files are sufficient to solve the task.
- Evidence timestamps are comparable to `audit_at` without timezone ambiguity **[UNVERIFIED]**.
- SHA-256 email hashes match emails (verified on all 850 identities in a prior check).
- The sort rule holds on all 32 sample answers (verified in a prior check).
- Cited evidence in the samples is never captured after `audit_at`, and for text-searchable citations it is the latest snapshot at or before `audit_at` containing the resource (70 of 70, verified in a prior check).

---

## 10. Out of Scope for This Version

- Executing deletions or connecting to live systems
- Any user interface or service deployment
- Image and PDF evidence (P2, only after the structured path works)
- Multi-tenant or production-scale operation
