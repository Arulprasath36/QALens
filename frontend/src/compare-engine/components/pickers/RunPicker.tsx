import React from 'react';
import type { Run, TimeMode } from '../../types';

interface RunPickerProps {
  runs:           Run[];
  selected:       string[];
  onToggle:       (id: string) => void;
  onCustomSelect: (ids: string[]) => void;
  timeMode:       TimeMode;
}

function passRateColor(rate: number) {
  if (rate >= 0.9) return 'text-emerald-400';
  if (rate >= 0.7) return 'text-amber-400';
  return 'text-red-400';
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function RunPicker({ runs, selected, onToggle, timeMode }: RunPickerProps) {
  if (timeMode === 'latest_vs_previous' && runs.length >= 2) {
    const latest = runs[0];
    const prev   = runs[1];
    const autoSelected = [latest.id, prev.id];

    return (
      <div className="flex items-center gap-2">
        <RunChip run={latest} active={autoSelected.includes(latest.id)} onClick={() => {}} />
        <span className="text-xs text-zinc-600 font-medium">vs</span>
        <RunChip run={prev}   active={autoSelected.includes(prev.id)}   onClick={() => {}} />
        <span className="text-[10px] text-zinc-600 italic ml-1">Auto-selected</span>
      </div>
    );
  }

  const limit = timeMode === 'last5' ? 5 : timeMode === 'last10' ? 10 : runs.length;
  const visible = runs.slice(0, limit);

  return (
    <div className="flex flex-wrap gap-2">
      {visible.map(run => (
        <RunChip
          key={run.id}
          run={run}
          active={selected.includes(run.id)}
          onClick={() => onToggle(run.id)}
        />
      ))}
      {selected.length === 2 && (
        <div className="flex items-center gap-1 text-[11px] text-violet-400 font-medium px-2 py-1 rounded bg-violet-500/10 border border-violet-500/20">
          ✓ Ready to compare
        </div>
      )}
    </div>
  );
}

function RunChip({ run, active, onClick }: { run: Run; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={[
        'flex flex-col items-start px-3 py-2 rounded-lg border text-left',
        'transition-all duration-150 cursor-pointer',
        active
          ? 'bg-violet-500/10 border-violet-500/40 ring-1 ring-violet-500/20'
          : 'bg-zinc-900 border-zinc-700 hover:border-zinc-500',
      ].join(' ')}
    >
      <span className="text-xs font-semibold text-zinc-100">{run.label}</span>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className="text-[10px] text-zinc-500">{fmtDate(run.startedAt)}</span>
        <span className="text-zinc-700">·</span>
        <span className={`text-[10px] font-medium ${passRateColor(run.passRate)}`}>
          {Math.round(run.passRate * 100)}%
        </span>
      </div>
    </button>
  );
}
