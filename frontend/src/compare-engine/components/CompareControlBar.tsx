import type { CompareDimension, TimeMode } from '../types';
import { DIMENSION_CONFIG } from '../types';
import type { UseCompareStateReturn } from '../hooks/useCompareState';
import type { Owner, Run, Suite } from '../types';
import { Dropdown } from '../../components/Dropdown';
import { OwnerPicker }       from './pickers/OwnerPicker';
import { RunPicker }         from './pickers/RunPicker';
import { SuitePicker }       from './pickers/SuitePicker';

// ─────────────────────────────────────────────────────────────
// Dimension tab strip
// ─────────────────────────────────────────────────────────────

const DIMENSION_OPTIONS: { value: CompareDimension; label: string; icon: string }[] = [
  { value: 'runs',   label: 'Runs',   icon: '⚡' },
  { value: 'owners', label: 'Owners', icon: '👤' },
  { value: 'suites', label: 'Suites', icon: '📦' },
];

const TIME_OPTIONS: { value: TimeMode; label: string }[] = [
  { value: 'latest_vs_previous', label: 'Latest vs Previous' },
  { value: 'last5',              label: 'Last 5 runs'        },
  { value: 'last10',             label: 'Last 10 runs'       },
  { value: 'custom',             label: 'Custom range…'      },
];

function DimensionTabs({
  value,
  onChange,
}: {
  value: CompareDimension;
  onChange: (v: CompareDimension) => void;
}) {
  return (
    <div className="flex items-center gap-0.5 p-1 rounded-xl border border-border-default bg-surface-subtle">
      {DIMENSION_OPTIONS.map(opt => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150',
            value === opt.value
              ? 'bg-surface text-primary shadow-sm border border-border-default'
              : 'text-muted hover:text-secondary hover:bg-hover',
          ].join(' ')}
        >
          <span className="text-[13px] leading-none">{opt.icon}</span>
          <span>{opt.label}</span>
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Time selector — compact inline dropdown
// ─────────────────────────────────────────────────────────────

function TimeSelect({
  value,
  onChange,
}: {
  value: TimeMode;
  onChange: (v: TimeMode) => void;
}) {
  return (
    <Dropdown
      value={value}
      onChange={onChange}
      triggerClassName="min-w-[172px] pl-3 pr-3 py-2 text-sm font-medium"
      leftIcon={(
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M8 5v3.5l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )}
      options={TIME_OPTIONS}
    />
  );
}

// ─────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────

interface CompareControlBarProps extends UseCompareStateReturn {
  owners:     Owner[];
  runs:       Run[];
  suites:     Suite[];
  timeLabel?: string;
  onReset?:   () => void;
}

// ─────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────

export function CompareControlBar({
  state,
  setDimension,
  setTimeMode,
  toggleSelection,
  toggleCustomRun,
  setCustomRuns,
  canCompare,
  owners,
  runs,
  suites,
  timeLabel,
  onReset,
}: CompareControlBarProps) {
  const cfg = DIMENSION_CONFIG[state.dimension];
  const hideSecondarySelector = state.dimension === 'runs' && state.timeMode !== 'custom';

  // Status pill for entity dimensions (owners / suites)
  const selectionPill = (() => {
    if (state.dimension === 'runs') return null;
    if (state.selections.length >= 2) {
      return state.selections.join('  ·  ');
    }
    return null;
  })();

  return (
    <div className="space-y-4">

      {/* ── Top row: dimension + time ───────────────────────── */}
      <div className="flex items-center gap-3 flex-wrap justify-between">
        <div className="flex items-center gap-3 flex-wrap">
        <DimensionTabs value={state.dimension} onChange={setDimension} />
        <TimeSelect value={state.timeMode} onChange={setTimeMode} />
        </div>

        {/* Active comparison badge */}
        {canCompare && selectionPill && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="qalens-pill qalens-pill-active text-xs">
              {selectionPill}
            </span>
          </div>
        )}

        {onReset && (
          <button
            onClick={onReset}
            className="qalens-chip type-chip"
          >
            Reset
          </button>
        )}
      </div>

      {/* ── Bottom row: entity / run picker ─────────────────── */}
      {!hideSecondarySelector && (
      <div className="space-y-2 border-t border-border-subtle pt-4">
        {/* Section label — suppressed for suites (SuitePicker has its own guided header) */}
        {state.dimension !== 'suites' && (
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted mb-2">
            {state.dimension === 'runs' && (
              state.timeMode === 'last5' || state.timeMode === 'last10' || state.timeMode === 'latest_vs_previous'
            )
              ? 'Run window'
              : `Select ${cfg.label}`}
          </p>
        )}

        <DynamicSelector
          state={state}
          toggleSelection={toggleSelection}
          toggleCustomRun={toggleCustomRun}
          setCustomRuns={setCustomRuns}
          owners={owners}
          runs={runs}
          suites={suites}
          timeLabel={timeLabel}
          canCompare={canCompare}
        />
      </div>
      )}

    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Dynamic selector — switches based on dimension
// ─────────────────────────────────────────────────────────────

interface DynamicSelectorProps {
  state:           CompareControlBarProps['state'];
  toggleSelection: CompareControlBarProps['toggleSelection'];
  toggleCustomRun: CompareControlBarProps['toggleCustomRun'];
  setCustomRuns:   CompareControlBarProps['setCustomRuns'];
  owners:          Owner[];
  runs:            Run[];
  suites:     Suite[];
  timeLabel?: string;
  canCompare: boolean;
}

function DynamicSelector({ state, toggleSelection, toggleCustomRun, setCustomRuns, owners, runs, suites, timeLabel, canCompare }: DynamicSelectorProps) {
  switch (state.dimension) {
    case 'runs':
      return (
        <RunPicker
          runs={runs}
          selected={state.customRunIds}
          timeMode={state.timeMode}
          onCustomToggle={toggleCustomRun}
          onCustomSet={setCustomRuns}
        />
      );
    case 'owners':
      return (
        <div className="space-y-4">
          <OwnerPicker
            owners={owners}
            selected={state.selections}
            onToggle={toggleSelection}
            maxSelections={DIMENSION_CONFIG.owners.maxSelections}
          />
          {state.timeMode === 'custom' && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                Select runs
              </p>
              <RunPicker
                runs={runs}
                selected={state.customRunIds}
                timeMode="custom"
                onCustomToggle={toggleCustomRun}
                onCustomSet={setCustomRuns}
              />
            </div>
          )}
        </div>
      );
    case 'suites':
      return (
        <div className="space-y-4">
          <SuitePicker
            suites={suites}
            selected={state.selections}
            onToggle={toggleSelection}
            maxSelections={DIMENSION_CONFIG.suites.maxSelections}
            timeLabel={timeLabel}
            canCompare={canCompare}
          />
          {state.timeMode === 'custom' && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                Select runs
              </p>
              <RunPicker
                runs={runs}
                selected={state.customRunIds}
                timeMode="custom"
                onCustomToggle={toggleCustomRun}
                onCustomSet={setCustomRuns}
              />
            </div>
          )}
        </div>
      );
  }
}
