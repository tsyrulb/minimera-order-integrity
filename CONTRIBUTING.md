# Engineering guide for Minimera

Minimera separates deterministic context policy from integrations and evidence storage. Changes should keep that boundary easy to inspect, preserve recorded experiments and make behavior testable without payment accounts or model inference.

## Structure

| Modules | Responsibility |
| --- | --- |
| `app.py` | Compose an application and create its service during FastAPI lifespan. |
| `api.py` | Validate HTTP input, call the service and format HTTP responses. |
| `security.py` | Bound HTTP requests and attach response headers through ASGI. |
| `service.py` | Coordinate analysis, replay and PayPal refresh; own workflow state. |
| `model.py`, `bedrock.py`, `paypal.py` | Call external services and validate their responses. |
| `gateway.py`, `model_requests.py` | Define the model interface, shared generation lock, validation and provider request construction. |
| `experiments.py` | Fix named protocols before inference, resume observations and verify results. |
| `prompts.py`, `recorded.py` | Keep task versions immutable and reconstruct exact recorded settings. |
| `reference.py` | Evaluate synthetic reference labels; never used by inference or projection. |
| `storage.py` | Read recorded evidence and atomically persist runtime results. |
| `policy.py` | Project structured facts with deterministic field decisions and hashes. |
| `evaluation.py`, `review.py` | Measure fixture results and apply narrow draft checks. |
| `contracts.py`, `dataset.py` | Define data shapes and validate the fixed fixtures. |
| `config.py`, `secrets.py` | Snapshot operator settings and read private credential files. |

HTTP handlers depend on the application service. The service receives a model gateway, sandbox reader and evidence store through its constructor. The policy, evaluation and review functions perform no HTTP calls, environment reads or filesystem writes.

## Order Integrity boundaries

The current application lives in `ntk/integrity/`. Its `app.py` composes dependencies, `api.py` owns HTTP and role checks, and `service.py` coordinates the ordered workflow. `policy.py` contains the deterministic decisions, projections and resource bindings; its `now()` helper supplies observation timestamps. `store.py` owns SQLite persistence, optimistic revisions and durable dispatch claims.

The coordinator accepts the structural `Reviewer` and `Gateway` interfaces. The concrete `Analyst` implements recorded and fresh AI review; `Sandbox` and `Simulator` implement the shared payment operations. Simulation-only approval belongs to `Simulator` and is excluded from the payment interface. Keep the single-process store concrete until a real storage variation needs another implementation.

Capture returns its independently verified payment observation. The workflow must retain that observation rather than overwrite it with an unchecked extra read. Every refund check binds the resource identity, parent capture, amount, currency and source. Warehouse release also binds the corrected record's payment to the verified replacement.

In `ui/src/`, `api.ts` owns HTTP transport and typed `ApiError` failures; `types.ts` describes application data. Both role views ignore older revisions arriving after a newer saved state. Only the expected missing-session response is treated as an empty workspace. `StudioBoundary` contains module/render failures so that the rest of the merchant workflow remains usable.

## Abstraction and object design

Use classes when configuration, state or a resource lifetime belongs to an instance. Use functions for deterministic transformations. The model and sandbox clients implement structural `Protocol` interfaces; callers depend on their operations rather than their concrete implementation. The filesystem store remains a concrete class for the current storage implementation.

Prefer composition and small, cohesive responsibilities. Add an abstraction when a current variation or testing boundary needs it. A proposed class or interface should make a concrete caller easier to understand. Keep dependencies visible in constructors and function arguments. Avoid service locators, hidden mutable registries and speculative provider frameworks.

Application instances must have independent settings, cases, refresh cooldowns and rate limits. Importing `ntk.app` must not read fixtures, create runtime files, contact PayPal or start a model. Lifespan initializes the service; request-scoped clients and generation locks have explicit cleanup.

## Types and configuration

The production Python package passes strict mypy checking. `TypedDict` contracts describe facts, cases and projections; Pydantic validates API input, synthetic dataset structure and generated analyses at runtime. `JsonObject` explicitly permits heterogeneous provider envelopes and versioned evidence reports. Type annotations alone do not validate external JSON.

Settings are frozen dataclasses created from an explicit environment snapshot. Existing instances must not change provider when another instance or test changes environment variables. Model requests are constructed from explicit settings; the default request builder preserves the recorded Ollama experiment independently of the operator environment.

Use descriptive names, explicit return types and UTF-8 for persisted JSON. Ruff owns formatting and import order. The project uses a 100-character formatting target, subject to long literal strings that must retain their exact bytes. Add docstrings for public behavior and non-obvious constraints; explain why a boundary exists.

## Errors and credentials

