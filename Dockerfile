FROM node:18-bookworm-slim@sha256:f9ab18e354e6855ae56ef2b290dd225c1e51a564f87584b9bd21dd651838830e AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend ./frontend
RUN mkdir -p src/qalens/server/static \
    && cd frontend \
    && npm run build


FROM cgr.dev/chainguard/python:latest-dev@sha256:ddd3811dcbef56aa9f3882ae16fdc2920174ac6028c12e76cfb64c1d37b7abe2 AS python-build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

USER root
WORKDIR /opt/qalens

COPY pyproject.toml README.md LICENSE hatch_build.py ./
COPY src ./src
COPY --from=frontend-build /build/src/qalens/server/static ./src/qalens/server/static

RUN python -m venv "$VIRTUAL_ENV" \
    && python -m pip install --upgrade pip \
    && QALENS_SKIP_FRONTEND_BUILD=1 python -m pip install --no-cache-dir . \
    && python -m pip uninstall --yes pip setuptools wheel \
    && mkdir -p /data


FROM cgr.dev/chainguard/python:latest@sha256:30ac20a34bae29023ae54b454e85fedb5cfb7de5f206dc73112bf8b0e3e3e190 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build --chown=65532:65532 /data /data

USER 65532:65532
WORKDIR /data

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"]

ENTRYPOINT ["/opt/venv/bin/qalens"]
CMD ["serve", "--db", "/data/qalens.db", "--config", "/data/config.toml", "--host", "0.0.0.0", "--port", "8080", "--no-open", "--allow-public-bind"]
