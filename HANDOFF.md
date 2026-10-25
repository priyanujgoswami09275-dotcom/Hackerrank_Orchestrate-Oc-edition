# HANDOFF — PramaanTrace, Ghost Data Still Exists

Working state for any resumed session. Read AGENTS.md first; this file is the
operational resume point (kept out of code.zip; committed to git).

## What is done

- M1–M4c complete and committed (eval harness, gated evidence store, identity
  resolver, deterministic baseline, media reader, failure analysis, intent fix).
- M4d Step 1 complete and committed by the previous session:
  - `c399763` harness scores steps as content tuples (multiset on
    phase/system/resource/operation/state/evidence, ignoring step_no) and
    reports precision + recall on A/B/all splits.
  - `4181ec9` support-reference fix: `customer_reference` no longer counts as a
    prohibited identifier on support records (rule_05 retains shared context,
    REDACT; direct contact fields absent ⇒ compliant). Kept under the new
    criterion: status 24→27/32, B status 11→13, B tuple recall 43→68/100.
  - 47/47 unit tests pass. Source-literal scan passes.
- Root `output.csv` regenerated with the support fix and committed (`bd44d3f`):
  518 rows, COMPLETE=140, INCOMPLETE=369, NOT_APPLICABLE=9,
  SHA-256 `70c6031d7a45685d43202c6808a8902e51c17e433ae18f5f1e5800f5e4130398`.
  Two consecutive warm-cache runs byte-identical (same hash).

## M5 final-task safe state (2026-10-25)

- `BRIEF.md` is absent from this worktree and the main checkout; the user's
  final master task is the active brief.
- Current branch `feat/investigator-agent` at `39d852f` has a committed,
  validated 518-row baseline in root `output.csv`: COMPLETE=133,
  INCOMPLETE=376, NOT_APPLICABLE=9; SHA-256
  `35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`.
  It matches the previous no-key baseline run. This is distinct from the
  historical `bd44d3f` output above; do not treat the old hash/counts as the
  current branch output.
- `output_baseline.csv` is an exact, uncommitted fallback copy of that current
  baseline (500,724 bytes, same SHA-256); exclude it from `code.zip`.
- The existing `code/run.py` process (PID 13610 when checked) was still alive;
  do not start a duplicate. Its run log was 0 bytes and cache had 0 responses
  at the last check. Recheck before deciding whether its results are usable.

### Step 2 leakage checks

- No runtime source reads `sample_output.csv` or a label file. Its references
  are in evaluation/test code; `loader.py` also loads public
  `sample_deletion_requests.csv`, which `run.py`, `run_baseline`, and the agent
  pipeline do not consume. `python3 code/check_source_literals.py` passed.
- With `dataset/sample_output.csv` temporarily absent, the full no-agent
  pipeline (`python3 code/run.py --disable-agent --output <isolated-temp-file>`)
  validated all 518 cases and produced SHA-256
  `35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`, byte
  identical to the committed baseline. The sample file was restored unchanged;
  root `output.csv` was unchanged.
- Linkage keys: (1) `IdentityResolver` joins the request email or its SHA-256
  to identities visible at `audit_at`, retaining historical email/hash/phone/
  customer-reference values and stable `user_id`; (2) record identity matches
  use user ID, email, email hash, phone, and customer reference; (3) enrichment
  sniffs identifier-shaped values only under `lookup_key`, `query`,
  `subject_key`, `subject_ref`, `search_term`, and `correlation_key`; (4)
  structured cross-references accept resource-shaped attribute values on
  already subject-linked records, excluding record/capture/evidence/request
  IDs and user/customer references; (5) activity linkage requires a whole-token
  identity value in event details and uses that event's resource ID, at/before
  the cutoff; (6) wave-derived accounts require exactly one account DELETE
  within 420 seconds of a linked resource's in-window deletion claim and no
  surviving stored record. All evidence/resource joins are `audit_at` gated.

### Step 3 agent gate

- The full run sourced the main checkout's uncommitted `.env` and completed.
  The sanitized run log reports `nvidia/nemotron-3.5-super-vl:free` via
  `openrouter.ai`, 518 rows validated, and the same output hash as the
  baseline. It attempted 509 authorized cases; 0 completed, 509 fell back,
  0 candidates were accepted/rejected, 1,527 network calls were made (1,018
  retries), and 509 requests failed. Cache responses and input/output tokens
  were 0; reported cost was $0. The run therefore had no measurable output
  gain and the baseline remains selected.
- A separate connectivity/tool-call test and three raw case traces were not
  captured. The full run is the only measured attempt; do not make another
  provider call just to fabricate traces. The second warm-cache hash check,
  budget skips, and per-case attempt details remain unverified. The worktree
  itself has no `.env`; the full run command came from the main checkout.

### Step 4 Feature A — submission guard

