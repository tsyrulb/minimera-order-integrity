# Security policy

Minimera is a personal hackathon prototype maintained by [Borys Tsyrulnikov](https://github.com/tsyrulb). The latest `main` revision is the supported demonstration version. It is not a production payment service or a compliance certification.

## Report privately

Use **Security → Report a vulnerability** on GitHub when that option is available. Do not post exploit details, credentials, personal information or payment data in public issues or pull requests.

If private reporting is unavailable, open an issue containing only **Private security contact requested** so the maintainer can arrange a private channel. Include no vulnerability details in that contact request. This project does not offer a bug bounty or promise a response deadline.

A private report should identify the affected revision, reproduction steps using synthetic fixtures, expected and observed behavior, and the relevant role or payment boundary. Use PayPal Sandbox test funds only; do not test real merchant accounts or real money.

## Demonstration boundaries

- Public judge mode uses simulated payments, synthetic merchant/warehouse records and actual recorded Bedrock responses. It has no PayPal or AWS credentials.
- Sandbox writes and fresh model calls require an explicitly configured, loopback-only operator preview. They are excluded from CI.
- Merchant approval is bound to an order snapshot; buyer approval is a separate capability. Unknown payment outcomes keep fulfillment held for reconciliation.
- The event hash chain is recomputable local review evidence. It is not external attestation or proof of an immutable ledger.
- GitHub source and CI must exclude private environment files, runtime databases, checkout footage and the entrant's AG Studio setting. A browser licence configured on the hosted demo is intentionally visible to that browser SDK.

Dependency advisories are checked with `pip-audit` and `npm audit`; CI scans Git history with Gitleaks. Passing automated checks does not establish that all vulnerabilities have been found. [Architecture and trust boundaries](docs/ARCHITECTURE.md).
