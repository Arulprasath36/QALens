# CLI Reference

The package exposes one command:

```bash
qalens
```

Use:

```bash
qalens --help
qalens COMMAND --help
```

## `qalens detect`

Detect the report type at a path.

```bash
qalens detect path/to/report
qalens detect path/to/report --verbose
```

Use this when a report does not ingest as expected.

## `qalens extract`

Parse a report and write normalized JSON without storing it.

```bash
qalens extract path/to/report --out normalized-run.json
```

Use this for parser debugging and support issues.

## `qalens ingest`

Parse and store a report in SQLite.

```bash
qalens ingest path/to/report --db ./qalens.db
```

Important options:

| Option | Purpose |
|---|---|
| `--db` | SQLite database path. Defaults to `~/.qalens/qalens.db`. |
| `--force` | Re-ingest an existing run. |
| `--owner-map` | JSON/TOML owner mapping file. |
| `--override-owners` | Replace owners found in the report with owner-map values. |
| `--artifact-mode` | `text-only`, `metadata-only`, or `full`. |
| `--artifact-storage-dir` | Storage root for full artifact mode. |

## `qalens analyze`

Analyze stored runs.

```bash
qalens analyze --db ./qalens.db
```

Use this for terminal summaries or scriptable analysis workflows.

## `qalens clusters`

Show failure clusters from stored data.

```bash
qalens clusters --db ./qalens.db
```

Use this to inspect repeated failure signatures without opening the UI.

## `qalens compare`

Compare run history by different dimensions.

```bash
qalens compare --db ./qalens.db --by runs --window 10
qalens compare --db ./qalens.db --by owners --window 10
qalens compare --db ./qalens.db --by suites --window 10
qalens compare --db ./qalens.db --by modules --window 10
```

Use explicit run ids for a specific range:

```bash
qalens compare --db ./qalens.db --run-id RUN_A --run-id RUN_B
```

## `qalens history`

Inspect one target over time.

```bash
qalens history test "testCreditCardPayment()" --db ./qalens.db
qalens history owner "Checkout Team" --db ./qalens.db
qalens history suite "Payments" --db ./qalens.db
qalens history failure FINGERPRINT --db ./qalens.db
```

## `qalens ask`

Ask a natural-language question about the stored test data.

```bash
qalens ask "What broke in the latest run?" --db ./qalens.db
qalens ask "Which tests are flaky?" --db ./qalens.db
qalens ask "Which run had the highest pass percentage in the last 20 runs?" --db ./qalens.db
```

Some answers are deterministic and do not require an LLM. If a question needs LLM narration or flexible parsing, QA Lens uses the configured provider.

Debug context:

```bash
qalens ask "Summarize all failures" --db ./qalens.db --show-context
```

## `qalens llm-config`

Configure the LLM provider.

```bash
qalens llm-config
```

The default config path is:

```text
~/.qalens/config.toml
```

## `qalens serve`

Start the web UI and API server.

```bash
qalens serve --db ./qalens.db
```

Default URL:

```text
http://127.0.0.1:8080
```

Common options:

```bash
qalens serve --host 127.0.0.1 --port 8080 --db ./qalens.db
qalens serve --db ./qalens.db --project "ShopNow"
qalens serve --db ./qalens.db --no-open
```

Do not bind to a public interface unless authentication is enabled and the deployment is protected.

## `qalens report`

Export a deterministic shareable report.

```bash
qalens report --db ./qalens.db --out qalens-report.html
qalens report --db ./qalens.db --format markdown --out qalens-report.md
qalens report --db ./qalens.db --format json --out qalens-report.json
```

Useful options:

| Option | Purpose |
|---|---|
| `--project` | Project scope. |
| `--run-id` | Run id, run sequence, or `latest`. |
| `--window` | Recent run count for recurring groups. |
| `--min-runs` | Minimum history depth for stability/flaky sections. |
| `--limit` | Maximum rows per report section. |
| `--open` | Open HTML output after writing. |