Raise explicit exceptions for runtime input and evidence validation. Reserve `assert` for tests and internal debugging assumptions. Handle expected adapter failures through safe `AppError` codes and messages; retain refresh failure status in health while keeping the last saved observation visible.

Every path that acquires a generation lock must release it. A cancelled or memory-limited request must cancel its owned HTTP task before its client closes and attempt to unload only the configured local model. Preserve memory checks before loading and during local inference.

Bedrock uses the standard AWS credential chain and botocore SigV4 signing with bounded async HTTP requests. Cancellation closes the owned request and releases the lock. Reserve its persistent request allowance before sending; failures and cancellation still consume an attempt. Fresh inference is opt-in, and inspecting recorded evidence must not resolve AWS credentials. Never repair a rejected model answer to make an experiment appear successful.

Named experiments have separate report and runtime directories. Fix all planned request hashes before generation and reject incompatible resumes. The original protocol, dataset and benchmark remain unchanged. Bedrock's evidence hashes the explicit operation, region, model ID and body envelope; it excludes authentication headers. Model identifiers and request hashes are provenance, not execution attestation.

A completed experiment must validate its unique planned observations and summary without rewriting files or invoking a provider. A new dataset is selected explicitly and must remain under public `data/` when bundled. Recorded configuration reconstruction must preserve operator settings without resolving credentials. GPT-OSS reasoning effort and generation ceilings are part of the protocol; provider reasoning text is excluded from evidence.

Prompt 2.1.0 uses worked examples from development cases only. The provider envelope renames per-fact provenance `source` to `record_origin`, preserving all selected IDs, values and metadata. The canonical policy projection stays unchanged; Python/Worker tests check the exact transformed request as well as the projection. Do not tune on the new reporting outputs or quietly replace a failed candidate.

Keep credentials in server configuration or owner-only regular files. Reject symlinks, special files, unexpected keys, duplicate keys and oversized credential files. Do not log authentication headers, reflect submitted input in validation errors, embed credentials in the Worker, or persist raw PayPal profiles and messages.

Use unique temporary files for atomic JSON replacement. A failed write must retain the preceding report and remove its temporary file. Return independent copies of indexed recordings so callers cannot mutate evidence served to another request.

## Verification

Install Python dependencies in a virtual environment and use Node.js 22 or later for Worker checks:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/check.py
```

The command runs Ruff lint and format checks, strict mypy, pytest, JavaScript syntax checks, local Worker builds and all 90 Python/Worker projection and provider-request comparisons for the baseline and each complete experiment, sequentially. It stops on the first failure. The Worker check loads generated ESM directly and does not require the ignored hosting checkout. CI runs the same command on Python 3.12 and Node.js 22.

Tests use synthetic fixtures and injected HTTP transports. Add regression tests for privacy boundaries, invalid provider output, cancellation, cache compatibility and persistence failure when those behaviors change. Prefer observable outcomes over assertions about private implementation details. Tests must not call live payment APIs, load models or rewrite checked-in experiment reports.

After UI or workflow changes, build the interface and run `python scripts/verify_judge_demo.py`. It includes delayed responses for both roles, startup errors, checkout cancellation, reconnection and Studio module failure, as well as the complete judge journey. Install the UI dependencies first: its accessibility checks require `axe-core` and fail if it is absent. `python scripts/verify_container_demo.py --image <local-image>` runs the same checks in a locally built container. These verifiers own their test servers and temporary state.

Check available memory before browser checks or other substantial local jobs. Keep heavy work sequential on this host. A successful unit suite does not require loading the 3B model.

The recorded dataset, protocol and original model outputs are experimental artifacts. Changing policy behavior, prompt bytes or model identity requires a separately identified experiment and an explicit compatibility-test update. Preserve the original files and their provenance. The current workflow quality gates and measured failures remain part of the result.

## Reference guidance

These sources inform the project rules; the module boundaries and tool settings above are project decisions.

- [PEP 8](https://peps.python.org/pep-0008/): readable, consistent Python and explicit public interfaces; preserve compatibility when applying style changes.
- [PEP 20](https://peps.python.org/pep-0020/): simple, explicit design and visible failures.
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html): avoid mutable global state, use precise exception handling, annotate code and manage resources explicitly.
- [Martin Fowler on YAGNI](https://martinfowler.com/bliki/Yagni.html): implement current requirements and keep the code easy to change through refactoring.
- [Python protocols](https://docs.python.org/3/library/typing.html#typing.Protocol): describe interchangeable behavior through structural typing.
- [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) and [lifespan](https://fastapi.tiangolo.com/advanced/events/): make dependencies and startup responsibilities explicit.
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/) and [mypy configuration](https://mypy.readthedocs.io/en/stable/config_file.html): reproducible style and static checking.
- [GitHub Python CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/python): install declared dependencies and run the repository checks in automation.
