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
- Prediction map: no model calls; the deterministic planner classified,
  assessed, planned, and serialized every case
- Output status counts: COMPLETE=133, INCOMPLETE=376, NOT_APPLICABLE=9
- Output SHA-256: `35351f13786f2aaa11926f8ba72febdec231b506dc96a0064a27682b8854c1ed`
- Output produced with: `PRAMAANTRACE_ENRICH=1`
- Average model requests per audited case: 0
- Average input tokens per audited case: 0
- Average output tokens per audited case: 0
- Average estimated model cost per audited case: $0.00
- Average tokens per model request: n/a (there were no model requests)

The local media pass used Apple Vision/PDFKit and pypdf. These tools do not
consume provider tokens, and no model-token cost is estimated for them. Two
full runs in the same session (the root write and an independent trial to a
separate path) produced byte-identical output with the SHA-256 above. OCR
text is cached outside the repository; cache contents are excluded from
`code.zip`, and the submitted output does not require the cache.

No API key was read, used, or recorded. These figures describe the measured
baseline run only; they are not an estimate for a future LLM-enabled agent.