- Added `code/tools/submission_guard.py`, documented its repo-root invocation
  in `code/README.md`, and added CLI tests including a deliberately malformed
  CSV and malformed JSON step values. The guard reports each item and exits 1
  on any failure; it calls `validate_rows` as an additional check.
- `python3 -m pytest code/tests -q`: 97 passed, 32 subtests passed.
  `python3 code/check_source_literals.py`: PASS.
- Guard checks for output CSV structure/policy/cutoffs, package contents and
  exclusions, secret-like values in code/reports/log/archive, and dataset-driven
  literals in runtime Python (comments, docstrings, tests, evaluation exempt).
  Its checks pass except `log format`: 15 legacy format issues, including
  `model=unknown` and unverified metadata in pre-existing entries. The log is
  append-only; no historical entry was rewritten. Exit code is 1 as required.
- The existing `code.zip` has not yet been rebuilt with the guard; Step 8 must
  regenerate it and run the guard again.

### Step 5 Feature B — ablation and custom cases

- Added `code/evaluation/ablation_report.md` and `decision_log.md`. Fresh
  sample runs measured rules-only at 27/32 status, 113/193 tuple recall,
  68/193 positional exact steps, 638/1,351 fields, 2/32 sequences; rules plus
  linkage measured 29/32, 161/193, 122/193, 987/1,351, 12/32 respectively.
- The prior sample agent CSV was byte-identical to linkage baseline (17
  completed investigations, 15 fallbacks, 36 candidates accepted, 0 rejected;
  97 network calls, 28 retries, 13 failures, 172,870 tokens, $0 reported).
  The full run made 1,527 network attempts,
  1,018 retries, 509 failed requests, and fell back for all 509 authorized
  cases; 0 tokens/cache responses and $0 reported. Output hash matched the
  baseline. The agent output is dropped; no verifier-off run was attempted.
- Added an instruction-like request test that confirms evidence-driven
  INCOMPLETE output still passes `validate_rows`. Historical-email, legal-hold,
  replica-drift, tombstone-identifier, and missing-retention tests already
  cover the other requested custom conditions. `python3 -m pytest
  code/tests -q`: 98 passed, 32 subtests passed.
- Agent sample call totals, three raw traces, budget skips, verifier-off
  behavior, and a second warm-cache hash remain unverified; the full request
  set has no public gold labels for accuracy scoring.

### Step 6 reports

- Updated `code/evaluation/evaluation_report.md` with current rules/linkage and
  positional metrics, prior sample-agent usage, full agent-run fallback results,
  custom cases including instruction-like input, fixes, known failures, the
  small-sample/non-blind-B limitations, and unverified items.
- Replaced the stale no-agent usage report with the measured full run:
  OpenRouter `nvidia/nemotron-3.5-super-vl:free`, 1,527 network attempts,
  1,018 retries, 509 failures, 0 tokens, and $0.00000000 reported; sample-run
  usage is reported separately (97 calls, 172,870 tokens, $0). No keys are
  included.
- Refreshed the ablation/decision logs with those previously recorded sample
  usage totals. Source-literal scan passed after report updates. Full unit suite
  most recently passed 98 tests and 32 subtests.

### Step 7 notes and interview sheet

- Appended current trials, measured results, kept/dropped decisions, and
  unverified items to `NOTES.md` without removing its historical development
  notes.
- Added root `INTERVIEW.md` covering architecture, why deterministic code
  decides final steps, `audit_at` gates, replica drift, measured agent gain
  (none), remaining failures, unverified items, and cautiously attributed AI
  tool/model records from `log.txt`.

### Step 8 final packaging

- Regenerated root `output.csv` with `python3 code/run.py --disable-agent`:
  518 rows, COMPLETE=133, INCOMPLETE=376, NOT_APPLICABLE=9, sorted by
  `case_id`, SHA-256
  `35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`,
  byte-identical to `output_baseline.csv`.
- `python3 -m pytest code/tests -q`: 98 passed, 32 subtests passed.
- Rebuilt `code.zip` using `code/package_submission.py`: 52 entries; package
  excludes dataset, `.env`, caches, nested archives, and secret-like values.
- Guard PASS: all CSV/pipeline, archive, secret, and hardcoding checks. Guard
  FAIL: log format (15 legacy issues, including unknown/unverified historical
  model fields); exit code 1 as required. No prior log entry was rewritten.
- The agent remains source code only (for audit/optional use); the selected
  submitted predictions are baseline-only. The archive listing and final guard
  output should be rechecked after the final Step 9 log append.

## Latest metrics (32 public samples)

- Status: 27/32 (A 14/16, B 13/16)
- Tuple-matched step precision: 113/115; recall: 113/193 (A 45/93, B 68/100)
- Positional field accuracy: 638/1351 (noisy; no longer the keep/revert gate)
- Exact sequences: 2/32
- Keep/revert criterion (M4d): keep a fix if status or tuple-matched steps
  improve on all 32 AND neither gets worse on half B.

## Known remaining failures (do not re-litigate)

