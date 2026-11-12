# Deployment

The root multi-stage Dockerfile builds the React interface and serves Order Integrity through FastAPI. Default hosting uses simulated payments and labelled original Bedrock recordings. No provider account or keys are needed for that mode.

## Current demonstration

Open **https://minimera.onrender.com**. The Render Free service uses a canonical HTTPS origin and `/api/integrity/health` checks both the built UI and SQLite access. The hosted workflow has been checked using separate merchant/buyer sessions, both simulated payment legs, corrected release, Studio, event hashes and blocked scenarios.

Render Free can take about a minute to wake after idle and uses ephemeral storage. Synthetic workspaces can reset on service restart; start a new example when necessary. Public verification checks client reload. Local/container checks separately cover restart durability. [Render Free limits](https://render.com/docs/free).

## Local Docker

```bash
docker build -t minimera:demo .
docker run --rm --name minimera-demo -p 127.0.0.1:10000:10000 minimera:demo
```

Open **http://127.0.0.1:10000**. Node, npm development dependencies and private/runtime history are excluded from the final image. The application runs as an unprivileged user; SQLite is under `NTK_RUNTIME_DIR`, defaulting to `/app/runtime`. Replacing a container without preserving that directory resets its examples.

With the development requirements installed, run:

```bash
.venv/bin/python scripts/verify_container_demo.py --image minimera:demo
```

The verifier owns a bounded loopback container, runs the complete judge journey including a real container restart, records synthetic diagnostics under the ignored runtime directory, and stops its container afterward.

## Optional Studio setting

A default source build uses evaluation mode. To use your own valid Studio licence:

```bash
docker build --no-cache-filter ui \
  --build-arg WITH_AG_STUDIO_LICENSE=true \
  --secret id=ag_studio_env,src=ui/.env.local \
  -t minimera:licensed-demo .
```

That owner-only file must contain only the supported browser licence setting. BuildKit mounts it during the UI build; the SDK's browser licence intentionally enters the built JavaScript. PayPal and AWS credentials must never enter UI settings. Secret values do not invalidate Docker's cache, so rebuild the UI stage when changing the setting. [Docker build secrets](https://docs.docker.com/build/building/secrets/).

## Hosting configuration

The Render template listens on `0.0.0.0:$PORT`. The launcher derives HTTPS from `RENDER_EXTERNAL_HOSTNAME` or accepts an explicit canonical origin. Callback URLs are never constructed from a visitor's Host header. Non-loopback origins require HTTPS and reject credentials, paths, queries and fragments.

`FORWARDED_ALLOW_IPS=*` is appropriate only for this platform's private container behind its proxy. On another host, set the actual trusted proxy addresses and keep the direct container port private. Public HTTPS sessions use Secure cookies and enforce same-origin requests.

The template does not enable Sandbox writes or fresh Bedrock calls. Provider-enabled previews are loopback-only; follow [provider setup](ORDER_INTEGRITY.md). A production service needs persistent storage, tenant identity and operational reconciliation beyond this prototype.
