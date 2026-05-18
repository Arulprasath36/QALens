import { useState } from 'react';
import { Tooltip } from '../../../components/Tooltip';
import type { Suite } from '../../types';

interface SuitePickerProps {
  suites:        Suite[];
  selected:      string[];
  onToggle:      (id: string) => void;
  maxSelections: number;
  timeLabel?:    string;
  canCompare?:   boolean;
}

// ── Progress hint text based on selection count ────────────────
function progressHint(count: number, max: number): { text: string; tone: string } {
  if (count === 0) return { text: `Add 2–${max} suites to start your comparison`, tone: 'text-muted' };
  if (count === 1) return { text: 'Add 1 more suite to compare',                   tone: 'text-warning' };
  if (count < max) return { text: 'Ready — add 1 more for a deeper comparison',    tone: 'text-success' };
  return              { text: `Maximum reached · ${max} suites selected`,           tone: 'text-info'    };
}

export function SuitePicker({ suites, selected, onToggle, maxSelections, timeLabel, canCompare }: SuitePickerProps) {
  const atMax = selected.length >= maxSelections;
  const hint  = progressHint(selected.length, maxSelections);

  // Track the last-selected id so its source chip can animate out
  const [leaving, setLeaving] = useState<string | null>(null);

  function handleToggle(id: string) {
    if (!selected.includes(id)) {
      // about to be added — animate source chip out first
      setLeaving(id);
      setTimeout(() => setLeaving(null), 200);
    }
    onToggle(id);
  }

  return (
    <div className="space-y-3">

      {/* ══════════════════════════════════════════════════════
          FOCAL AREA — Your comparison (top, most prominent)
      ══════════════════════════════════════════════════════ */}
      <div className={[
        'rounded-xl border-2 transition-all duration-200',
        selected.length === 0
          ? 'border-info/20 bg-info/[0.04]'  // inviting, not a drag-drop zone
          : canCompare
            ? 'border-success/30 bg-success/[0.03]'
            : 'border-info/25 bg-surface',
      ].join(' ')}>

        {/* Header row */}
        <div className="flex items-center justify-between px-4 pt-3 pb-1.5">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">
              Your comparison
            </p>
            <span className={[
              'text-[10px] font-bold px-1.5 py-0.5 rounded-full border tabular-nums transition-colors',
              selected.length >= 2
                ? 'bg-success/10 text-success border-success/25'
                : selected.length === 1
                  ? 'bg-warning/10 text-warning border-warning/25'
                  : 'bg-surface-raised text-muted border-border-default',
            ].join(' ')}>
              {selected.length}/{maxSelections}
            </span>
          </div>

          {/* Time label — shown when comparing */}
          {canCompare && timeLabel && (
            <div className="flex items-center gap-1 text-[11px] font-medium text-success">
              <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
                <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M8 5v3.5l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <span>{timeLabel}</span>
            </div>
          )}
        </div>

        {/* Content area */}
        <div className="px-4 pb-3">
          {selected.length === 0 ? (
            /* Commanding empty prompt — no icon, two clear lines */
            <div className="py-1.5">
              <p className="text-sm font-semibold text-primary leading-snug">
                Add suites to start comparison
              </p>
              <p className="text-xs text-muted mt-0.5">
                Select 2–3 suites below · Compare pass rate, failures &amp; flakiness
              </p>
            </div>
          ) : (
            /* Selected chips — removable, animated on entry */
            <div className="flex flex-wrap gap-2">
              {selected.map(id => {
                const suite = suites.find(s => s.id === id);
                if (!suite) return null;
                return (
                  <div
                    key={id}
                    className="chip-enter group inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-lg border border-info/30 bg-surface text-sm font-medium text-primary shadow-sm transition-all duration-150 hover:border-danger/35 hover:bg-danger/5"
                  >
                    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" className="text-info group-hover:text-danger/60 transition-colors flex-shrink-0">
                      <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span>{suite.name}</span>
                    <Tooltip content={`Remove ${suite.name}`} className="inline-flex flex-shrink-0">
                      <button
                        onClick={() => onToggle(id)}
                        className="flex h-4 w-4 items-center justify-center rounded text-muted hover:text-danger transition-colors"
                      >
                        <svg width="8" height="8" viewBox="0 0 10 10" fill="none">
                          <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>
                        </svg>
                      </button>
                    </Tooltip>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Progress bar footer */}
        <div className="border-t border-border-subtle px-4 py-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              {Array.from({ length: maxSelections }).map((_, i) => (
                <div
                  key={i}
                  className={[
                    'h-1.5 rounded-full transition-all duration-300',
                    i < selected.length
                      ? selected.length >= 2 ? 'w-5 bg-success' : 'w-5 bg-warning'
                      : 'w-2 bg-border-strong',
                  ].join(' ')}
                />
              ))}
            </div>
            <p className={`text-[11px] font-medium ${hint.tone}`}>{hint.text}</p>
          </div>

        </div>
      </div>

      {/* ══════════════════════════════════════════════════════
          SECONDARY — Available suites to pick from
      ══════════════════════════════════════════════════════ */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-secondary">
          Pick suites to compare
        </p>
        <div className="flex flex-wrap gap-2">
          {suites.map(suite => {
            const isSelected = selected.includes(suite.id);
            const isDisabled = atMax && !isSelected;
            const highRisk   = suite.failureRate >= 0.35;

            const option = (
              <button
                onClick={() => handleToggle(suite.id)}
                disabled={isDisabled}
                className={[
                  'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium',
                  'transition-all duration-150',
                  isSelected
                    ? 'bg-selected border-info/35 text-primary shadow-sm'
                    : isDisabled
                      ? 'border-border-subtle text-muted/30 cursor-not-allowed'
                      : [
                          'border-border-strong/40 bg-surface-subtle text-primary cursor-pointer shadow-sm',
                          'hover:border-info/60 hover:bg-info/[0.07] hover:shadow hover:scale-[1.02]',
                          leaving === suite.id ? 'opacity-0 scale-90 transition-all duration-150' : '',
                        ].join(' '),
                ].join(' ')}
              >
                {isSelected ? (
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none" className="text-info flex-shrink-0">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                ) : !isDisabled ? (
                  <svg width="9" height="9" viewBox="0 0 10 10" fill="none" className="text-muted/55 flex-shrink-0">
                    <path d="M5 1v8M1 5h8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
                  </svg>
                ) : null}

                <span>{suite.name}</span>

                {highRisk && (
                  <Tooltip content="Higher failure rate" className="inline-flex">
                    <span className="text-[11px]">⚠️</span>
                  </Tooltip>
                )}

                <span className={[
                  'text-[10px] rounded-full px-1.5 py-0.5 border tabular-nums',
                  isSelected
                    ? 'border-info/20 bg-info/10 text-info'
                    : isDisabled
                      ? 'border-border-subtle text-muted/25'
                      : 'border-border-subtle bg-surface text-muted',
                ].join(' ')}>
                  {suite.testCount}
                </span>
              </button>
            );

            if (isDisabled) {
              return (
                <Tooltip key={suite.id} content={`Maximum ${maxSelections} suites selected`} className="inline-flex">
                  <span>{option}</span>
                </Tooltip>
              );
            }

            return <span key={suite.id} className="inline-flex">{option}</span>;
          })}
        </div>
      </div>

    </div>
  );
}
