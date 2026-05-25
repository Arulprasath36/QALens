FROM node:18-bookworm-slim@sha256:f9ab18e354e6855ae56ef2b290dd225c1e51a564f87584b9bd21dd651838830e AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend ./frontend
RUN mkdir -p src/qalens/server/static \
    && cd frontend \
    && npm run build


FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/qalens

COPY pyproject.toml README.md LICENSE hatch_build.py ./
COPY src ./src
COPY --from=frontend-build /build/src/qalens/server/static ./src/qalens/server/static

RUN QALENS_SKIP_FRONTEND_BUILD=1 python -m pip install --no-cache-dir . \
    && groupadd --system qalens \
    && useradd --system --gid qalens --home-dir /data --create-home qalens \
    && mkdir -p /data \
    && chown -R qalens:qalens /data

USER qalens
WORKDIR /data

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"

ENTRYPOINT ["qalens"]
CMD ["serve", "--db", "/data/qalens.db", "--config", "/data/config.toml", "--host", "0.0.0.0", "--port", "8080", "--no-open", "--allow-public-bind"]
