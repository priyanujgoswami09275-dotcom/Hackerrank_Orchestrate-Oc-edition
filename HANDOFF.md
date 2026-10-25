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

- M4d Step 2: linkage analysis. Classify how each missing step's resource
  connects to the subject using only evidence at/before audit_at; write the
  count table in NOTES.md; no case IDs in code.

## Exact next step

1. Write/extend a gated diagnostic (evaluation-only, may read sample labels) to
   classify the 80 missing tuples into link types.
2. M4d Step 3: implement general subject linkage one type at a time, ordered by
   how many missing steps each explains; report A/B/all after each; revert what
   does not help; log in NOTES.md.
3. Step 4: evidence-ID selection rule; Step 5: intent/language coverage audit.
4. M5 agent only if budget remains; then section I deliverables
   (reports, NOTES.md interview sheet, code.zip rebuild + secret scans).

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
