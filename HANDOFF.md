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
