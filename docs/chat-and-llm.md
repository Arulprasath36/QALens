# Chat and LLMs

QA Lens can answer many questions without an LLM. LLM assistance is optional.

## Two Answer Paths

### Deterministic Answers

Deterministic answers are computed directly from SQLite and QA Lens code.

They are used for:

- Latest failures.
- New failures.
- Flaky tests.
- Risk rankings.
- Owner and suite summaries.
- Pass-rate extrema.
- Many structured result workspaces.
- Report exports.
- Action Brief and trend intelligence.

Benefits:

- Reproducible.
- Fast.
- Explainable.
- No network required.
- No data leaves the machine.

### LLM-Assisted Answers

LLM assistance is used when QA Lens needs:

- Flexible natural-language interpretation.
- General explanation.
- Intent parsing.
- Follow-up narration.
- A user-friendly summary over structured facts.

LLMs do not replace the database. QA Lens still gathers structured context first and sends only the relevant prompt context.

## Default Behavior

Core QA Lens features work without an LLM.

If LLM assistance is disabled or unavailable:

- Deterministic chat questions still work.
- UI analysis still works.
- Reports still work.
- Ingestion still works.
- API data endpoints still work.

Some free-form questions may fall back to deterministic summaries or return an LLM connection message.

## Configure From UI

Open Settings.

The recommended flow is:

1. Read **How answers are written**.
2. Turn on **LLM-assisted answers** only if needed.
3. Choose where the LLM runs:
   - Local LLM
   - Cloud provider
4. Enter provider, model, endpoint, and API key if required.
5. Save.

Settings are locked by default. Click **Edit** before changing values.

## Configure From CLI

```bash
qalens llm-config
```

Default config path:

```text
~/.qalens/config.toml
```

Example local Ollama config:

```toml
[llm]
enabled = true
provider = "ollama"
base_url = "http://localhost:11434/v1"
model = "llama3.2"
api_key = ""
timeout = 120
max_tokens = 2048
temperature = 0.2
system_prompt = ""
allow_external = false
```

## Local LLMs

Use local mode when the model runs on your machine or private network.

Supported local-style providers:

- Ollama
- LM Studio
- Custom OpenAI-compatible endpoint

Examples:

Ollama:

```text
provider: ollama
endpoint: http://localhost:11434/v1
model: llama3.2
```

LM Studio:

```text
provider: lmstudio
endpoint: http://localhost:1234/v1
model: local-model
```

Local Gemma through Ollama:

```text
provider: ollama
endpoint: http://localhost:11434/v1
model: gemma3:4b
```

Local providers usually do not need an API key. If your local server requires one, set:

```bash
export QALENS_LLM_API_KEY="..."
```

## Cloud Providers

Cloud providers can receive redacted report context. Enable them only if your organization permits sending this data to the provider.

Supported cloud-style providers:

- OpenAI
- Azure OpenAI
- Anthropic
- Gemini
- Custom hosted endpoint

Cloud mode requires explicit opt-in:

```toml
[llm]
enabled = true
allow_external = true
```

Or:

```bash
export QALENS_ALLOW_EXTERNAL_LLM=1
```

API key:

```bash
export QALENS_LLM_API_KEY="..."
```

## Security Boundary

QA Lens treats test reports as untrusted input.

Before LLM calls:

- Context is selected from stored test data.
- Secret-like patterns are redacted.
- Prompt size is capped.
- Cloud providers require explicit opt-in.

Still, report data may contain:

- Test names.
- Failure messages.
- Stack traces.
- URLs.
- Environment names.
- Customer-like or internal identifiers if your tests include them.

Do not enable cloud providers unless this data is allowed to leave your environment.

## Useful Questions

```text
What broke in the latest run?
What changed since the previous run?
Which tests are flaky?
Which tests should I fix first?
Which failures share the same root cause?
Which suites are degrading?
Which owner has the highest failure rate?
How can I fix testCreateOrder()?
In the last 20 runs, which run had the highest pass percentage?
```

## Why A Local Model May Not Write Every Answer

Even when an LLM is configured, QA Lens intentionally uses deterministic answers first for factual questions.

That is expected.

For example, this should be deterministic:

```text
Which run had the highest pass percentage in the last 20 runs?
```

The answer is a database calculation. Asking an LLM would be slower and less reliable.

The model is more useful for:

- Natural-language summaries.
- Explaining a grouped failure.
- Interpreting a broad question.
- Follow-up wording.

