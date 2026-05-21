import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  HardDrive,
  KeyRound,
  Lock,
  Pencil,
  RotateCcw,
  Save,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';

type ProviderOption = {
  value: string;
  label: string;
  local: boolean;
};

type SettingsPayload = {
  runtime: {
    database_path: string;
    database_source: string;
    config_path: string;
    config_exists: boolean;
  };
  llm: {
    enabled?: boolean;
    provider: string;
    provider_display: string;
    base_url: string;
    effective_base_url: string;
    model: string;
    timeout: number;
    max_tokens: number;
    temperature: number;
    allow_external: boolean;
    external_llm_allowed: boolean;
    endpoint_is_local: boolean;
    api_key_configured: boolean;
    api_key_env_configured: boolean;
    system_prompt: string;
    provider_options: ProviderOption[];
  };
  artifacts: {
    mode: string;
    max_screenshots_per_failure: number;
    max_screenshot_bytes: number;
    max_total_screenshot_bytes_per_run: number;
    storage_dir: string;
    supported_image_mime_types: string[];
    svg_enabled: boolean;
  };
  security: {
    external_llm_opt_in_env: string;
    external_llm_env_enabled: boolean;
    local_llm_providers: string[];
    max_llm_prompt_chars: number;
    redaction_enabled: boolean;
    untrusted_data_wrappers_enabled: boolean;
  };
  owner_mapping: {
    active_path: string | null;
    source: string;
    editable: boolean;
  };
};

type LLMForm = {
  enabled: boolean;
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
  timeout: string;
  max_tokens: string;
  temperature: string;
  system_prompt: string;
  allow_external: boolean;
};

type LlmLocation = 'local' | 'cloud';

const PROVIDER_DEFAULTS: Record<string, { model: string; base_url: string }> = {
  ollama: { model: 'llama3.2', base_url: 'http://localhost:11434/v1' },
  lmstudio: { model: 'local-model', base_url: 'http://localhost:1234/v1' },
  custom: { model: 'default', base_url: 'http://localhost:8080/v1' },
  openai: { model: 'gpt-4o-mini', base_url: 'https://api.openai.com/v1' },
  azure: { model: 'gpt-4o', base_url: '' },
  anthropic: { model: 'claude-3-haiku-20240307', base_url: 'https://api.anthropic.com' },
  gemini: { model: 'gemini-2.0-flash', base_url: 'https://generativelanguage.googleapis.com' },
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = units[0];
  for (let i = 1; i < units.length && value >= 1024; i += 1) {
    value /= 1024;
    unit = units[i];
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
}

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function formFromSettings(settings: SettingsPayload): LLMForm {
  return {
    enabled: settings.llm.enabled ?? true,
    provider: settings.llm.provider,
    base_url: settings.llm.base_url,
    model: settings.llm.model,
    api_key: '',
    timeout: String(settings.llm.timeout),
    max_tokens: String(settings.llm.max_tokens),
    temperature: String(settings.llm.temperature),
    system_prompt: settings.llm.system_prompt,
    allow_external: settings.llm.allow_external,
  };
}

function llmLocationFromSettings(settings: SettingsPayload): LlmLocation {
  const provider = settings.llm.provider_options.find(option => option.value === settings.llm.provider);
  if (settings.llm.endpoint_is_local || provider?.local) return 'local';
  return 'cloud';
}

function StatusPill({
  ok,
  label,
}: {
  ok: boolean;
  label: string;
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold',
        ok
          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
          : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300',
      )}
    >
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
      {label}
    </span>
  );
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}

function ReadOnlyRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 border-t border-border-subtle py-3 first:border-t-0 sm:grid-cols-[170px_minmax(0,1fr)]">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted">{label}</div>
      <div className={cx('min-w-0 text-sm text-primary', mono && 'font-mono break-all')}>{value}</div>
    </div>
  );
}

function editableControlClass(editing: boolean) {
  return cx(
    'qalens-control w-full px-3.5 text-sm',
    !editing && 'cursor-not-allowed bg-surface-subtle text-muted opacity-80',
  );
}

