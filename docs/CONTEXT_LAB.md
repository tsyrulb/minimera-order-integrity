# Historical Context Lab evaluations

The current application is **Order Integrity**. The `ntk` package also retains an earlier context-minimization research prototype and its fixed datasets, original model outputs, protocols and measured failures. They are retained for reproducibility and Python/Worker parity; their scores are not merchant-accuracy claims for the current workflow.

The original local Qwen2.5 3B experiment selected the reference action on 2/10 reporting cases in each context mode. An earlier Qwen3 Next Bedrock experiment scored 5/10 actions in its purpose-specific mode and failed its workflow gates. The later GPT-OSS 120B configuration met the fixed synthetic gates on its reporting variants. The fixtures were developed with coding assistance and are not independently human-adjudicated or blinded. See [historical verification](../reports/VERIFICATION.md), [results](../reports/RESULTS.md) and the individual experiment reports.

No model weights are distributed. Model/service terms remain in [THIRD_PARTY.md](../THIRD_PARTY.md). The current Order Integrity reviewer uses the separately versioned seven-fact prompt and recorded answers described in [ORDER_INTEGRITY.md](ORDER_INTEGRITY.md).

## Inspect the historical application

After installing the Python requirements:

```bash
.venv/bin/python scripts/serve_demo.py
```

Open **http://127.0.0.1:8765**. Recorded playback does not require provider credentials. Fresh inference is explicit; use the standard AWS credential chain and the existing named-experiment tooling when creating a new run. Never alter a retained prompt, dataset or original output to make an old experiment appear successful.

[Historical read-only PayPal setup](PAYPAL_SETUP.md) is separate from Order Integrity's refund/replacement adapter. The normalized Sandbox observations contain allowlisted business facts, not raw buyer profiles or messages.

## Reproduce checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/check.py
```

The suite checks immutable recording identities, context projections, exact provider requests, no reference-label leakage, offline adapters, cancellation and persistence. Three complete configurations contribute 270 Python/Worker comparisons. Tests do not contact live providers or load a model. Passing these project checks does not establish production validity, anonymity or legal compliance.
