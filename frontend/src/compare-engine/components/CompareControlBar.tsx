import React from 'react';
import type { CompareDimension, TimeMode } from '../types';
import { DIMENSION_CONFIG, TIME_MODE_LABELS } from '../types';
import type { UseCompareStateReturn } from '../hooks/useCompareState';
import type { Owner, Run, Suite } from '../types';
import { OwnerPicker }       from './pickers/OwnerPicker';
import { RunPicker }         from './pickers/RunPicker';
import { SuitePicker }       from './pickers/SuitePicker';
import { StatusToggleGroup } from './pickers/StatusToggleGroup';

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

interface DropdownProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string; icon?: string }[];
  onChange: (v: T) => void;
}

function Dropdown<T extends string>({ label, value, options, onChange }: DropdownProps<T>) {
  const selected = options.find(o => o.value === value);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500 px-0.5">
        {label}
      </span>
      <div className="relative">
        <select
          value={value}
          onChange={e => onChange(e.target.value as T)}
          className={[
            'appearance-none cursor-pointer',
            'bg-zinc-900 border border-zinc-700 rounded-lg',
            'pl-3 pr-8 py-2',
            'text-sm font-medium text-zinc-100',
            'hover:border-zinc-500 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30',
            'transition-colors duration-150 outline-none',
            'min-w-[160px]',
          ].join(' ')}
        >
          {options.map(o => (
            <option key={o.value} value={o.value}>
              {o.icon ? `${o.icon}  ` : ''}{o.label}
            </option>
          ))}
        </select>
        {/* Chevron */}
        <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </div>
    </div>
  );
}

function Divider() {
  return (
    <div className="self-end pb-[9px]">
      <div className="w-px h-8 bg-zinc-800" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Dimension options
// ─────────────────────────────────────────────────────────────

const DIMENSION_OPTIONS: { value: CompareDimension; label: string; icon: string }[] = [
  { value: 'runs',   label: 'Runs',   icon: '⚡' },
  { value: 'owners', label: 'Owners', icon: '👤' },
  { value: 'suites', label: 'Suites', icon: '📦' },
  { value: 'status', label: 'Status', icon: '🏷️' },
];

const TIME_OPTIONS: { value: TimeMode; label: string }[] = [
  { value: 'last5',              label: 'Last 5 runs' },
  { value: 'last10',             label: 'Last 10 runs' },
  { value: 'latest_vs_previous', label: 'Latest vs Previous' },
  { value: 'custom',             label: 'Custom range…' },
];

// ─────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────

interface CompareControlBarProps extends UseCompareStateReturn {
  owners:  Owner[];
  runs:    Run[];
  suites:  Suite[];
  /** Optional date range label computed by parent */
  timeLabel?: string;
}

// ─────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────

export function CompareControlBar({
  state,
  setDimension,
  setTimeMode,
  toggleSelection,
  setCustomRuns,
  canCompare,
  owners,
  runs,
  suites,
  timeLabel,
}: CompareControlBarProps) {

  const cfg = DIMENSION_CONFIG[state.dimension];

  return (
    <div className="w-full space-y-3">
      {/* ── Main control row ─────────────────────────────── */}
      <div className="flex items-end gap-3 flex-wrap">

        {/* Compare (dimension) */}
        <Dropdown<CompareDimension>
          label="Compare"
          value={state.dimension}
          options={DIMENSION_OPTIONS}
          onChange={setDimension}
        />

        <Divider />

        {/* Time scope */}
        <Dropdown<TimeMode>
          label="Time"
          value={state.timeMode}
          options={TIME_OPTIONS}
          onChange={setTimeMode}
        />

        <Divider />

        {/* Dynamic selector */}
        <div className="flex flex-col gap-1 flex-1 min-w-0">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500 px-0.5">
            Select {cfg.label}
          </span>
          <DynamicSelector
            state={state}
            toggleSelection={toggleSelection}
            setCustomRuns={setCustomRuns}
            owners={owners}
            runs={runs}
            suites={suites}
          />
        </div>

        {/* Compare CTA */}
        {canCompare && (
          <div className="self-end pb-0.5">
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-violet-500/10 border border-violet-500/30">
              <span className="text-xs font-medium text-violet-300">
                {state.selections.length === 2
                  ? `${state.selections[0]}  vs  ${state.selections[1]}`
                  : `${state.selections.length} selected`}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ── Context label ────────────────────────────────── */}
      {timeLabel && (
        <p className="text-xs text-zinc-500 pl-0.5">
          {timeLabel}
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Dynamic selector — switches based on dimension
// ─────────────────────────────────────────────────────────────

interface DynamicSelectorProps {
  state:            CompareControlBarProps['state'];
  toggleSelection:  CompareControlBarProps['toggleSelection'];
  setCustomRuns:    CompareControlBarProps['setCustomRuns'];
  owners:           Owner[];
  runs:             Run[];
  suites:           Suite[];
}

function DynamicSelector({ state, toggleSelection, setCustomRuns, owners, runs, suites }: DynamicSelectorProps) {
  switch (state.dimension) {
    case 'runs':
      return (
        <RunPicker
          runs={runs}
          selected={state.selections}
          onToggle={toggleSelection}
          onCustomSelect={setCustomRuns}
          timeMode={state.timeMode}
        />
      );
    case 'owners':
      return (
        <OwnerPicker
          owners={owners}
          selected={state.selections}
          onToggle={toggleSelection}
        />
      );
    case 'suites':
      return (
        <SuitePicker
          suites={suites}
          selected={state.selections}
          onToggle={toggleSelection}
        />
      );
    case 'status':
      return (
        <StatusToggleGroup
          selected={state.selections}
          onToggle={toggleSelection}
        />
      );
  }
}
