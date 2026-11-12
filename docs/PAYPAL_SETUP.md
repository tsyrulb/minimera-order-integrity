> Historical Context Lab adapter. For the current Order Integrity Sandbox workflow, see [ORDER_INTEGRITY.md](ORDER_INTEGRITY.md#paypal-sandbox).

# PayPal sandbox: read-only dispute integration

The demonstration reads a synthetic USD 1.00 order, its capture and its linked item-not-received dispute. It does not create, capture, refund or adjudicate transactions. The sandbox response is normalized in the merchant backend before it reaches the interface or model.

For the existing published demonstration, no judge account is needed. A timestamped normalized observation is included with the application. Live refresh is available when the operator configures the sandbox connection. A recorded observation is not presented as a live read.

To connect your own sandbox:

1. Create a PayPal Developer application and Business/Personal sandbox accounts in your own account.
2. Prepare and buyer-approve a USD 1.00 sandbox order with purchase-unit `reference_id: need-to-know-sandbox`. Capture it and separately read back its completed state. No real funds are used in the sandbox.
3. From the sandbox buyer's Resolution Center, open an item-not-received test dispute against that transaction. Sandbox indexing can take time; do not infer that a dispute is absent from one immediate list response.
4. Configure the server-side names in `.env.example`: `NTK_PAYPAL_ORDER_ID`, `NTK_PAYPAL_CAPTURE_ID`, and `NTK_PAYPAL_DISPUTE_ID`. These are fixed operator settings, never browser-provided resource paths.
5. Store `PAYPAL_SANDBOX_CLIENT_ID` and `PAYPAL_SANDBOX_CLIENT_SECRET` as host secrets. For a local file, set `NTK_PAYPAL_ENV_FILE` to an owned, regular, non-symlink file with mode `0600`, containing only those two `KEY=value` lines. Do not paste secrets into chat or commit them.
6. Restart the application. It reads the configured case on startup. Select **Live PayPal sandbox dispute** and use **Refresh PayPal** for another read. The action is rate-limited; it only performs OAuth and GET requests.

If the capture changed after the original payment completed, you may explicitly supply `NTK_COMPLETION_RECORD`, a local JSON observation with the matching order/capture IDs, `status` and `capture_status` equal to `COMPLETED`, `amount: "1.00"`, `currency: "USD"`, and `payment_verified: true`. The application labels this as an **unsigned local observation**, separates it from the current state and does not infer a completed refund.

The adapter refuses another order reference, other amounts, mismatched captures and mismatched dispute IDs. It forwards a bounded allowlist of status, amount, link and deadline facts. Buyer profiles, messages and attachment contents are excluded. Unknown carrier and refund facts remain `null`; no absence claim is manufactured from an omitted PayPal field.

The current shipping workflow assumes this demo's physical test goods. Extend and evaluate its policy before using it for digital services, subscriptions, returns or another dispute reason. Case state, deadlines and evidence requirements may change; records retained for judging show their observation time.

Official references: [PayPal sandbox](https://developer.paypal.com/tools/sandbox/), [Disputes API](https://developer.paypal.com/api/customer-disputes/v1), [Orders API](https://developer.paypal.com/docs/api/orders/v2/).
