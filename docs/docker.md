# Docker

QA Lens is available as a container image for users who do not want to install Python or Node.js locally. The container includes the CLI, API server, and built web UI.

## Requirements

- A running Docker engine.
- Docker Desktop or Colima is a normal choice on macOS.
- The Docker Compose plugin is required only for the `docker compose` examples.

On macOS, installing the `docker` CLI alone is not enough: it provides commands but not the local engine that builds and runs containers.

## Image

The publishing workflow builds images for `linux/amd64` and `linux/arm64`:

```text
ghcr.io/arulprasath36/qalens:latest
```

The `latest` tag represents the current image built from the `main` branch. A SHA-specific image is also published for each build:

```text
ghcr.io/arulprasath36/qalens:sha-<git-commit-sha>
```

For repeatable deployments, use the SHA-specific tag after validating it.

After the first workflow publication, the repository owner must set the GHCR package visibility to public for unauthenticated users to pull the image. Until then, authenticated GitHub users with package access can use `docker login ghcr.io`.

## Local Quick Start

Create durable storage and start QA Lens:

```bash
docker volume create qalens-data
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  ghcr.io/arulprasath36/qalens:latest
```

Open:

```text
http://127.0.0.1:8080
```

QA Lens defaults to no authentication. The explicit `127.0.0.1` host mapping prevents other machines from reaching this local container.

## Persistent Data

The container stores mutable state in `/data`:

| Path | Purpose |
|---|---|
| `/data/qalens.db` | SQLite run history and analysis data. |
| `/data/config.toml` | Settings, including optional LLM configuration. |

Keep `/data` in a named volume or durable bind mount. Deleting the volume deletes ingested history and saved configuration.

## Ingest A Report

Mount the source report read-only and use the same `/data` volume as the UI server:

```bash
docker run --rm \
  -v qalens-data:/data \
  -v "/absolute/path/to/allure-report:/reports/input:ro" \
  ghcr.io/arulprasath36/qalens:latest \
  ingest /reports/input --db /data/qalens.db
```

From a repository checkout, ingest the included sample:

```bash
docker run --rm \
  -v qalens-data:/data \
  -v "$PWD/tests/fixtures/allure_sample:/reports/input:ro" \
  ghcr.io/arulprasath36/qalens:latest \
  ingest /reports/input --db /data/qalens.db
```

Refresh the browser after ingestion to see the imported run.

## Export A Report

Mount an output directory for exported files:

```bash
mkdir -p qalens-output
docker run --rm \
  -v qalens-data:/data \
  -v "$PWD/qalens-output:/output" \
  ghcr.io/arulprasath36/qalens:latest \
  report --db /data/qalens.db --out /output/qalens-report.html
```

## Docker Compose

The repository includes `compose.yaml` for local builds:

```bash
docker compose up --build
```

It builds the current source checkout, maps the app to `http://127.0.0.1:8080`, and creates the `qalens-data` named volume.

Ingest through the Compose service:

```bash
docker compose run --rm \
  -v "$PWD/tests/fixtures/allure_sample:/reports/input:ro" \
  qalens ingest /reports/input --db /data/qalens.db
```

## Build Locally

To build without Compose:

```bash
docker build -t qalens:local .
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  qalens:local
```

The Docker build compiles the frontend in a Node build stage and installs only the packaged Python application in the final runtime stage.

## Authentication And Network Exposure

Do not publish the container on `0.0.0.0:8080` without authentication. The application contains test failures, stack traces, paths, and potentially sensitive artifacts.

For token authentication:

```bash
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  -e QALENS_AUTH_TOKEN="replace-with-a-strong-token" \
  ghcr.io/arulprasath36/qalens:latest
```

For shared hosting:

- Enable token authentication or GitHub OAuth.
- Terminate HTTPS at a trusted proxy or hosting platform.
- Persist `/data` on restricted durable storage.
- Control retention for ingested reports and artifacts.
- Treat optional cloud LLM settings as a data-egress decision.

See [Security and Deployment](security-and-deployment.md) for the complete security model.

## Updating

Pull the latest image and start it with the existing volume:

```bash
docker pull ghcr.io/arulprasath36/qalens:latest
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  ghcr.io/arulprasath36/qalens:latest
```

Back up the volume before upgrading a shared or important installation.
