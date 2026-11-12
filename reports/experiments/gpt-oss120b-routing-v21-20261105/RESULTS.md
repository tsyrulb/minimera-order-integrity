# Frozen routing evaluation — 2026-11-05

The selected configuration is `openai.gpt-oss-120b-1:0` through Amazon Bedrock in `us-east-1`, prompt `inr-assistant/2.1.0`, temperature 0, low reasoning effort and a 4,096-token generation ceiling. Only the final response text is recorded; provider reasoning content is excluded. Every accepted answer passes the unchanged local Pydantic schema and fact-ID checks.

## Ten new reporting variants

| Context | Correct actions | Valid outputs | Missing-evidence F1 | Mean unrelated input fields |
| --- | --- | --- | --- | --- |
| Full context | 9/10 | 9/10 | 0.90 | 8 |
| Known-field PII masking | 10/10 | 10/10 | 1.00 | 3 |
| Minimera purpose view | 10/10 | 10/10 | 1.00 | 0 |

All six original project gates pass: baseline and candidate action accuracy of at least 90%, candidate missing-evidence F1 of at least 0.80, all candidate responses structurally valid, zero unrelated candidate fields and no candidate action regression. These gates measure this synthetic exercise, not production readiness, independent certification, anonymity or legal compliance.

Full context on NTK-039 returned invalid JSON. The raw text and structural error remain in the report, and the attempt counts as incorrect. It was not repaired or retried inside the fixed experiment. Across all 30 cases, full context scored 29/30 actions, masking 30/30 and Minimera 30/30. No exact protected-string matches were observed in accepted outputs; this is not a semantic leakage test.

The workspace displays a recorded failure without invoking a model again. Its comparison keeps the successful modes beside the failed one. An explicitly requested fresh generation remains a separate observation and cannot change these fixed metrics. Byte-size metrics describe canonical policy projections before provider encoding; exact encoded requests are included in exports.

## Selection and data provenance

The dataset contains 20 unchanged development cases and ten new variants, NTK-031 through NTK-040. The new variants change amounts, currencies, rule combinations, field IDs and field order. The snapshot was recorded before model queries on these variants. They were not used to select this configuration. All 20 development cases matched action, missing-evidence and structural checks in each mode before the [selection record](selection.json) was saved; only then were the reporting variants evaluated.

These are developer-authored synthetic cases with AI assistance. Their reference labels are computed from an explicit internal routing rubric and were not independently human adjudicated. The creator knows their contents; this is not an independently blinded test. References, stories and case labels never enter a model request. The evaluation oracle is never used to replace or repair a model output. See [dataset methodology](../../../data/DATASET_V2.md) and the [development-label audit](../../development-label-audit-20261105.json).

This small sample cannot establish generalization or statistical superiority. It also cannot establish an improvement over the earlier 5/10 result: model, prompt and reporting cases differ. The valid comparison here is among context modes within this fixed configuration.

## What changed and what did not

The revised instructions explicitly distinguish seller-response states, unknown deadlines, destination mismatch, merchant-claimed refunds and completed partial refunds. Six worked examples come only from development cases. Input values and selected facts are preserved; the per-fact provenance key `source` is renamed `record_origin` in the provider request so it is not confused with the business field `tracking_source`. Policy `inr-context/1.0.1` and the output contract remain unchanged. All three modes use the same prompt, schema and model settings.

Development-only candidates were retained: Qwen3 Next with prompt 2.0.0 scored 16/20 purpose actions; Qwen3 32B with that prompt scored 1/3 on its short pilot; Qwen3 Next with prompt 2.1.0 scored 2/3 on its pilot. Their reporting partitions were never run. These are selection records with different sample sizes, not a controlled model ranking.

Two purpose drafts matched the original conservative refund-phrasing check. This is not proof that either draft asserted repayment. Runtime draft-check version 1.0.2 describes the factual review requirement without asserting a semantic conclusion from a regex. Stored observations retain their original review metadata. Draft prose and unsupported timing promises still require human review; action/F1 scores do not grade every sentence.

All earlier datasets, protocols and experiments remain intact. Request hashes identify exact unsigned envelopes; they do not attest to provider execution, confidentiality or deletion. No model weights, cloud instances or subscriptions were provisioned. AWS credit application and the exact billed amount are not verified.

A separate end-to-end sandbox check read the configured PayPal order/capture/dispute relationship and sent only 17 allowlisted business facts to this configuration. It returned a structurally valid `gather_evidence` draft. The [normalized observation](paypal-observation.json) and [model response](paypal-model-run.json) are outside the 90 synthetic observations and have no adjudicated action label. Raw customer profiles and messages are excluded.

- [Protocol and all planned request hashes](protocol.json)
- [Complete observations, including the invalid response](benchmark.json)
- [Development-only selection record](selection.json)
