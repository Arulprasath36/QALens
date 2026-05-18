import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  HardDrive,
  KeyRound,
  Lock,
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

export function SettingsPanel() {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [form, setForm] = useState<LLMForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

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
    () => settings?.llm.provider_options.map(option => ({
      value: option.value,
      label: option.local ? `${option.label} · local` : option.label,
    })) ?? [],
    [settings],
  );

  const selectedProvider = settings?.llm.provider_options.find(option => option.value === form?.provider);
  const externalProviderSelected = selectedProvider ? !selectedProvider.local : false;

  async function saveSettings() {
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setError(null);

    try {
      const payload = {
        provider: form.provider,
        base_url: form.base_url,
        model: form.model,
        api_key: form.api_key || undefined,
        timeout: Number(form.timeout),
        max_tokens: Number(form.max_tokens),
        temperature: Number(form.temperature),
        system_prompt: form.system_prompt,
        allow_external: form.allow_external,
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
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  }

  function resetForm() {
    if (!settings) return;
    setForm(formFromSettings(settings));
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

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <PageHeader
        title="Settings"
        kicker="Configuration"
        description="Runtime paths, LLM provider settings, and security defaults used by this QaLens server."
        icon={<Settings className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            {saved && <StatusPill ok label="Saved" />}
            <button
              type="button"
              onClick={resetForm}
              className="qalens-control px-3.5 text-sm"
              disabled={saving}
            >
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
            <button
              type="button"
              onClick={saveSettings}
              className="qalens-control bg-indigo-600 px-3.5 text-sm font-semibold text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-400"
              disabled={saving}
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
              ok={settings.llm.external_llm_allowed}
              label={settings.llm.external_llm_allowed ? 'Allowed' : 'External disabled'}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Provider">
              <Dropdown
                value={form.provider}
                onChange={provider => setForm(current => current && ({ ...current, provider }))}
                options={providerOptions}
                fullWidth
                ariaLabel="LLM provider"
                triggerClassName="px-3.5 text-sm"
              />
            </Field>

            <Field label="Model">
              <input
                value={form.model}
                onChange={event => setForm(current => current && ({ ...current, model: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <Field label="Base URL">
              <input
                value={form.base_url}
                onChange={event => setForm(current => current && ({ ...current, base_url: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <Field
              label="API key"
              hint={
                settings.llm.api_key_env_configured
                  ? 'QaLens_LLM_API_KEY is set in the environment.'
                  : settings.llm.api_key_configured
                    ? 'A key is saved. Leave blank to keep it unchanged.'
                    : 'Leave blank for local providers.'
              }
            >
              <input
                value={form.api_key}
                type="password"
                autoComplete="off"
                placeholder={settings.llm.api_key_configured ? 'Configured' : ''}
                onChange={event => setForm(current => current && ({ ...current, api_key: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <Field label="Timeout seconds">
              <input
                value={form.timeout}
                type="number"
                min={5}
                max={600}
                onChange={event => setForm(current => current && ({ ...current, timeout: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <Field label="Max tokens">
              <input
                value={form.max_tokens}
                type="number"
                min={128}
                max={65536}
                onChange={event => setForm(current => current && ({ ...current, max_tokens: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <Field label="Temperature">
              <input
                value={form.temperature}
                type="number"
                min={0}
                max={2}
                step={0.1}
                onChange={event => setForm(current => current && ({ ...current, temperature: event.target.value }))}
                className="qalens-control w-full px-3.5 text-sm"
              />
            </Field>

            <div className="flex items-end">
              <label className="flex min-h-11 w-full items-center gap-3 rounded-[0.95rem] border border-border-default bg-surface px-3.5 text-sm text-primary">
                <input
                  type="checkbox"
                  checked={form.allow_external}
                  onChange={event => setForm(current => current && ({ ...current, allow_external: event.target.checked }))}
                  className="h-4 w-4 accent-indigo-600"
                />
                <span>Allow external LLM providers</span>
              </label>
            </div>
          </div>

          {externalProviderSelected && !form.allow_external && (
            <div className="mt-4 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              External providers require explicit opt-in before QaLens sends redacted report context outside this machine.
            </div>
          )}

          <Field label="System prompt override" hint="Optional. Leave blank to use QaLens's default prompt.">
            <textarea
              value={form.system_prompt}
              onChange={event => setForm(current => current && ({ ...current, system_prompt: event.target.value }))}
              rows={4}
              className="min-h-[120px] w-full resize-y rounded-[0.95rem] border border-border-default bg-surface px-3.5 py-3 text-sm text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40"
            />
          </Field>
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
