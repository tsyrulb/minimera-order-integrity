# Verification scope

The current Order Integrity runtime has passed 210 Python tests, Ruff lint/format checks and strict mypy over 35 modules. Historical fixed experiments contribute 270 Python/Worker projection and provider-request comparisons. Ordinary checks use synthetic fixtures, injected transports and original recordings without calling live providers.

The reusable browser verifier runs 50 assertions against the actual built interface: separate merchant/buyer sessions, role rejection, delayed responses, cancellation and continuation, reconnect, Studio failure recovery, exact approval binding, duplicate callback behavior, verified refund/replacement outcomes, corrected release, evidence hashes, responsive layout and automated accessibility checks. The same journey runs in Docker, including a real container restart.

The hosted Render mode separately passed 44 core checks on 12 audited desktop/mobile screens. It uses simulated payments and recorded AI. Client reload was checked on that hosted service; it is separate from isolated restart and fault-injection evidence.

An actual PayPal Sandbox sequence completed a $1.00 refund, distinct $0.70 capture and corrected synthetic warehouse release. Its saved evidence passed 27 checks, including independent provider read order and exact model request fingerprint. Actual Sandbox evidence is separate from the synthetic unit/UI tests. The final video uses original recorded Bedrock advice and made no fresh model calls during filming.

Run `python scripts/check.py` after installing `requirements-dev.txt`. For browser checks, first install/build the UI and install Playwright Chromium; then run `python scripts/verify_judge_demo.py`. CI uses Python 3.12, Node.js 22.22.0 and Ubuntu 24.04, builds the UI/container, runs both journeys, audits dependencies and scans Git history. No provider credentials or issued Studio licence are required by CI.

Testing is not a security or accessibility certification. Browser coverage uses Chromium with desktop/mobile viewports; it does not establish behavior on every physical device or browser. Merchant savings and production accuracy have not been measured. The historical model failures and dataset limitations remain preserved in [Context Lab](CONTEXT_LAB.md).
