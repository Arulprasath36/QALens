import type { Suite } from '../../types';

interface SuitePickerProps {
  suites:        Suite[];
  selected:      string[];
  onToggle:      (id: string) => void;
  maxSelections: number;
}

export function SuitePicker({ suites, selected, onToggle, maxSelections }: SuitePickerProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {suites.map(suite => {
        const active = selected.includes(suite.id);
        const highRisk = suite.failureRate >= 0.35;

        return (
          <button
            key={suite.id}
            onClick={() => onToggle(suite.id)}
            className={[
              'qara-chip inline-flex items-center gap-2 text-sm cursor-pointer',
              active
                ? 'qara-chip-active'
                : '',
            ].join(' ')}
          >
            <span className="font-medium">{suite.name}</span>
            {highRisk && <span className="text-[11px]" title="Higher failure rate">⚠️</span>}
            <span className={[
              'text-[10px] rounded-full px-1.5 py-0.5 border',
              active ? 'border-info/20 bg-selected text-primary' : 'border-border-subtle bg-surface-subtle text-muted',
            ].join(' ')}>
              {suite.testCount}
            </span>
          </button>
      );
      })}
      {selected.length >= 2 && selected.length <= maxSelections && (
        <div className="qara-badge-info">
          ✓ Ready ({selected.length}/{maxSelections})
        </div>
      )}
    </div>
  );
}
