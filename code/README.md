# PramaanTrace deletion audit

PramaanTrace audits deletion requests using the enriched deterministic evidence
pipeline. If `LLM_API_KEY` is configured, a bounded LLM investigator runs
automatically to propose additional resource links. Deterministic code replays
and verifies every proposed link, applies policy, plans steps, validates the
contract, and writes the CSV. The model cannot choose the final status or steps.

## Requirements and setup

- Python 3.10 or newer
- Install dependencies:

  ```bash
  python3 -m pip install -r requirements.txt
  ```

- `pypdf` reads selectable PDF text. On macOS, Swift with Apple Vision and
  PDFKit provides OCR. Portable fallback: Tesseract on `PATH`, plus Pillow,
  `pytesseract`, and `pypdfium2`. If no OCR backend is available, the run reports
  cutoff-eligible media it skipped rather than claiming it was read.

No LLM credential is required for the enriched deterministic baseline. Without
`LLM_API_KEY`, the run makes no model calls. With a key, model calls are
automatic unless `--disable-agent` is provided.

## Run

From this `code/` directory:

```bash
python3 run.py
```

The command reads participant-facing files under `../dataset/`, validates the
requests it processes, and writes `../output.csv` by default. The full dataset
contains 518 requests. Evidence is time-gated by each request's `audit_at`.
Media is read only when its manifest capture time is eligible for at least one
request. Extracted text is cached outside the package.

To force deterministic-only operation even when credentials are present:

```bash
python3 run.py --disable-agent
```

This still uses the enriched deterministic baseline. For a structured-only
media comparison, add `--disable-media`.

## Investigator configuration and privacy

Set these environment variables to enable the investigator:

- `LLM_API_KEY`: provider API key.
- `LLM_BASE_URL`: OpenAI-compatible API base URL; for OpenRouter, for example,
  use `https://openrouter.ai/api/v1`. The client appends
  `/chat/completions`. HTTPS is required except for loopback development URLs.
- `LLM_MODEL`: provider model identifier.
- `AGENT_STEP_CAP`: optional completion limit per deletion-authorized case,
  from 1 to 64; default is 8.
- `LLM_INPUT_COST_PER_1M` and `LLM_OUTPUT_COST_PER_1M`: optional per-million
  token rates used only when the provider omits cost from its usage response.
- `PRAMAANTRACE_LLM_CACHE`: optional SQLite response-cache path. By default it
  is outside this repository under `~/.cache/pramaantrace/`.

The program does not load `.env` automatically. For a local uncommitted `.env`
file in a bash/zsh shell, export its values before running:

```bash
set -a
source .env
set +a
python3 run.py
```

Never commit `.env` or include it in `code.zip`. The configured provider receives
the request's cutoff-resolved identifiers and the participant-visible evidence
needed for investigation. Model responses and tool results are cached locally
and may contain sensitive evidence excerpts; protect the cache and do not
submit or package it. API keys, prompts, and evidence contents are not printed
in the run summary. Use `--disable-agent` to prevent provider calls.

## Evidence-linkage enrichment

Enrichment is enabled by default. It includes system normalization, structured
JSON-lines parsing, trace pairing, support-attachment ownership, request-window
close-out checks, structured cross-resource references, and unique-wave account
derivation. Set `PRAMAANTRACE_ENRICH=0` (also `false`, `no`, or `off`) to disable
these enrichment behaviors for a baseline comparison. Explicit `1`, `true`, or
`yes` enables them.

On the 32 public samples, the enriched deterministic baseline scores 29/32
deletion statuses, with 32 missing and zero extra steps; the opt-out baseline
scores 27/32 with 80 missing and two extra steps. These are baseline results,
not a claim about LLM improvement. The measured agent results belong in the
evaluation reports.

## Sample evaluation and checks

From this directory:

```bash
python3 evaluate.py
```

The harness scores all 32 public samples for status, step, field, and sequence
accuracy. If an API key is configured, this command also runs the investigator
because it calls `run.py`; use `python3 run.py --disable-agent` for a direct
deterministic output, or temporarily unset the key for baseline evaluation.
To measure the media delta, run:

```bash
python3 evaluate.py --disable-media
```

Score an existing candidate CSV with
`python3 evaluation/harness.py path/to/sample-output.csv`. For a per-case
multiset diff, use `python3 evaluation/failure_analysis.py`.

Other checks:

```bash
python3 -m pytest tests -q
python3 check_source_literals.py
```

From the repository root, run the submission guard (it requires the
participant-facing `dataset/` directory and supplements the pipeline validator):

```bash
python3 code/tools/submission_guard.py
```

The source scan reads participant-facing request and evidence manifests and
fails if code embeds a dataset case ID, evidence ID, or evidence filename.

## Build the submission archive

From this directory:

```bash
python3 package_submission.py
```

The script creates `../code.zip` from the contents of this directory, verifies
the archive, and prints each included path. The archive must not contain
`dataset/`, `.env`, model/media caches, credentials, or nested archives.

## Scope and limitations

The investigator is advisory and read-only. It can only suggest links supported
by case-scoped tool observations; deterministic replay rejects unsupported,
ambiguous, cross-subject, and post-cutoff candidates. API, tool, and verification
failures fall back to that case's enriched deterministic baseline. Public sample
results are a small estimate of performance on the full dataset. A missing
policy-required retained record is classified `INCOMPLETE`; the allowed
operation vocabulary has no finding or remediation for restoring it, so the
planner does not invent one.
