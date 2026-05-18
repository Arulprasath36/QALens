import { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react';
import { Tooltip } from '../../../components/Tooltip';
import type { Owner } from '../../types';

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function failureRateBadge(rate: number): { label: string; className: string } {
  if (rate >= 0.35) return { label: `${Math.round(rate * 100)}%`, className: 'qalens-badge-danger'   };
  if (rate >= 0.15) return { label: `${Math.round(rate * 100)}%`, className: 'qalens-badge-warning' };
  return              { label: `${Math.round(rate * 100)}%`, className: 'qalens-badge-success' };
}

function FailureBadge({ rate }: { rate: number }) {
  const { label, className } = failureRateBadge(rate);
  return <span className={className}>{label}</span>;
}

function CheckIcon({ checked }: { checked: boolean }) {
  return (
    <div className={[
      'w-4 h-4 rounded-[0.4rem] flex items-center justify-center flex-shrink-0 transition-all duration-150',
      checked
        ? 'bg-selected border border-info text-info'
        : 'border border-border-default bg-surface',
    ].join(' ')}>
      {checked && (
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none" className="text-current">
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
  owner:     Owner;
  checked:   boolean;
  focused:   boolean;
  disabled:  boolean;
  onSelect:  (id: string) => void;
}

function OwnerRow({ owner, checked, focused, disabled, onSelect }: OwnerRowProps) {
  return (
    <button
      onClick={() => onSelect(owner.id)}
      className={[
        'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left',
        'transition-all duration-150',
        disabled && !checked
          ? 'opacity-35 cursor-not-allowed'
          : checked
            ? 'bg-selected text-primary cursor-pointer'
            : focused
              ? 'bg-hover cursor-pointer'
              : 'hover:bg-hover cursor-pointer',
      ].join(' ')}
    >
      <CheckIcon checked={checked} />

      <div className={[
        'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 transition-colors duration-150',
        checked ? 'bg-info/10 text-info border border-info/20' : 'bg-surface-subtle text-muted border border-border-subtle',
      ].join(' ')}>
        {owner.name.charAt(0)}
      </div>

      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium truncate text-primary">{owner.name}</span>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[11px] text-muted">{owner.testCount} tests</span>
          {owner.flakyCount > 0 && (
            <>
              <span className="text-border-strong">•</span>
              <span className="text-[11px] text-muted">{owner.flakyCount} flaky</span>
            </>
          )}
        </div>
      </div>

      <FailureBadge rate={owner.failureRate} />
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// Main OwnerPicker
// ─────────────────────────────────────────────────────────────

interface OwnerPickerProps {
  owners:        Owner[];
  selected:      string[];
  onToggle:      (id: string) => void;
  maxSelections: number;
}

export function OwnerPicker({ owners, selected, onToggle, maxSelections }: OwnerPickerProps) {
  const [open,     setOpen]     = useState(false);
  const [query,    setQuery]    = useState('');
  const [focusIdx, setFocusIdx] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLInputElement>(null);

  const atMax          = selected.length >= maxSelections;
  const selectedOwners = owners.filter(o => selected.includes(o.id));

  const filtered = owners.filter(o =>
    query === '' || o.name.toLowerCase().includes(query.toLowerCase())
  );

  // ── When user clicks a disabled row, flash the limit message ─

  function handleRowSelect(id: string) {
    if (!selected.includes(id) && atMax) return;
    onToggle(id);
  }

  // ── Keyboard navigation ──────────────────────────────────────

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
        if (filtered[focusIdx]) handleRowSelect(filtered[focusIdx].id);
        break;
      case 'Escape':
        setOpen(false);
        break;
    }
  }, [filtered, focusIdx, handleRowSelect]);

  // ── Click outside ─────────────────────────────────────────────

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setFocusIdx(0);
      setQuery('');
    }
  }, [open]);

  // ──────────────────────────────────────────────────────────────

  return (
    <div ref={containerRef} className="relative">

      {/* ── Trigger ───────────────────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        className={[
          'qalens-control flex items-center gap-2 h-auto min-h-[2.75rem] px-3 py-2 text-sm min-w-[220px] w-full',
          'transition-all duration-150',
          open ? 'qalens-pill-active' : '',
        ].join(' ')}
      >
        {selectedOwners.length === 0 ? (
          <span className="text-muted">Search owners…</span>
        ) : (
          <div className="flex items-center gap-1.5 flex-wrap flex-1">
            {selectedOwners.map(o => (
              <span
                key={o.id}
                className="inline-flex items-center gap-1 qalens-pill qalens-pill-active pr-1"
              >
                <span>{o.name.split(' ')[0]}</span>
                <Tooltip content={`Remove ${o.name}`} className="inline-flex">
                  <button
                    onClick={e => { e.stopPropagation(); onToggle(o.id); }}
                    className="flex h-3.5 w-3.5 items-center justify-center rounded hover:text-danger transition-colors flex-shrink-0"
                  >
                    <svg width="7" height="7" viewBox="0 0 10 10" fill="none">
                      <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                    </svg>
                  </button>
                </Tooltip>
              </span>
            ))}
            {!atMax && (
              <span className="text-muted text-xs">+ pick {maxSelections - selectedOwners.length} more</span>
            )}
          </div>
        )}
        <svg
          width="12" height="12" viewBox="0 0 12 12" fill="none"
          className={`ml-auto flex-shrink-0 text-muted transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        >
          <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {/* ── Popover ───────────────────────────────────────────── */}
      {open && (
        <div className="absolute left-0 top-[calc(100%+6px)] z-50 w-[320px] qalens-card-elevated qalens-fade-up">

          {/* Search + count badge */}
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border-subtle">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-muted flex-shrink-0">
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
              className="flex-1 bg-transparent text-sm text-primary placeholder:text-muted outline-none"
            />
            <span className={[
              'text-[10px] font-bold px-1.5 py-0.5 rounded-full border tabular-nums flex-shrink-0',
              atMax
                ? 'bg-warning/10 text-warning border-warning/25'
                : selected.length > 0
                  ? 'bg-info/10 text-info border-info/20'
                  : 'bg-surface-raised text-muted border-border-default',
            ].join(' ')}>
              {selected.length}/{maxSelections}
            </span>
            {query && (
              <button onClick={() => setQuery('')} className="text-muted hover:text-primary transition-colors">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </button>
            )}
          </div>

          {/* Persistent limit banner — visible whenever at max */}
          {atMax && (
            <div className="mx-2 mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-warning/10 border border-warning/20 text-warning text-xs font-medium">
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="flex-shrink-0">
                <path d="M8 2L1 14h14L8 2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
                <path d="M8 7v3M8 12v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              Maximum {maxSelections} owners selected. Remove one to add another.
            </div>
          )}

          {/* Owner list */}
          <div className="max-h-[300px] overflow-y-auto p-1.5 space-y-0.5">
            {filtered.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted">
                No owners match "{query}"
              </div>
            ) : (
              filtered.map((owner, idx) => (
                <OwnerRow
                  key={owner.id}
                  owner={owner}
                  checked={selected.includes(owner.id)}
                  focused={focusIdx === idx}
                  disabled={atMax && !selected.includes(owner.id)}
                  onSelect={handleRowSelect}
                />
              ))
            )}
          </div>

          {/* Footer */}
          {selected.length > 0 && (
            <div className="flex items-center justify-end px-3 py-2 border-t border-border-subtle">
              <button
                onClick={() => selected.forEach(id => onToggle(id))}
                className="text-[11px] text-muted hover:text-primary transition-colors"
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
