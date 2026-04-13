import React, { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react';
import type { Owner } from '../../types';

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function failureRateBadge(rate: number): { label: string; className: string } {
  if (rate >= 0.35) return { label: `${Math.round(rate * 100)}%`, className: 'bg-red-500/20 text-red-400 border border-red-500/30'   };
  if (rate >= 0.15) return { label: `${Math.round(rate * 100)}%`, className: 'bg-amber-500/20 text-amber-400 border border-amber-500/30' };
  return              { label: `${Math.round(rate * 100)}%`, className: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' };
}

function FailureBadge({ rate }: { rate: number }) {
  const { label, className } = failureRateBadge(rate);
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${className}`}>
      {label}
    </span>
  );
}

function CheckIcon({ checked }: { checked: boolean }) {
  return (
    <div
      className={[
        'w-4 h-4 rounded flex items-center justify-center flex-shrink-0 transition-all duration-150',
        checked
          ? 'bg-violet-500 border border-violet-400'
          : 'border border-zinc-600 bg-transparent',
      ].join(' ')}
    >
      {checked && (
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none" className="text-white">
          <path d="M1 4l2.5 2.5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Owner row
// ─────────────────────────────────────────────────────────────

interface OwnerRowProps {
  owner:    Owner;
  checked:  boolean;
  focused:  boolean;
  onSelect: (id: string) => void;
}

function OwnerRow({ owner, checked, focused, onSelect }: OwnerRowProps) {
  return (
    <button
      onClick={() => onSelect(owner.id)}
      className={[
        'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left',
        'transition-all duration-100 cursor-pointer group',
        checked ? 'bg-violet-500/10 hover:bg-violet-500/15' :
        focused  ? 'bg-zinc-800'                             :
                   'hover:bg-zinc-800/70',
      ].join(' ')}
    >
      {/* Checkmark */}
      <CheckIcon checked={checked} />

      {/* Avatar initial */}
      <div
        className={[
          'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0',
          'transition-colors duration-150',
          checked ? 'bg-violet-500/30 text-violet-200' : 'bg-zinc-700 text-zinc-300',
        ].join(' ')}
      >
        {owner.name.charAt(0)}
      </div>

      {/* Name + stats */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium truncate ${checked ? 'text-zinc-100' : 'text-zinc-200'}`}>
            {owner.name}
          </span>
          {owner.failureRate >= 0.35 && (
            <span className="text-amber-400 text-[11px]" title="High failure rate">⚠️</span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[11px] text-zinc-500">{owner.testCount} tests</span>
          {owner.flakyCount > 0 && (
            <>
              <span className="text-zinc-700">·</span>
              <span className="text-[11px] text-zinc-500">{owner.flakyCount} flaky</span>
            </>
          )}
        </div>
      </div>

      {/* Failure rate badge */}
      <FailureBadge rate={owner.failureRate} />
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// Main OwnerPicker
// ─────────────────────────────────────────────────────────────

interface OwnerPickerProps {
  owners:   Owner[];
  selected: string[];
  onToggle: (id: string) => void;
}

export function OwnerPicker({ owners, selected, onToggle }: OwnerPickerProps) {
  const [open,    setOpen]    = useState(false);
  const [query,   setQuery]   = useState('');
  const [focusIdx, setFocusIdx] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLInputElement>(null);

  // Filter + sort: selected first, then by name
  const filtered = owners.filter(o =>
    query === '' ||
    o.name.toLowerCase().includes(query.toLowerCase())
  );

  const selectedOwners = owners.filter(o => selected.includes(o.id));

  // ── Keyboard navigation ──────────────────────────────────

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setFocusIdx(i => Math.min(i + 1, filtered.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setFocusIdx(i => Math.max(i - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        if (filtered[focusIdx]) onToggle(filtered[focusIdx].id);
        break;
      case 'Escape':
        setOpen(false);
        break;
    }
  }, [filtered, focusIdx, onToggle]);

  // ── Click outside ────────────────────────────────────────

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setFocusIdx(0);
      setQuery('');
    }
  }, [open]);

  // ─────────────────────────────────────────────────────────

  return (
    <div ref={containerRef} className="relative">

      {/* ── Trigger ─────────────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        className={[
          'flex items-center gap-2 h-[38px] px-3 rounded-lg border text-sm',
          'transition-all duration-150 min-w-[220px]',
          open
            ? 'bg-zinc-800 border-violet-500 ring-1 ring-violet-500/20 text-zinc-100'
            : 'bg-zinc-900 border-zinc-700 hover:border-zinc-500 text-zinc-300',
        ].join(' ')}
      >
        {selectedOwners.length === 0 ? (
          <span className="text-zinc-500">Search owners…</span>
        ) : (
          <div className="flex items-center gap-1.5">
            {selectedOwners.map(o => (
              <span
                key={o.id}
                className="inline-flex items-center rounded-full bg-violet-500/20 border border-violet-500/30 px-2 py-0.5 text-[11px] font-medium text-violet-200"
              >
                {o.name.split(' ')[0]}
              </span>
            ))}
            {selectedOwners.length < 2 && (
              <span className="text-zinc-500 text-xs">+ pick {2 - selectedOwners.length} more</span>
            )}
          </div>
        )}
        <svg
          width="12" height="12" viewBox="0 0 12 12" fill="none"
          className={`ml-auto flex-shrink-0 text-zinc-500 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        >
          <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {/* ── Popover ──────────────────────────────────────── */}
      {open && (
        <div
          className={[
            'absolute left-0 top-[calc(100%+6px)] z-50',
            'w-[320px] rounded-xl border border-zinc-700/80',
            'bg-zinc-900 shadow-2xl shadow-black/50',
            'animate-in fade-in slide-in-from-top-1 duration-150',
          ].join(' ')}
        >
          {/* Search */}
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-zinc-800">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-zinc-500 flex-shrink-0">
              <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={e => { setQuery(e.target.value); setFocusIdx(0); }}
              onKeyDown={handleKeyDown}
              placeholder="Search by name…"
              className="flex-1 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 outline-none"
            />
            {query && (
              <button onClick={() => setQuery('')} className="text-zinc-600 hover:text-zinc-400 transition-colors">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </button>
            )}
          </div>

          {/* Owner list */}
          <div className="max-h-[300px] overflow-y-auto p-1.5 space-y-0.5">
            {filtered.length === 0 ? (
              <div className="text-center py-8 text-sm text-zinc-600">
                No owners match "{query}"
              </div>
            ) : (
              filtered.map((owner, idx) => (
                <OwnerRow
                  key={owner.id}
                  owner={owner}
                  checked={selected.includes(owner.id)}
                  focused={focusIdx === idx}
                  onSelect={id => { onToggle(id); }}
                />
              ))
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-3 py-2 border-t border-zinc-800">
            <span className="text-[11px] text-zinc-600">
              {selected.length}/2 selected · ↑↓ navigate · ↵ select
            </span>
            {selected.length > 0 && (
              <button
                onClick={() => { selected.forEach(id => onToggle(id)); }}
                className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
