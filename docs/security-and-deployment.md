# Security and Deployment

QA Lens is local-first by default. It is designed to be safe for developer machines and CI artifacts before being exposed as a shared service.

## Default Security Model

Default behavior:

- Server binds to localhost.
- Authentication is disabled.
- SQLite database is local.
- Core analysis does not require network access.
- Cloud LLM providers are blocked unless explicitly allowed.

This is appropriate for:

- Local development.
- Personal test report analysis.
- CI artifact generation.
- Private demos on localhost.

It is not appropriate for exposing QA Lens on a public network.

## Report Data Is Sensitive

Test reports may contain:

- Stack traces.
- File paths.
- Internal URLs.
- Environment names.
- API endpoints.
- Usernames.
- Test data.
- Screenshot metadata.
- Secrets accidentally printed by tests.

Treat reports as untrusted and potentially sensitive.

## Parsing Safety

QA Lens uses safer XML parsing through `defusedxml` where applicable and validates supported report file types. Still, report parsing should be performed on reports from trusted CI systems or controlled test environments.

Recommendations:

- Do not ingest arbitrary reports from unknown users.
- Keep QA Lens updated.
- Run ingestion with least-privilege filesystem access in shared environments.
- Avoid storing full screenshot bytes unless needed.

## Artifact Policy

Default ingestion mode is metadata-focused and lightweight.

Use:

```bash
--artifact-mode metadata-only
```

for most cases.

Use:

```bash
--artifact-mode full
```

only when the UI must display image bytes after the original report is gone.

Set caps:

```bash
--max-screenshots-per-failure 2
--max-screenshot-bytes 5242880
--max-total-screenshot-bytes 52428800
```

## Authentication Modes

### No Auth

Default.

Use only on localhost or trusted private environments.

### Token Auth

Set:

```bash
export QALENS_AUTH_TOKEN="strong-random-token"
qalens serve --db ./qalens.db
```

API requests:

```bash
curl -H "Authorization: Bearer strong-random-token" \
  http://127.0.0.1:8080/api/runs
```

### GitHub OAuth

Set:

```bash
export QALENS_AUTH_MODE=github
export QALENS_GITHUB_CLIENT_ID="..."
export QALENS_GITHUB_CLIENT_SECRET="..."
export QALENS_SESSION_SECRET="stable-random-secret"
export QALENS_ALLOWED_GITHUB_USERS="github-login,teammate-login"
```

Optional organization allowlist:

```bash
export QALENS_ALLOWED_GITHUB_ORGS="your-org"
```

Settings admin access:

```bash
export QALENS_ADMIN_GITHUB_USERS="github-login"
```

`QALENS_SESSION_SECRET` must be stable across restarts. If it changes, existing browser sessions become invalid.

## Public Binding

Do not bind QA Lens to a public interface unless:

- Authentication is enabled.
- The environment is private or protected by a reverse proxy.
- TLS is handled by the proxy/platform.
- You understand what report data is visible.

Prefer:

```bash
qalens serve --host 127.0.0.1 --port 8080 --db ./qalens.db
```

Avoid:

```bash
qalens serve --host 0.0.0.0
```

unless explicitly needed and protected.

## Docker Deployment

The Docker image must bind to `0.0.0.0` inside its container so Docker can forward traffic to it. This does not require exposing QA Lens beyond your machine.

For a local no-auth deployment, publish only on localhost:

```bash
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  arulprasath36/qalens:latest
```

The image:

- Runs as a non-root user.
- Stores its SQLite database and settings in `/data`.
- Provides an HTTP health check at `/api/health`.

If you expose a container on a network or through a hosted platform, enable token or GitHub OAuth authentication, place it behind TLS, and mount `/data` on durable restricted storage.

## LLM Security

Local LLM providers are safest because prompt context stays on the machine or private network.

Cloud LLM providers require opt-in:

```bash
export QALENS_ALLOW_EXTERNAL_LLM=1
```

or:

```toml
[llm]
allow_external = true
```

Before enabling cloud providers, confirm:

- Your organization permits sending report-derived context to the provider.
- The provider and model meet your compliance requirements.
- Secrets are not present in reports.
- Redaction is not your only control.

## CI Deployment

For CI, the safest pattern is:

1. Run tests.
2. Generate report.
3. Ingest report into a local `qalens.db`.
4. Export a static QA Lens report.
5. Upload the exported report as an artifact.

Example:

```bash
qalens ingest path/to/report --db qalens.db --artifact-mode metadata-only
qalens report --db qalens.db --out qalens-report.html
```

This avoids running a long-lived server in CI.

## Shared Server Deployment

For a shared internal server:

- Use token or GitHub OAuth auth.
- Put QA Lens behind a TLS-terminating reverse proxy.
- Store the SQLite database on durable disk.
- Restrict filesystem permissions.
- Avoid cloud LLMs unless approved.
- Back up the database.
- Keep a clear data retention policy.

## Production Checklist

Before exposing QA Lens:

- Authentication enabled.
- Admin list configured.
- Public bind intentional.
- TLS handled.
- SQLite file permissions restricted.
- Artifact storage location restricted.
- LLM provider policy reviewed.
- Report data sensitivity reviewed.
- Backup and retention policy defined.
- Version pinned.
