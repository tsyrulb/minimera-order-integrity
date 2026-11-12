# Recorded evaluation

30 developer-authored synthetic fixtures with AI assistance; 20 development, 10 fixed heldout. Same model, prompt, options; only context changes. Mode order rotates across cases. Labels are never sent to the model. Failed generations count as incorrect. Not independently blinded; no claims of generalization.

Model: `qwen2.5:3b`. Dataset SHA-256: `72e320092dd2530be427c096844c97b0dd815f8c7aec78f5ae02ad8e3335d40c`.

| Split | Context | Action accuracy | Missing evidence F1 | Unrelated fields sent | Valid outputs |
| --- | --- | ---: | ---: | ---: | ---: |
| development | full | 7/20 | 0.164 | 8.0 | 20/20 |
| development | masked | 8/20 | 0.200 | 3.0 | 20/20 |
| development | purpose | 8/20 | 0.183 | 0.0 | 20/20 |
| heldout | full | 2/10 | 0.100 | 8.0 | 10/10 |
| heldout | masked | 2/10 | 0.100 | 3.0 | 10/10 |
| heldout | purpose | 2/10 | 0.100 | 0.0 | 10/10 |
| all | full | 9/30 | 0.143 | 8.0 | 30/30 |
| all | masked | 10/30 | 0.167 | 3.0 | 30/30 |
| all | purpose | 10/30 | 0.156 | 0.0 | 30/30 |

The fixed fixture gates are not met. Do not infer that this model and policy are ready for operational use.

Raw outputs, citation coverage, exact-value checks, all failures, settings and exact requests are included in benchmark.json. Review patterns were applied after generation; no model response was rewritten.
