
const STATUS_OPTIONS = [
  { id: 'failed', label: 'Failed',  icon: '❌', color: 'text-danger',  activeBg: 'qara-chip-active' },
  { id: 'flaky',  label: 'Flaky',   icon: '⚠️', color: 'text-warning', activeBg: 'qara-chip-active' },
  { id: 'passed', label: 'Passed',  icon: '✅', color: 'text-success', activeBg: 'qara-chip-active' },
  { id: 'skipped',label: 'Skipped', icon: '⏭',  color: 'text-muted',   activeBg: 'qara-chip-active' },
] as const;

interface StatusToggleGroupProps {
  selected: string[];
  onToggle: (id: string) => void;
}

export function StatusToggleGroup({ selected, onToggle }: StatusToggleGroupProps) {
  return (
    <div className="flex items-center gap-2">
      {STATUS_OPTIONS.map(opt => {
        const active = selected.includes(opt.id);
        return (
          <button
            key={opt.id}
            onClick={() => onToggle(opt.id)}
            className={[
              'qara-chip inline-flex items-center gap-2 font-medium text-sm cursor-pointer',
              active
                ? `${opt.activeBg} ${opt.color}`
                : 'text-muted',
            ].join(' ')}
          >
            <span>{opt.icon}</span>
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
