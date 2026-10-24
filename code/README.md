# PramaanTrace baseline

This package contains the deterministic deletion-audit baseline and the
post-M4 local media reader. Code—not an LLM—classifies requests, assesses
evidence, plans steps, validates the output, and writes the CSV.

## Requirements and setup

- Python 3.10 or newer
- `pypdf` for text extraction from PDFs
- macOS: Swift with the Apple Vision and PDFKit frameworks for OCR
- Other platforms: Tesseract available on `PATH`, plus Pillow and pytesseract,
  for image OCR. If OCR is unavailable, the run reports unprocessed,
  cutoff-eligible media rather than claiming it was read.

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

No API key is required. The investigator agent milestone has not been
implemented, so `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, and
`AGENT_STEP_CAP` are not consumed by this baseline and there are no model
calls. On macOS, set `SWIFT_EXECUTABLE` only if `swift` is not on `PATH`.
`PRAMAANTRACE_MEDIA_CACHE` optionally chooses an OCR cache directory; by
default it is outside this repository (`~/Library/Caches` on macOS or
`$XDG_CACHE_HOME` / `~/.cache` elsewhere). The cache can contain extracted
personal data and must not be submitted.

## Run

From this `code/` directory:

```bash
python3 run.py
```

The command reads participant-visible files under `../dataset/`, validates all
518 predictions, and writes `../output.csv`. Evidence is time-gated by
`audit_at`. Media is read only if its manifest capture time is eligible for at
least one request in the run. Image OCR uses Apple Vision on macOS (or
Tesseract where configured); text-bearing PDFs use pypdf, with Vision OCR as a
fallback for scanned PDFs. Extracted text is cached outside the package.

## One-command sample evaluation

From this `code/` directory, run the baseline on the public sample and evaluate
the generated predictions against all 32 sample answers:

```bash
python3 evaluate.py
```

The harness prints status, step, field, and sequence accuracy plus per-case
differences. Use the structured-only mode to measure the media delta:

```bash
python3 evaluate.py --disable-media
```

To score a candidate CSV already generated for the 32 sample requests, use
`python3 evaluation/harness.py path/to/sample-output.csv`.

Other checks:

```bash
python3 -m unittest discover -s tests -v
python3 check_source_literals.py
```

The source scan reads participant-facing request and evidence manifests and
fails if code embeds a dataset case ID, evidence ID, or evidence filename.

## Build the submission archive

From this directory:

```bash
python3 package_submission.py
```

The script creates `../code.zip` from the **contents** of this directory, so
the archive contains `evaluation/` at its root as required. It applies
exclusions, verifies the archive, and prints every included path.

## Current scope and limitations

The deterministic baseline and local media extraction are implemented; the
tool-using investigator agent is not. The 32 public samples are a weak estimate
of performance on 518 evaluation requests. A missing required retained record
is classified `INCOMPLETE`; the current allowed operation vocabulary has no
finding or remediation for restoring such a record, so the planner does not
invent one.
