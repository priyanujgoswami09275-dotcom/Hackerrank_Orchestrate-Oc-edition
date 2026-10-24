# PramaanTrace model and usage report

## Full-dataset run

The final 518-case output was produced by the deterministic baseline. The
investigator-agent milestone is not implemented, and no LLM provider or model
was invoked. This report counts model use by the prediction pipeline, not the
coding-assistant model used during development.

| Provider/model | Calls | Input tokens | Output tokens | Estimated cost |
|---|---:|---:|---:|---:|
| None (LLM disabled/not implemented) | 0 | 0 | 0 | $0.00 |
| **Overall** | **0** | **0** | **0** | **$0.00** |

- Audited requests: 518
- Output status counts: COMPLETE=122, INCOMPLETE=387, NOT_APPLICABLE=9
- Output SHA-256: `9745eb17e50948658c8531dc173e64e7b8e381faa44b9700749dd9dc5a8d2bf8`
- Average model requests per audited case: 0
- Average input tokens per audited case: 0
- Average output tokens per audited case: 0
- Average estimated model cost per audited case: $0.00
- Average tokens per model request: n/a (there were no model requests)

The local media pass used Apple Vision/PDFKit and pypdf. These tools do not
consume provider tokens, and no model-token cost is estimated for them. Two
consecutive warm-cache M4c full runs produced byte-identical output with the
SHA-256 above. The earlier M4b warm-cache/cache-disabled comparison also
matched, but it preceded the M4c intent correction; a cache-disabled run was
not repeated after that correction. OCR text is cached outside the repository;
cache contents are excluded from `code.zip`, and the submitted output does not
require the cache.

No API key was read, used, or recorded. These figures describe the measured
baseline run only; they are not an estimate for a future LLM-enabled agent.
