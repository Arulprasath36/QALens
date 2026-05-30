# Docker

QA Lens is available as a container image for users who do not want to install Python or Node.js locally. The container includes the CLI, API server, and built web UI.

## Requirements

- A running Docker engine.
- Docker Desktop or Colima is a normal choice on macOS.
- The Docker Compose plugin is required only for the `docker compose` examples.

On macOS, installing the `docker` CLI alone is not enough: it provides commands but not the local engine that builds and runs containers.

## Image

The user-facing Docker Hub repository is:

```text
https://hub.docker.com/r/arulprasath36/qalens
```

Pull the latest Docker Hub image with:

```bash
docker pull arulprasath36/qalens:latest
```

The GitHub Actions publishing workflow also builds `linux/amd64` and `linux/arm64` images for GitHub Container Registry (GHCR):

```text
ghcr.io/arulprasath36/qalens:latest
```

For GHCR, the `latest` tag represents the current image built from the `main` branch. A SHA-specific image is also published for each build:

```text
ghcr.io/arulprasath36/qalens:sha-<git-commit-sha>
```

For repeatable deployments, use a versioned Docker Hub tag or the SHA-specific GHCR tag after validating it.

The current workflow publishes GHCR images automatically from `main`. Docker Hub images are published separately until Docker Hub publishing is added to CI. After the first GHCR publication, the repository owner must set the GHCR package visibility to public for unauthenticated users to pull that registry's image.

## Local Quick Start

Create durable storage and start QA Lens:

```bash
docker volume create qalens-data
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  arulprasath36/qalens:latest
```

Open:

```text
http://127.0.0.1:8080
```

QA Lens defaults to no authentication. The explicit `127.0.0.1` host mapping prevents other machines from reaching this local container.

## Try The Preloaded Demo Database

QA Lens provides a released demo database with 50 synthetic ShopNow E-Commerce runs. Use it to explore trends, incidents, risk, and the action brief without importing a report first.

Download and unpack the demo database:

```bash
mkdir -p qalens-demo
cd qalens-demo
curl -fL https://github.com/Arulprasath36/QALens/releases/download/v0.1.2/shopnow-demo.zip \
  -o shopnow-demo.zip
unzip shopnow-demo.zip
```

Load the database into a dedicated Docker volume and start the UI:

```bash
docker volume create qalens-demo-data
docker run --rm --entrypoint python \
  -v qalens-demo-data:/data \
  -v "$PWD:/seed:ro" \
  arulprasath36/qalens:latest \
  -c 'import shutil; shutil.copyfile("/seed/shopnow-demo.db", "/data/qalens.db")'

docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-demo-data:/data \
  arulprasath36/qalens:latest
```

Open `http://127.0.0.1:8080`. Keep the demo in `qalens-demo-data` rather than your normal `qalens-data` volume so it does not replace your own history.

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
  arulprasath36/qalens:latest \
  ingest /reports/input --db /data/qalens.db
```

From a repository checkout, ingest the included sample:

```bash
docker run --rm \
  -v qalens-data:/data \
  -v "$PWD/tests/fixtures/allure_sample:/reports/input:ro" \
  arulprasath36/qalens:latest \
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
  arulprasath36/qalens:latest \
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
  arulprasath36/qalens:latest
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
docker pull arulprasath36/qalens:latest
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  arulprasath36/qalens:latest
```

Back up the volume before upgrading a shared or important installation.
