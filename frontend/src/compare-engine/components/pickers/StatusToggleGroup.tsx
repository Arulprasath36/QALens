import React from 'react';

const STATUS_OPTIONS = [
  { id: 'failed', label: 'Failed',  icon: '❌', color: 'text-red-400',     activeBg: 'bg-red-500/10     border-red-500/40'     },
  { id: 'flaky',  label: 'Flaky',   icon: '⚠️', color: 'text-amber-400',   activeBg: 'bg-amber-500/10   border-amber-500/40'   },
  { id: 'passed', label: 'Passed',  icon: '✅', color: 'text-emerald-400', activeBg: 'bg-emerald-500/10 border-emerald-500/40' },
  { id: 'skipped',label: 'Skipped', icon: '⏭',  color: 'text-zinc-400',    activeBg: 'bg-zinc-500/10    border-zinc-500/40'    },
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
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg border font-medium text-sm',
              'transition-all duration-150 cursor-pointer',
              active
                ? `${opt.activeBg} ${opt.color}`
                : 'bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200',
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
