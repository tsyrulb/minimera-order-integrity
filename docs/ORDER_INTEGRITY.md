# Order Integrity: workflow and provider setup

Minimera coordinates a post-payment destination change with optional item removal. The merchant and warehouse systems are synthetic. Default operation uses a durable payment simulator and validated original Bedrock recordings. The public and local interfaces label those sources explicitly.

## Workflow

1. Hold fulfillment and compare the request with the paid order.
2. Obtain a scoped AI explanation and inspect its seven facts/citations.
3. Bind merchant approval to the exact snapshot, with a bounded expiry.
4. Obtain separate buyer approval of the replacement.
5. Refund the original capture and independently verify its resource identity, parent capture, amount, currency, source and completed status.
6. Capture and independently verify the distinct replacement payment.
7. Prepare a corrected fulfillment record; the merchant releases it after another binding check.

A changed warehouse state invalidates an earlier approval. A refund and replacement capture are separate operations. A timeout or unknown outcome does not establish failure or permission to dispatch again; committed claims and observations retain the incomplete sequence for reconciliation.

For a guided evaluation, follow [JUDGING.md](JUDGING.md). Installation and container commands are in [README](../README.md).

## PayPal Sandbox

The adapter uses PayPal Orders and Payments APIs. Actual Sandbox tests completed a full **$1.00 refund**, a distinct **$0.70 capture** and corrected synthetic fulfillment release after independent provider reads. Test funds are separate from the public simulator's **$120/$84** example.

To configure your own Sandbox application locally:

```bash
.venv/bin/python scripts/connect_paypal.py
```

The single-use loopback setup form verifies Sandbox OAuth and writes an owner-only, ignored credential file. Do not commit that file. Then start the provider-enabled preview:

```bash
NTK_PAYPAL_ENV_FILE="$PWD/private/paypal-sandbox.env" \
  .venv/bin/python scripts/serve_order_integrity.py --sandbox
```

Open **http://127.0.0.1:8766**. Create an example, select its Sandbox option, and approve the original test payment using your Sandbox buyer or officially generated test card. Submit the customer request, approve as merchant, continue as buyer, approve the replacement, verify both payment legs and release the corrected order. Real-money endpoints cannot be selected by this adapter.

Provider-enabled listening is restricted to loopback. The public-hosted mode does not enable Sandbox writes. Gross order totals exclude processing fees and taxes. A verified refund may take longer to become available through the buyer's bank; a failed replacement after refund keeps fulfillment held.

## AI and data minimization

The Bedrock reviewer uses `openai.gpt-oss-120b-1:0`, prompt `order-change-plan/1.2.0`, and a validated JSON output contract. Its seven facts describe original payment status, fulfillment state, destination/total change flags and documented payment constraints. Names, full addresses, messages, payment IDs and approval capabilities are outside that request. The server still processes the order data needed for the workflow.

Recorded responses retain their exact request fingerprint and provider provenance. Replay is labelled. Invalid responses are rejected rather than repaired into a successful experiment. AI has no approval or payment-dispatch capability.

Fresh inference is optional and uses the operator's standard AWS credential chain. Enable it only in an explicit local preview with a separate recording directory:

```bash
.venv/bin/python scripts/serve_order_integrity.py \
  --fresh-ai --recordings-dir runtime/local-bedrock-review
```

The named directory separates new responses from the preserved source recordings. Ordinary setup, tests and the public judge journey do not resolve AWS credentials or call a model.

## AG Studio trial licence

The interface uses `ag-studio` and `ag-studio-react` 3.1.0: two custom React widgets, a built-in event grid, theming, editable/responsive layouts and the Studio Agent Framework. The custom analyst supports explanation, model-data inspection and next-step intents. Free text stays in the browser; only an allowlisted intent reaches the server. Payment controls remain in the merchant workflow.

A clean source build uses vendor evaluation mode. To configure your own valid Studio setting, use the ignored `ui/.env.local` documented by `ui/.env.example`, then rebuild the UI. Only `VITE_AG_STUDIO_LICENSE_KEY` belongs in that file. No issued licence is distributed in source. The SDK intentionally reads a browser licence from the built interface; PayPal and AWS credentials must remain server-side.

The built-in Studio grid is covered by Studio's terms. Separate standalone Enterprise instances require their own applicable licences. This repository's MIT licence does not relicense vendor dependencies. [Official licence installation](https://www.ag-grid.com/studio/react/licence-install/), [third-party terms](../THIRD_PARTY.md).

## Verification and scope

The current workflow passes local, browser and container checks described in [QUALITY.md](QUALITY.md). Independent buyer sessions cannot approve merchant actions. Duplicate callbacks preserve the same payment resources. Delayed client refreshes cannot overwrite newer revisions. Studio module failures leave the main workflow usable.

The hash chain is independently recomputable local evidence, not an external attestation or immutable ledger. The prototype does not certify compliance, guarantee Seller Protection or integrate with a real merchant warehouse. Production identity, operational reconciliation and actual merchant validation remain future work.
