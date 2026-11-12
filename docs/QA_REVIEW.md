> Current release: 210 Python tests and the patched dependency stack. Earlier dated QA observations below are retained as technical history. See [QUALITY.md](QUALITY.md).

# Minimera QA and architecture review

**11 November challenge-first update:** the current source passed 50 local judge checks and 44 core checks against the actual Render deployment, including 12 desktop/mobile audits. TypeScript, formatting, production build, 207 Python tests, strict mypy and 270 Python/Worker comparisons passed. The challenge control is checked for visibility without scrolling. New display checks cover verified financial outcomes and the untouched payment legs after stale approval. A newly filmed actual Sandbox lifecycle passed 27 independent saved-evidence checks, including provider refund-read-before-capture order. Bedrock recordings are preserved; no new model calls were made for filming. The public check exercises client reload; local restart and injected faults remain separate. [Current verification](../reports/order-integrity-v1/challenge-first-verification-20261111.json).

Reviewed on **10 November 2026**. The active Order Integrity application passes the documented local demo after the corrections below: **207 Python tests and 46 browser checks**, with the browser checks repeated in Docker. The architecture is suitable for the current single-process prototype. A production merchant service would need the integrations and operating controls listed below.

The review covered workflow transitions, payment bindings, AI recording and concurrency, role boundaries, frontend refresh behavior, failure recovery and packaging. Faults were reproduced with synthetic gateways and controlled browser responses. The earlier actual Sandbox and Bedrock rehearsal remains separate evidence; this QA made no new provider requests and retained the original model recordings.

## Corrected defects

The initial 194-test suite passed before this review. Thirteen new backend cases exposed missing guards and resilience behavior before their fixes. Browser fault cases also reproduced stale display state and a failed Studio import.

| Priority | Finding | Correction |
| --- | --- | --- |
| P1 correctness | Warehouse release checked items and destination but could accept a corrected record attached to the refunded original payment. Its last refund check also omitted refund identity and source. | Release binds the corrected order ID and payment to the verified replacement, checks the complete refund binding, and retains the final provider observations. |
| P1 correctness | After verifying the original capture, a redundant unchecked read could overwrite that verified payment. | Capture returns its verified observation; original and replacement flows retain that result. |
| P2 cost and evidence | Concurrent identical AI contexts could both invoke the model. Replay checked the request but accepted inconsistent advice metadata. | Recheck the recording after acquiring the generation lock. Validate the advice request hash, model, prompt version, original source and policy agreement before replay. |
| P2 provider resilience | Null or malformed nested model envelopes could raise an uncaught attribute error. | Validate envelope structure before extracting text and return the existing safe AI error. Reasoning blocks remain excluded. |
| P2 display correctness | Delayed polling could overwrite a newer merchant approval or buyer completion. Startup storage errors were silently discarded. | Both role views reject older revisions. Typed API errors distinguish an expected absent session from a failed startup. |
| P2 UI recovery | A failed Studio module could remove the whole merchant interface. | A Studio error boundary keeps navigation and saved order state usable, with a verified reload path. |
| P2 delivery performance | Large UI assets were served without compression. | Enable gzip while preserving response security headers and the original decoded bytes. |

These priorities describe correctness and resilience of this prototype. The injected mismatches do not establish an actual incorrect PayPal transaction or shipment.

Payment and model regressions are in [test_integrity_qa.py](../tests/test_integrity_qa.py) and [test_integrity_deployment.py](../tests/test_integrity_deployment.py). Browser fault cases are in [judge_resilience.py](../scripts/judge_resilience.py); both browser runners execute them.

## Programming and object design

| Principle | Current implementation and assessment |
| --- | --- |
| Single responsibility | HTTP and sessions, deterministic policy, provider transports, persistence and workflow coordination occupy separate modules. Frontend HTTP transport now lives in `api.ts`, separate from data types and components. |
| Dependency inversion | `IntegrityService` accepts the narrow structural `Reviewer` and `Gateway` interfaces. Tests replace external providers without changing workflow policy. SQLite remains a concrete store because there is one current storage implementation. |
| Interface segregation | The shared payment interface contains operations supported by both gateways. Simulation approval belongs to `Simulator`; Sandbox does not implement a method that only raises an unsupported-operation error. |
| State and encapsulation | Locks, session keys, provider configuration and storage belong to application instances. Optimistic revisions reject lost updates; persisted dispatch claims prevent blind repetition after unknown outcomes. |
| Appropriate abstraction | Classes own configuration, state or resource lifetime. Deterministic decisions and bindings use functions. Composition and protocols provide the current variations without an inheritance hierarchy. The React error boundary uses a class for its actual lifecycle requirement. |
| Error handling | Boundary validation produces safe errors. Interrupted payment execution records uncertainty and re-raises the failure; it never assumes success. Frontend failures retain their HTTP status and error code. |

`IntegrityService` remains a substantial coordinator because the non-atomic payment sequence has explicit persistence and verification steps. Before adding a second workflow, extract payment execution into a collaborator with the same regression coverage. Some assistant answer selection also remains in the HTTP module and can move into a query/presentation function as that feature expands.

Python and TypeScript contracts are maintained separately; several frontend state fields remain broad strings. Explicit response DTOs and generated TypeScript contracts would reduce drift as the API grows. Strict typing and browser tests currently verify the implemented path; they do not establish complete contract coverage.

## Verification

- **207 Python tests**, Ruff and strict mypy across 35 production modules passed.
- All **270 Python/Worker projection and request comparisons** passed.
- TypeScript, Prettier and production UI builds passed.
- **46 browser checks** passed locally and in the default Docker image, including an actual server/container restart, separate roles, cancellation and continuation, delayed responses, connection recovery and Studio reload.
- Nine audited screens had no automated axe WCAG A/AA violations or horizontal overflow. The completed walkthrough recorded no unhandled browser JavaScript errors or external browser requests. Automated checks are not a complete accessibility assessment.

Repeat from the repository root after installing the documented dependencies:

```bash
.venv/bin/python scripts/check.py
npm run check --prefix ui
npm run build --prefix ui
.venv/bin/python scripts/verify_judge_demo.py
docker build -t minimera:qa .
.venv/bin/python scripts/verify_container_demo.py --image minimera:qa
```

The browser verifier requires the installed `axe-core` dependency and fails when it is absent. Detailed local records are retained under ignored `runtime/qa-20261110/` and `runtime/container-demo/`; the scripts recreate the checks without credentials or live model/payment calls.

## Remaining scope

**Before recording:** use the refreshed build and keep the actual Sandbox source labels visible. The QA defects above are corrected; the previously prepared Sandbox payment and approvals have not been consumed by these tests.

**Before a production merchant pilot:** connect an actual OMS/WMS, add merchant identity and tenant management, define durable deployment/backups, and implement operational reconciliation and monitoring for unknown provider outcomes. SQLite, application locks and session storage currently assume the documented single-process deployment. Hosted preview disables provider-enabled execution.

**Further polish:** Studio remains a large lazy module. The current local server transferred 1,870,119 compressed bytes for its 6,606,139-byte module, a **71.7% reduction**, with identical bytes after decompression. Vendor bundle size still affects first use. Browser verification currently uses Chromium with desktop and mobile viewports, including mobile Studio recovery; Firefox, Safari and physical mobile devices need separate compatibility runs.
