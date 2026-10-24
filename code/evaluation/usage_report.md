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
- Output status counts: COMPLETE=120, INCOMPLETE=376, NOT_APPLICABLE=22
- Output SHA-256: `e554553fd4b061b6253b9f3da1f7f2ce8b2a2c251a06650abe62441c1652309f`
- Average model requests per audited case: 0
- Average input tokens per audited case: 0
- Average output tokens per audited case: 0
- Average estimated model cost per audited case: $0.00
- Average tokens per model request: n/a (there were no model requests)

The local media pass used Apple Vision/PDFKit and pypdf. These tools do not
consume provider tokens, and no model-token cost is estimated for them. A
warm-cache rerun and a cache-disabled rerun produced the same output SHA-256.
OCR text is cached outside the repository; cache contents are excluded from
`code.zip`, and the submitted output does not require the cache.

No API key was read, used, or recorded. These figures describe the measured
baseline run only; they are not an estimate for a future LLM-enabled agent.
