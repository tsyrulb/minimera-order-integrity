# syntax=docker/dockerfile:1
FROM node:26.13.0-bookworm-slim@sha256:add5c17c14752c54d2f3d519ec46a3815684d41c33f198bcb09fb998f7dcbf68 AS ui
WORKDIR /build/ui
ENV NODE_OPTIONS=--max-old-space-size=1024
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
ARG WITH_AG_STUDIO_LICENSE=false
RUN --mount=type=secret,id=ag_studio_env,target=/build/ui/.env.local \
    if [ "$WITH_AG_STUDIO_LICENSE" = true ]; then test -s .env.local; else test ! -e .env.local; fi \
    && npm run build

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS app
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
