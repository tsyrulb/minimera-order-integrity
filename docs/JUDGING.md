# Minimera judge walkthrough

Change an already paid order from New York to Boston, remove the travel pouch, and follow the approvals, refund, replacement payment and corrected fulfillment order. The interactive walkthrough takes about three minutes after setup.

## Open the hosted demo

Open **[https://minimera.onrender.com](https://minimera.onrender.com)** and select **Explore a safe change**. No installation, account or credentials are needed. The hosted mode uses the same payment simulator and labelled recorded Bedrock responses described below.

Render Free services can take about a minute to wake after idle. Their local SQLite data resets on a service restart; start a new example if an older synthetic workspace is unavailable. The local run option below provides a separate reproducible setup.

On 11 November, this actual public HTTPS build passed **44 core browser checks on 12 audited desktop/mobile screens**, including separate buyer/merchant sessions, the complete refund/replacement/release lifecycle, Studio, evidence verification and blocked changes. Client reload was checked; a server restart and local fault-injection cases were not repeated on the public Free service.

## Try the approval challenge first

From a fresh welcome screen, click **Test an outdated approval**. Compare the Boston request with the original New York payment. Click **Approve this plan**, then **What if the warehouse ships now?** in the payment panel. The outcome at the top shows **Warehouse changed after approval**, **Not sent** for the refund and **Not captured** for the replacement. This is a controlled simulation, not an actual warehouse incident.

Choose **Explore scenarios → A safe change** to try the full successful path below. The challenge and each new example keep separate evidence.

## Start the application

Use Linux or WSL, with Python 3.10+, Node.js 22.12+ and npm. Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix ui --no-audit --no-fund
npm run build --prefix ui
.venv/bin/python scripts/serve_order_integrity.py
```

Open **http://127.0.0.1:8766** and keep that hostname throughout the walkthrough. Leave the terminal running. Dependencies need internet access during installation; the default running application needs no account, API keys, model downloads or external service calls.

The default payment provider is a durable local simulator. AI explanations replay actual AWS Bedrock responses and are labelled **Recorded Bedrock response**. The merchant order and warehouse are synthetic. This mode exercises the complete application workflow without asking judges for credentials.

## Follow the complete change

1. Click **Explore a safe change**. The paid order is **$120.00**, with a tote and pouch going to New York. The request removes the pouch and changes the destination to Boston. Fulfillment is held; the replacement total is **$84.00**.
2. Click **See the 7 facts sent to the model**. Inspect the exact context and click **Show cited fact F5**. Payment state, fulfillment state, change flags and PayPal constraints reach the model; customer names, full addresses, messages and payment IDs are excluded. Press Escape to return.
3. Open **Operations studio**. The comparison widget, decision widget and event grid reflect this order. Click **Explain this decision**. Try **Arrange dashboard**, then **Finish arranging**. The analyst explains the plan; payment actions stay in the order workflow.
4. Return to **Order integrity** and click **Approve this plan**. This saves the merchant's approval of that exact snapshot. It does not refund or charge anything yet.
5. Click **Continue as buyer**, then **Approve replacement · Simulation**. The buyer sees a **$120.00 refund**, a separate **$84.00 payment**, and a **$36.00 difference**. Wait for **Your change is confirmed.**
6. Click **Review the merchant result**, then **Release corrected order**. The result is **Corrected order queued**. The corrected order contains the tote only, addressed to Boston. The original capture is refunded; the new capture is completed.
7. Open **Evidence trail** and click **Download evidence**. The JSON contains both payment legs, their separate IDs, the approved snapshot, corrected warehouse manifest and ordered event hashes.

For an independent buyer session, open the **Continue as buyer** link in a private window. After approving, return to the original merchant tab to release the order. The private buyer window has no merchant session; following its merchant link opens a new visitor's welcome screen.

Refreshing the page or restarting the server preserves the current session and saved workflow. To repeat from the beginning, choose **Explore scenarios → A safe change**. Each example creates a separate workspace; no database deletion is needed.

## Try the blocked changes

| Action | Expected result |
| --- | --- |
| **Explore scenarios → Already shipped** | **Order already shipped**; no automatic approval, refund or replacement payment. |
| **Explore scenarios → The order changed**, approve the plan, then **What if the warehouse ships now?** | **Approval no longer valid**; the old approval cannot start checkout or move money. |

## Run the same walkthrough automatically

Stop the manual server if desired; the verifier uses its own loopback server on port 8767 and creates temporary state. Install the browser tools once:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/verify_judge_demo.py
```

The verifier clicks through the real interface using separate merchant and buyer browser sessions. It also checks rejected cross-role actions, duplicate checkout completion, server restart, independent visitors, exported payment amounts and IDs, recomputed event hashes, AG Studio, mobile screens and blocked changes. It saves screenshots and a JSON report under `runtime/judge-demo/`, then stops its browser and server. A failure returns a nonzero exit code. If port 8767 is in use, add `--port 8768`.

On **10 November 2026**, the expanded QA walkthrough passed **46 checks on nine audited screens** in the local build and default Docker image. It includes delayed responses for both roles, startup errors, checkout cancellation and continuation, connection recovery, Studio module failure and reload, keyboard scrolling through a longer analyst conversation and all three supported question intents.

The current challenge-first revision passes **50 checks** in both the local walkthrough and the clean CI container, including a real container restart. After building it, run `.venv/bin/python scripts/verify_container_demo.py --image minimera:demo` to repeat that check. The patched repository suite passes **210 tests**. Install the UI dependencies before verification: the automated accessibility engine must be available. [Container instructions](DEPLOYMENT.md), [verification scope](QUALITY.md).

## Test actual PayPal Sandbox calls

The default walkthrough does not contact PayPal. For new Sandbox payments, follow [PayPal Sandbox setup](ORDER_INTEGRITY.md#paypal-sandbox), supply your own Sandbox app credentials through the local setup form, and start the server with `--sandbox`. The original test payment is **$1.00**; its replacement is **$0.70**. Buyer approval takes place on PayPal's Sandbox checkout. Real payment endpoints cannot be selected by this adapter.

The existing actual Sandbox lifecycle was independently read back on **10 November 2026**: the original full refund completed, a distinct replacement capture completed, and the corrected synthetic warehouse order was released. This is separate evidence from the simulator walkthrough. Fresh AI inference is also optional and requires explicitly enabling Bedrock with the operator's AWS credentials.

## AG Studio evaluation and scope

AG Studio is a commercial dependency. A clean source checkout does not include the entrant's local trial key, so the vendor may display evaluation diagnostics. The walkthrough remains usable locally. An issued Studio key can be configured through `ui/.env.local` using [the documented licence setting](ORDER_INTEGRITY.md#ag-studio-trial-licence), followed by a rebuild. No PayPal or AWS secret belongs in that browser setting.

The analyst recommends and explains; deterministic checks and both user approvals govern payment execution. Refund and capture are separate operations. This prototype does not guarantee Seller Protection, certify compliance, or connect to a real warehouse. Its local event hash chain is not an external attestation or an immutable ledger.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Node version or Vite engine error | Use Node.js 22.12+ and rerun `npm ci --prefix ui`. |
| Page says `UI_BUILD_REQUIRED` | Run `npm run build --prefix ui`, then restart the Python server. |
| Port 8766 is in use | Stop the other preview or run `scripts/serve_order_integrity.py --port 8768` and use `http://127.0.0.1:8768`. |
| Buyer window cannot open the merchant result | Return to the original merchant browser session. |
| Browser automation says Chromium is missing | Run `.venv/bin/python -m playwright install chromium`; follow Playwright's package instructions if the OS lacks browser libraries. |
| First Studio visit takes longer | Its vendor code loads on demand. The primary order workflow loads separately. |
