# Bedrock experiment — 2026-11-04

Qwen3 Next 80B A3B (`qwen.qwen3-next-80b-a3b`) was invoked through Amazon Bedrock in `us-east-1`. All 90 planned observations completed. The protocol and planned request hashes were recorded before generation. Temperature was 0, output was capped at 768 tokens and the prompt and deterministic policy were unchanged within this experiment.

## Ten reused reporting fixtures

| Context | Correct actions | Valid outputs | Missing-evidence F1 | Mean unrelated fields sent |
| --- | --- | --- | --- | --- |
| Full context | 3/10 | 8/10 | 0.30 | 8 |
| Known-field PII masking | 4/10 | 9/10 | 0.35 | 3 |
| Minimera purpose-specific view | 5/10 | 9/10 | 0.45 | 0 |

The fixed workflow gates **fail**: neither baseline nor candidate reaches 90% action accuracy; the candidate misses 0.80 evidence F1 and has one invalid output. No unrelated structured fields were sent by the purpose-specific policy, and its action score did not regress against full context in this run. These observations do not establish operational readiness, legal compliance or anonymity.

Across all 30 fixtures, correct actions were 11/30, 14/30 and 15/30 respectively; valid outputs were 24/30, 22/30 and 24/30. Captured schema failures exceeded the four-citation limit. The application rejected them without truncating citations or repairing the generated answer, and failures remain in each metric's denominator. The AWS-compatible schema omits some bounds that remain enforced by the local Pydantic contract.

## Limits and provenance

These are developer-authored synthetic fixtures with AI assistance. Twenty are development cases; the ten reporting fixtures are reused from the earlier local experiment, not a new unseen or independently blinded set. Results are a small descriptive comparison of context modes, not a statistically established model improvement. Scores against the older model are not a controlled cross-model experiment.

The first invalid purpose-mode answer for NTK-001 was observed before raw failure capture was enabled. Its error is retained; its raw output and token count are unavailable. A separately labelled diagnostic retry is stored only in runtime evidence and does not replace the planned observation. Interactive retries may appear in the workspace while the Evaluation page remains a fixed experiment snapshot.

Bedrock model ID, region, exact unsigned request envelope, SHA-256, returned text, token counts where available and provider request ID are recorded. They are not a weight digest, cryptographic execution attestation or deletion proof. No credentials are included. The original dataset, protocol and local benchmark remain unchanged.

A separate end-to-end PayPal sandbox check read the configured order/capture/dispute relationship and passed only 17 allowlisted business facts to Bedrock. The model returned a structurally valid `gather_evidence` draft. This integration check is outside the 90 synthetic observations and has no adjudicated action label. The timestamped [normalized observation](paypal-observation.json) and [actual model response](paypal-model-run.json) are retained separately; raw PayPal profiles and messages are excluded.

- [Fixed protocol](protocol.json)
- [Complete observations and metrics](benchmark.json)
- [Original local results](../../RESULTS.md)

Requests were sequential and made without loading local model weights. The runtime reserves at most 100 attempts by default, including failures and retries; this is not an AWS billing cap. Application of a particular AWS credit grant has not been verified.
