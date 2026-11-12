# syntax=docker/dockerfile:1
FROM node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS ui
WORKDIR /build/ui
ENV NODE_OPTIONS=--max-old-space-size=1024
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
ARG WITH_AG_STUDIO_LICENSE=false
RUN --mount=type=secret,id=ag_studio_env,target=/build/ui/.env.local \
    if [ "$WITH_AG_STUDIO_LICENSE" = true ]; then test -s .env.local; else test ! -e .env.local; fi \
    && npm run build

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ntk ./ntk
COPY data ./data
COPY web ./web
COPY reports/order-integrity-v1/recordings ./reports/order-integrity-v1/recordings
RUN chmod -R a+rX /app/reports/order-integrity-v1/recordings
COPY scripts/serve_order_integrity.py ./scripts/serve_order_integrity.py
COPY --from=ui /build/ui/dist ./ui/dist
COPY LICENSE THIRD_PARTY.md ./
RUN useradd --create-home ntk && mkdir /app/runtime && chown ntk:ntk /app/runtime
USER ntk
ENV NTK_RUNTIME_DIR=/app/runtime
EXPOSE 10000
CMD ["sh", "-c", "exec python scripts/serve_order_integrity.py --host 0.0.0.0 --port \"${PORT:-10000}\""]
