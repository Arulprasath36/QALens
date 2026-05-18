# QALens Production Checklist

QALens is designed as a local developer tool. Before exposing `qalens serve` beyond
localhost, complete this checklist.

## Network Exposure

- [ ] Bind QALens to `127.0.0.1` unless QALens auth and network controls are enabled.
- [ ] For simple sharing, set `QALENS_AUTH_TOKEN` or pass `qalens serve --auth-token ...`.
- [ ] For team SSO, set `QALENS_AUTH_MODE=github` and configure GitHub OAuth.
- [ ] Restrict GitHub sign-in with `QALENS_ALLOWED_GITHUB_USERS` or
      `QALENS_ALLOWED_GITHUB_ORGS`.
- [ ] Use a long random `QALENS_SESSION_SECRET` and rotate it when team access changes.
- [ ] For broader deployments, also require authentication at the proxy layer,
      such as OAuth2 or mTLS.
- [ ] Terminate HTTPS at the proxy.
- [ ] Restrict access by IP allowlist or private network controls.

## Secrets

- [ ] Keep LLM API keys in environment variables or a secrets manager.
- [ ] Do not store tokens in git remotes, `.env` files, source code, or screenshots.
- [ ] Rotate any credentials that may have appeared in test reports or git history.
- [ ] Confirm QALens redaction is enabled before using LLM features.

## LLM Boundary

- [ ] Use local providers (`ollama`, `lmstudio`) by default.
- [ ] For cloud providers, explicitly set `allow_external = true` or
      `QALENS_ALLOW_EXTERNAL_LLM=1` only after approving data egress.
- [ ] Review whether report data includes PII, customer data, secrets, hostnames,
      internal URLs, or proprietary stack traces.
- [ ] Set provider-side budget and usage alerts.

## Artifacts

- [ ] Keep the default `metadata-only` artifact mode unless image bytes are required.
- [ ] Keep screenshot byte caps enabled.
- [ ] Do not enable SVG artifacts; QALens accepts raster image magic bytes only.
- [ ] Store full artifacts outside any web root.

## Database

- [ ] Store SQLite files outside the static asset directory.
- [ ] Set database file permissions to owner read/write only.
- [ ] Back up the database according to your retention policy.
- [ ] Treat the database as sensitive because it contains report-derived failure data.

## CI And Dependencies

- [ ] Run Python tests and frontend tests before deployment.
- [ ] Run `pip-audit` for Python dependency CVEs.
- [ ] Run `npm audit --audit-level=high` for frontend dependency CVEs.
- [ ] Run `bandit -r src/ -ll` for Python static security checks.
- [ ] Enable Dependabot or Renovate alerts.

## Logging

- [ ] Confirm request bodies are not logged.
- [ ] Monitor repeated 4xx, 5xx, and `/api/ask` rate-limit responses.
- [ ] Apply a retention policy to logs because test names and stack traces may be sensitive.
