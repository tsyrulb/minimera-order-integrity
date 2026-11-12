# Historical evaluation verification

These results concern the earlier Context Lab experiments. The current Order Integrity application and its separate verification are described in [QUALITY.md](../docs/QUALITY.md).

## GPT-OSS 120B configuration

The `gpt-oss120b-routing-v21-20261105` experiment completed all 90 planned observations through Amazon Bedrock, with prompt 2.1.0 and fixed generation settings. On its ten reporting variants, the purpose-specific configuration scored 10/10 actions and valid outputs, 1.00 missing-evidence F1 and zero unrelated input fields. Full context had one invalid response. Original outputs, including that failure, remain intact. [Results and limitations](experiments/gpt-oss120b-routing-v21-20261105/RESULTS.md).

## Earlier Qwen3 Next Bedrock configuration

The `qwen3-next-bedrock-20261104` experiment completed 90 planned observations. The purpose-specific reporting result was 5/10 actions, 9/10 valid outputs and 0.45 missing-evidence F1; its fixed workflow gates failed. The reporting fixtures were reused and were not unseen independent adjudication. [Original results](experiments/qwen3-next-bedrock-20261104/RESULTS.md).

## Original local evaluation

The local Qwen2.5 3B evaluation completed 90 generations across 30 synthetic fixtures and three context modes. On the ten reporting cases it selected the reference action in 2/10 cases in every mode. The purpose view excluded the eight unrelated fields and retained the 22 structured task facts; this did not establish operational readiness. Full-context outputs reproduced a synthetic email and loyalty identifier in individual cases. No exact protected-value reproduction was observed in the purpose outputs, a narrow exact-match result rather than a privacy guarantee. [Dataset and protocol](../data/DATASET.md), [measured results](RESULTS.md).

## Reproducibility and limits

All datasets, protocols, original benchmark outputs and known failures remain preserved. The suite compares 270 Python/Worker projections and exact provider requests across the three complete configurations. Tests exercise recordings with provider credentials unavailable and fresh calls disabled.

The reference labels and synthetic cases used coding assistance and are not independently human-adjudicated or blinded. Scores are fixed project-gate observations, not PayPal decisions, merchant accuracy, legal compliance or evidence of production suitability. The original Qwen model's research licence and current model/service terms remain documented in [THIRD_PARTY.md](../THIRD_PARTY.md); no model weights are distributed.