- 5 wrong statuses: 3 expected COMPLETE→INCOMPLETE are unlinked
  account_XXXX absent resources; 2 expected INCOMPLETE→COMPLETE are known
  one-offs (analytics rule_07 attribution conflict; backup `deletion_block`
  schema variant) — brief says do not patch these.
- 80 missing expected tuples, 2 extra candidate tuples. Missing steps
  concentrate on VERIFY_RECORD_ABSENT account_XXXX, VERIFY_RECORD_PRESENT
  audit_record_XXXX (security_service), VERIFY_RECORD_ANONYMIZED
  analytics_XXXX, and whole-case linkage failures.

## In progress

- Final-task step 7 (packaging, secret scan incl. git history, no push) and
  step 8 (final report). Steps 1–6 are complete; see the verdicts below.

## Final-task progress ledger (2026-10-25)

- Step 1 intent fix: committed `197599b` — 3 general negation patterns in
  `code/pramaantrace/intent.py`; RED test first; positive erasure regressions
  green; across all 518 texts exactly 1 flip (case_539 True→False), 0 sample
  flips.
- Step 2: 12 zero-match cases audited (below) → all UNRESOLVED; case_539 was
  the pipeline's intent bug fixed in step 1. Committed `3a37574`.
- Step 3: single OpenRouter diagnostic returned HTTP 429
  `free-models-per-day` (`X-RateLimit-Remaining: 0`, key redacted); agent work
  stopped; reports state root cause + "no measurable gain". Committed
  `09160ae`.
- Step 4: guard strict default with `PRAMAANTRACE_ADMIT_UNRESOLVED_INCOMPLETE=1`
  opt-out (WARN/UNRESOLVED, never PASS; default OFF) and documented
  per-entry legacy-log exemptions (`code/tools/log_exemptions.txt`, 14
  entries). 111 tests pass; guard strict = FAIL only on the unresolved
  INCOMPLETE plans; opt-out run exits 0 with the WARN line. Committed
  `159760d`.
- Step 5: two consecutive runs identical SHA-256
  `6447f3edd32d631689402866973b9ef05aee39a0d2438682dd202f15b99bd7bd`;
  518 rows; COMPLETE=133, INCOMPLETE=375, NOT_APPLICABLE=10 (case_539
  NOT_APPLICABLE, []); sample-label-removal leakage run byte-identical;
  sample eval 29/32 status, 161/161 precision, 161/193 recall, 987/1,351
  fields, 12/32 sequences; sort contract PASS. Committed `7fe08e4`.
- Step 6: evaluation/usage/ablation/decision reports, NOTES.md and
  INTERVIEW.md refreshed with the final numbers, the 12 UNRESOLVED case IDs,
  case_539 outcome, agent root cause, and attribution wording.

## Final-task step 2 verdict (2026-10-25)

- 12 zero-match `INCOMPLETE,[]` cases audited through the temporal gate:
  every resolved identifier (current + historical email, email hash, phone,
  user_id, customer reference) returned 0 pre-cutoff record hits and 0
  surviving records at ANY capture time, and 0 data-flow log hits for every
  identity value at any time.
- case_53 `support_1034` exists only as a 2026-09-17 capture (after its
  2026-05-25 cutoff, non-citable). case_61 `object_19` has no stored record
  at any time. All 12 are honestly UNRESOLVED: no evidence may be cited.
- Stalled-flow ownership is explicit in the logs: every `data_flow_*` line
  with attribution names its owner via `correlation_key` (e.g.
  `data_flow_8024` -> `user_461` = Ana Nowak), none matching the 12 subjects.

## Exact next step

1. Step 7: rebuild `code.zip` with `code/package_submission.py`; list at depth
   2; secret-scan working tree, zip, `log.txt`, and git history (redacted);
   verify `.gitignore` covers `.env`, caches, `output_baseline.csv`,
   `.DS_Store`; show `git status`/`git remote -v`; NO push of any kind.
2. Step 8: final report (paths, guard table, metrics, agent numbers,
   UNRESOLVED cases, secret scan, model name, skipped items). Nothing after.

## Key commands

- Full run: `python3 code/run.py` (writes root output.csv)
- Sample eval: `cd code && python3 evaluate.py`
- Tests: `python3 -m unittest discover -s code/tests -v`
- Hardcoding scan: `cd code && python3 check_source_literals.py`
- Failure analysis: `cd code && python3 evaluation/failure_analysis.py`
- Package: `cd code && python3 package_submission.py`

## Constraints reminders

- Never read/use/cite evidence captured after a case's audit_at (store gate).
- No hardcoded case/evidence IDs, names, filenames in code (scan enforces).
- LLM (if built) proposes findings only; code verifies and decides steps.
- Commit each kept improvement; never commit dataset/, caches, .env,
  CLAUDE.md/PRD.md/"Architecture .md", .DS_Store.
- Append-only log.txt entries every turn (tool=OpenCode, model=z-ai/glm-5.3).