export function SettingsPanel() {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [form, setForm] = useState<LLMForm | null>(null);
  const [llmLocation, setLlmLocation] = useState<LlmLocation>('local');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch('/api/settings');
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json() as SettingsPayload;
        if (cancelled) return;
        setSettings(data);
        setForm(formFromSettings(data));
        setLlmLocation(llmLocationFromSettings(data));
        setEditing(false);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load settings.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const providerOptions = useMemo(
    () => settings?.llm.provider_options
      .filter(option => (
        llmLocation === 'local'
          ? option.local || option.value === 'custom' || (settings.llm.endpoint_is_local && option.value === form?.provider)
          : !option.local
      ))
      .map(option => ({
      value: option.value,
      label: option.local ? `${option.label} · local` : option.label,
    })) ?? [],
    [form?.provider, llmLocation, settings],
  );

  function providerAllowedForLocation(provider: string, location: LlmLocation) {
    const option = settings?.llm.provider_options.find(item => item.value === provider);
    if (!option) return false;
    return location === 'local' ? option.local || option.value === 'custom' : !option.local;
  }

  function applyProvider(provider: string) {
    const defaults = PROVIDER_DEFAULTS[provider];
    setForm(current => current && ({
      ...current,
      provider,
      ...(defaults ? { model: defaults.model, base_url: defaults.base_url } : {}),
    }));
  }

  function applyLlmLocation(location: LlmLocation) {
    setLlmLocation(location);
    setForm(current => {
      if (!current) return current;
      if (providerAllowedForLocation(current.provider, location)) return current;
      const provider = location === 'local' ? 'ollama' : 'openai';
      const defaults = PROVIDER_DEFAULTS[provider];
      return {
        ...current,
        provider,
        model: defaults.model,
        base_url: defaults.base_url,
      };
    });
  }

  async function saveSettings() {
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setError(null);

    try {
      const payload = {
        enabled: form.enabled,
        provider: form.provider,
        base_url: form.base_url,
        model: form.model,
        api_key: form.api_key || undefined,
        timeout: Number(form.timeout),
        max_tokens: Number(form.max_tokens),
        temperature: Number(form.temperature),
        system_prompt: form.system_prompt,
        allow_external: form.enabled && llmLocation === 'cloud',
      };
      const res = await fetch('/api/settings/llm', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());

      const fresh = await fetch('/api/settings');
      if (!fresh.ok) throw new Error(await fresh.text());
      const data = await fresh.json() as SettingsPayload;
      setSettings(data);
      setForm(formFromSettings(data));
      setLlmLocation(llmLocationFromSettings(data));
      setSaved(true);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  }

  function resetForm() {
    if (!settings) return;
    setForm(formFromSettings(settings));
    setLlmLocation(llmLocationFromSettings(settings));
    setEditing(false);
    setSaved(false);
    setError(null);
  }

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-16 rounded-2xl bg-surface-subtle" />
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-72 rounded-2xl bg-surface-subtle" />
          <div className="h-72 rounded-2xl bg-surface-subtle" />
        </div>
      </div>
    );
  }

  if (!settings || !form) {
    return (
      <div className="qalens-card p-6">
        <p className="text-sm text-danger">{error ?? 'Settings are unavailable.'}</p>
      </div>
    );
  }

  const activeProvider = settings.llm.provider_options.find(option => option.value === settings.llm.provider);
  const activeProviderIsLocal = Boolean(
    settings.llm.endpoint_is_local
    || (activeProvider ? activeProvider.local : settings.security.local_llm_providers.includes(settings.llm.provider)),
  );
  const providerStatusLabel = activeProviderIsLocal
    ? settings.llm.endpoint_is_local
      ? 'Local endpoint'
      : 'Local model'
    : settings.llm.external_llm_allowed
      ? 'External allowed'
      : 'External blocked';
  const savedLlmLocation = llmLocationFromSettings(settings);
  const isDirty = (
    form.enabled !== (settings.llm.enabled ?? true)
    || llmLocation !== savedLlmLocation
    || form.provider !== settings.llm.provider
    || form.base_url !== settings.llm.base_url
    || form.model !== settings.llm.model
    || form.timeout !== String(settings.llm.timeout)
    || form.max_tokens !== String(settings.llm.max_tokens)
    || form.temperature !== String(settings.llm.temperature)
    || form.system_prompt !== settings.llm.system_prompt
    || form.api_key.trim() !== ''
  );
  const canSave = editing && isDirty && !saving;
  const canReset = editing && isDirty && !saving;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <PageHeader
        title="Settings"
        kicker="Configuration"
        description="Runtime paths, LLM provider settings, and security defaults used by this QA Lens server."
        icon={<Settings className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            {saved && <StatusPill ok label="Saved" />}
            <button
              type="button"
              onClick={() => {
                if (editing) {
                  if (!isDirty) setEditing(false);
                  return;
                }
                setEditing(true);
                setSaved(false);
              }}
              className="qalens-control px-3.5 text-sm"
              disabled={saving}
            >
              <Pencil className="h-4 w-4" />
              {editing ? (isDirty ? 'Editing' : 'Done') : 'Edit'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="qalens-control px-3.5 text-sm"
              disabled={!canReset}
            >
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
            <button
              type="button"
              onClick={saveSettings}
              className={cx(
                'qalens-control px-3.5 text-sm font-semibold transition',
                canSave
                  ? 'bg-indigo-600 text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-400'
                  : 'cursor-not-allowed border-border-subtle bg-surface-subtle text-muted opacity-70',
              )}
              disabled={!canSave}
            >
              <Save className="h-4 w-4" />
              {saving ? 'Saving' : 'Save'}
            </button>
          </div>
        }
      />

      {error && (
        <div className="rounded-2xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
        <div className="qalens-card p-5">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-info" />
              <h2 className="text-base font-semibold text-primary">LLM provider</h2>
            </div>
            <StatusPill
              ok={activeProviderIsLocal || settings.llm.external_llm_allowed}
              label={providerStatusLabel}
            />
          </div>

          <div className="mb-5 grid gap-3 lg:grid-cols-2">
            <div className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-500/25 dark:bg-blue-500/10">
              <div className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-blue-700 dark:text-blue-300" />
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700 dark:text-blue-300">How answers are written</p>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-200">
                QA Lens uses deterministic code first for factual answers, rankings, counts, and workspaces. The configured model is used only when a question path needs LLM narration, intent parsing, or a general explanation.
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-surface-subtle p-4 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <Cpu className="h-4 w-4 text-primary" />
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Active model path</p>
              </div>
              <div className="mt-3 space-y-2 text-sm text-secondary">
                <p><span className="font-semibold text-primary">Provider:</span> {settings.llm.provider_display}</p>
                <p><span className="font-semibold text-primary">Model:</span> {settings.llm.model || 'Not set'}</p>
                <p>
                  <span className="font-semibold text-primary">Endpoint:</span>{' '}
                  <span className="font-mono text-xs">{settings.llm.effective_base_url || 'Provider default'}</span>
                  {settings.llm.endpoint_is_local && (
                    <span className="ml-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
                      local
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>

            <div className="mb-5 rounded-2xl border border-border-default bg-surface p-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Allow LLM-assisted answers?</p>
                <p className="mt-2 text-sm leading-6 text-secondary">
                  Deterministic QA Lens answers and workspaces stay available either way. Turn this on for model-written narration, intent parsing, and flexible follow-up questions.
                </p>
              </div>
              <label className="flex min-h-11 shrink-0 cursor-pointer items-center gap-3 rounded-[0.95rem] border border-border-default bg-surface-subtle px-3.5 text-sm font-medium text-primary">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={event => setForm(current => current && ({ ...current, enabled: event.target.checked }))}
                  disabled={!editing}
                  className="peer sr-only"
                />
                <span className="relative inline-flex h-6 w-11 items-center rounded-full bg-slate-300 transition peer-checked:bg-indigo-600 dark:bg-slate-700">
                  <span className="inline-block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition peer-checked:translate-x-5" />
                </span>
                <span>{form.enabled ? 'LLM assistance on' : 'LLM assistance off'}</span>
              </label>
            </div>
          </div>

          {!editing && (
            <div className="mb-5 rounded-2xl border border-border-subtle bg-surface-subtle px-4 py-3 text-sm leading-6 text-secondary">
              <div className="flex items-start gap-2">
                <Lock className="mt-0.5 h-4 w-4 shrink-0" />
                <p>Settings are locked to prevent accidental changes. Click Edit before changing LLM configuration.</p>
              </div>
            </div>
          )}

          {!form.enabled ? (
            <div className="rounded-2xl border border-border-subtle bg-surface-subtle px-4 py-4 text-sm leading-6 text-secondary">
              LLM-assisted narration is disabled. QA Lens will still answer deterministic questions such as run counts, failures, rankings, pass-rate extremes, and decision workspaces.
            </div>
          ) : (
            <>
              <div className="mb-5 rounded-2xl border border-border-default bg-surface p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Where should the LLM run?</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {(['local', 'cloud'] as const).map(location => (
                    <button
                      key={location}
                      type="button"
                      onClick={() => applyLlmLocation(location)}
                      disabled={!editing}
                      className={cx(
                        'rounded-[0.95rem] border px-4 py-3 text-left transition',
                        llmLocation === location
                          ? 'border-indigo-400 bg-indigo-50 text-indigo-900 dark:border-indigo-500/50 dark:bg-indigo-500/10 dark:text-indigo-200'
                          : 'border-border-default bg-surface-subtle text-secondary hover:bg-surface',
                        !editing && 'cursor-not-allowed opacity-70',
                      )}
                    >
                      <span className="block text-sm font-semibold text-primary">
                        {location === 'local' ? 'Local LLM' : 'Cloud provider'}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-secondary">
                        {location === 'local'
                          ? 'Use Ollama, LM Studio, or another localhost-compatible server.'
                          : 'Use OpenAI, Anthropic, Gemini, Azure, or another hosted endpoint.'}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="mb-3">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Model connection</p>
                <p className="mt-1 text-sm text-secondary">
                  {llmLocation === 'local'
                    ? 'For local Gemma through Ollama, use the Ollama provider and a localhost endpoint such as http://localhost:11434/v1.'
                    : 'Cloud providers may receive redacted report context. API keys can also come from QALENS_LLM_API_KEY.'}
                </p>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Field label={llmLocation === 'local' ? 'Local provider' : 'Cloud provider'}>
                  <Dropdown
                    value={form.provider}
                    onChange={applyProvider}
                    options={providerOptions}
                    disabled={!editing}
                    fullWidth
                    ariaLabel="LLM provider"
                    triggerClassName="px-3.5 text-sm"
                  />
                </Field>

                <Field label="Model">
                  <input
                    value={form.model}
                    disabled={!editing}
                    onChange={event => setForm(current => current && ({ ...current, model: event.target.value }))}
                    className={editableControlClass(editing)}
                  />
                </Field>

                <Field label="Endpoint URL" hint={llmLocation === 'local' ? 'Local server URL, usually localhost.' : 'Leave blank to use the provider default when supported.'}>
                  <input
                    value={form.base_url}
                    disabled={!editing}
                    onChange={event => setForm(current => current && ({ ...current, base_url: event.target.value }))}
                    className={editableControlClass(editing)}
                  />
                </Field>

                {llmLocation === 'cloud' ? (
                  <Field
                    label="API key"
                    hint={
                      settings.llm.api_key_env_configured
                        ? 'QALENS_LLM_API_KEY is set in the environment.'
                        : settings.llm.api_key_configured
                          ? 'A key is saved. Leave blank to keep it unchanged.'
                          : 'Required for most cloud providers.'
                    }
                  >
                    <input
                      value={form.api_key}
                      type="password"
                      autoComplete="off"
                      disabled={!editing}
                      placeholder={settings.llm.api_key_configured ? 'Configured' : ''}
                      onChange={event => setForm(current => current && ({ ...current, api_key: event.target.value }))}
                      className={editableControlClass(editing)}
                    />
                  </Field>
                ) : (
                  <div className="rounded-[0.95rem] border border-border-subtle bg-surface-subtle px-4 py-3 text-sm leading-6 text-secondary">
                    Local providers usually do not need an API key. If your local server requires one, set it with <span className="font-mono text-xs">QALENS_LLM_API_KEY</span>.
                  </div>
                )}

                <Field label="Timeout seconds">
                  <input
                    value={form.timeout}
                    type="number"
                    min={5}
                    max={600}
                    disabled={!editing}
                    onChange={event => setForm(current => current && ({ ...current, timeout: event.target.value }))}
                    className={editableControlClass(editing)}
                  />
                </Field>

                <Field label="Max tokens">
                  <input
                    value={form.max_tokens}
                    type="number"
                    min={128}
                    max={65536}
                    disabled={!editing}
                    onChange={event => setForm(current => current && ({ ...current, max_tokens: event.target.value }))}
                    className={editableControlClass(editing)}
                  />
                </Field>

                <Field label="Temperature">
                  <input
                    value={form.temperature}
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    disabled={!editing}
                    onChange={event => setForm(current => current && ({ ...current, temperature: event.target.value }))}
                    className={editableControlClass(editing)}
                  />
                </Field>
              </div>

              {llmLocation === 'cloud' && (
                <div className="mt-4 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  Cloud providers receive redacted report context. Save only after confirming your project permits sending this data to the selected provider.
                </div>
              )}

              <Field label="System prompt override" hint="Optional. Leave blank to use QA Lens's default prompt.">
                <textarea
                  value={form.system_prompt}
                  disabled={!editing}
                  onChange={event => setForm(current => current && ({ ...current, system_prompt: event.target.value }))}
                  rows={4}
                  className={cx(
                    'min-h-[120px] w-full resize-y rounded-[0.95rem] border border-border-default bg-surface px-3.5 py-3 text-sm text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
                    !editing && 'cursor-not-allowed bg-surface-subtle text-muted opacity-80',
                  )}
                />
              </Field>
            </>
          )}
        </div>

        <div className="space-y-5">
          <div className="qalens-card p-5">
            <div className="mb-2 flex items-center gap-2">
              <Database className="h-5 w-5 text-info" />
              <h2 className="text-base font-semibold text-primary">Runtime paths</h2>
            </div>
            <ReadOnlyRow label="Database" value={settings.runtime.database_path} mono />
            <ReadOnlyRow label="DB source" value={settings.runtime.database_source} />
            <ReadOnlyRow label="Config file" value={settings.runtime.config_path} mono />
            <ReadOnlyRow
              label="Config status"
              value={settings.runtime.config_exists ? 'File exists' : 'Using built-in defaults'}
            />
          </div>

          <div className="qalens-card p-5">
            <div className="mb-2 flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-info" />
              <h2 className="text-base font-semibold text-primary">Security boundary</h2>
            </div>
            <div className="mb-3 rounded-2xl border border-border-subtle bg-surface-subtle px-4 py-3 text-sm leading-6 text-secondary">
              Local providers can receive redacted prompt context without external opt-in. Cloud providers stay blocked until either this settings page or the environment explicitly allows external LLM use.
            </div>
            <ReadOnlyRow label="Redaction" value={settings.security.redaction_enabled ? 'Enabled' : 'Disabled'} />
            <ReadOnlyRow label="Prompt cap" value={`${settings.security.max_llm_prompt_chars.toLocaleString()} chars`} />
            <ReadOnlyRow
              label="External env"
              value={`${settings.security.external_llm_opt_in_env}=${settings.security.external_llm_env_enabled ? 'enabled' : 'not set'}`}
              mono
            />
            <ReadOnlyRow
              label="Trusted local"
              value={settings.security.local_llm_providers.join(', ')}
            />
          </div>
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="qalens-card p-5">
          <div className="mb-2 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-info" />
            <h2 className="text-base font-semibold text-primary">Artifact defaults</h2>
          </div>
          <ReadOnlyRow label="Default mode" value={settings.artifacts.mode} />
          <ReadOnlyRow label="Per failure cap" value={settings.artifacts.max_screenshots_per_failure} />
          <ReadOnlyRow label="Image byte cap" value={formatBytes(settings.artifacts.max_screenshot_bytes)} />
          <ReadOnlyRow label="Run byte cap" value={formatBytes(settings.artifacts.max_total_screenshot_bytes_per_run)} />
          <ReadOnlyRow label="Storage dir" value={settings.artifacts.storage_dir} mono />
          <ReadOnlyRow label="SVG artifacts" value={settings.artifacts.svg_enabled ? 'Enabled' : 'Disabled'} />
        </div>

        <div className="qalens-card p-5">
          <div className="mb-2 flex items-center gap-2">
            <Lock className="h-5 w-5 text-info" />
            <h2 className="text-base font-semibold text-primary">Owner mapping</h2>
          </div>
          <ReadOnlyRow
            label="Active file"
            value={settings.owner_mapping.active_path ?? 'None for this server session'}
            mono={Boolean(settings.owner_mapping.active_path)}
          />
          <ReadOnlyRow label="Source" value={settings.owner_mapping.source} />
          <ReadOnlyRow
            label="Editable here"
            value={settings.owner_mapping.editable ? 'Yes' : 'No, pass --owner-map during ingest'}
          />
        </div>
      </section>
    </div>
  );
}
