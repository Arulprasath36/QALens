import React from 'react';
import type { Suite } from '../../types';

interface SuitePickerProps {
  suites:   Suite[];
  selected: string[];
  onToggle: (id: string) => void;
}

export function SuitePicker({ suites, selected, onToggle }: SuitePickerProps) {
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
              'inline-flex items-center gap-2 px-3 py-2 rounded-lg border text-sm',
              'transition-all duration-150 cursor-pointer',
              active
                ? 'bg-violet-500/10 border-violet-500/40 text-zinc-100'
                : 'bg-zinc-900 border-zinc-700 hover:border-zinc-500 text-zinc-300',
            ].join(' ')}
          >
            <span className="font-medium">{suite.name}</span>
            {highRisk && <span className="text-[11px]">⚠️</span>}
            <span className={[
              'text-[10px] rounded-full px-1.5 py-0.5',
              active ? 'bg-violet-500/20 text-violet-300' : 'bg-zinc-800 text-zinc-500',
            ].join(' ')}>
              {suite.testCount}
            </span>
          </button>
        );
      })}
      {selected.length === 2 && (
        <div className="inline-flex items-center text-[11px] text-violet-400 font-medium px-2 py-1 rounded bg-violet-500/10 border border-violet-500/20">
          ✓ Ready
        </div>
      )}
    </div>
  );
}
