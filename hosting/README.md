# Hosted adapter

`worker-runtime.mjs` is the source of the optional dependency-free hosted API. The Python core remains the primary application and inference/evaluation implementation.

From the repository root, `python3 scripts/build_worker.py` creates `site/worker/index.js`, embedding the canonical UI, fixtures, verified benchmark, normalized sandbox observation and any recorded sandbox model run. The generated Worker is an ES module exporting `default.fetch`; it can be deployed to a compatible Worker host. The ignored `site/` directory is a separate deployment checkout, not a required submodule. Its existing opaque hosting identity is preserved.

`node tests/check_worker.mjs` compares all 90 context projections, including exact payload hashes and metrics, against the Python implementation. It also checks boundary behavior and recorded-run provenance. Regenerate the Worker after changing canonical source. `--allow-partial` is for local development while the benchmark is running; default builds refuse incomplete evaluation evidence.

Configure PayPal sandbox secrets on the host, using the same variable names as `.env.example`. They never belong in the generated source. The hosted adapter permits only OAuth and GET requests to a fixed PayPal sandbox origin. Unknown response fields, profiles and free text are excluded.

Fresh hosted inference is disabled by default. With an operator-configured `NTK_OPENAI_API_KEY`, a model snapshot ID in `NTK_CLOUD_MODEL`, and `NTK_ENABLE_PUBLIC_FRESH=true`, it can use the Responses API. Configure appropriate account spending controls and a persistent deployment-wide quota before enabling anonymous paid inference; the in-memory per-isolate throttle is only an additional control. Recorded baseline runs remain clearly labelled and require no provider key.

The adapter's local observation and throttle state are isolate-local. Repeated requests may reach different isolates. Recorded sandbox data always carries its original timestamp; use a durable store before treating this as a production merchant service.
