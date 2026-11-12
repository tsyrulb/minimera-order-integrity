# Minimera engineering instructions

Read `CONTRIBUTING.md` for architecture, code conventions and verification commands.

- This directory is the standalone Minimera repository. The surrounding workspace contains independent repositories.
- Keep HTTP handling, service workflows, integrations, storage and deterministic policy separate. Inject dependencies; keep runtime state per application instance.
- Preserve the historical `ntk` package name, `NTK_*` configuration, fixture IDs, schema versions and configured sandbox order reference.
- Preserve experimental artifacts. Do not edit model outputs or relax measured workflow gates during a refactor. A new prompt, policy or model experiment must have its own identity and retain original evidence.
- Add meaningful regression tests for security-sensitive changes, cancellation, persistence failure and compatibility boundaries.
- Run `python scripts/check.py` using the environment with the development requirements. The checks run sequentially and use no live API or model inference.
- Check RAM and active processes before substantial local work. Do not run model inference as part of ordinary code checks or run multiple heavy jobs together.
- Keep credentials out of source, reports, error bodies and browser assets. Use synthetic data and injected transports in tests.
