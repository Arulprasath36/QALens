import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from '../../../components/Modal';
import { Tooltip } from '../../../components/Tooltip';
import type { Run, TimeMode } from '../../types';

interface RunPickerProps {
  runs:           Run[];
  selected:       string[];
  timeMode:       TimeMode;
  onCustomToggle: (id: string) => void;
  onCustomSet?:   (ids: string[]) => void;
}

function passRateColor(rate: number) {
  if (rate >= 0.9) return 'text-success';
  if (rate >= 0.7) return 'text-warning';
  return 'text-danger';
}

function fmtDate(iso: string) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function buildRunSearchText(run: Run) {
  return [run.label, fmtDate(run.startedAt), `${Math.round(run.passRate * 100)}%`, `${run.failedCount}`, `${run.totalTests}`]
    .join(' ')
    .toLowerCase();
}

// ─────────────────────────────────────────────────────────────
// latest_vs_previous: clean pairwise display
// ─────────────────────────────────────────────────────────────

function PairwisePicker({ runs }: { runs: Run[] }) {
  if (runs.length < 2) {
    return <span className="text-xs text-muted italic">Loading runs…</span>;
  }

  const latest = runs[0];
  const prev   = runs[1];
  const dateRange = `${fmtDate(prev.startedAt)} → ${fmtDate(latest.startedAt)}`;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <CompactRunChip run={latest} />
        <span className="text-xs font-medium text-muted px-2 py-1 border border-border-subtle rounded-full">vs</span>
        <CompactRunChip run={prev} />
        <span className="text-[10px] text-muted italic ml-2">Auto-selected</span>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-medium">Comparing latest vs previous</span>
        {dateRange && <><span>•</span><span>{dateRange}</span></>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// last5 / last10: horizontal scrolling run cards
// ─────────────────────────────────────────────────────────────

function AutoHistoryPicker({ timeMode, runs }: { timeMode: TimeMode; runs: Run[] }) {
  const limit   = timeMode === 'last5' ? 5 : 10;
  const visible = runs.slice(0, limit);

  if (visible.length === 0) return <span className="text-xs text-muted italic">Loading runs…</span>;

  const dateRange = visible.length >= 2
    ? `${fmtDate(visible[visible.length - 1].startedAt)} → ${fmtDate(visible[0].startedAt)}`
    : fmtDate(visible[0]?.startedAt || '');

  return (
    <div className="space-y-2">
      <div className="relative">
        <div className="flex gap-2 overflow-x-auto pb-1 scroll-smooth" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgb(203 213 225) transparent' }}>
          {visible.map(run => <CompactRunChip key={run.id} run={run} />)}
        </div>
        {visible.length > 4 && (
          <div className="absolute right-0 top-0 bottom-1 w-8 bg-gradient-to-l from-surface to-transparent pointer-events-none" />
        )}
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-medium">Showing last {visible.length} run{visible.length !== 1 ? 's' : ''}</span>
        {dateRange && <><span>•</span><span>{dateRange}</span></>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// custom: modal-based multi-select
// ─────────────────────────────────────────────────────────────

function scrollToResults() {
  document.getElementById('compare-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function syncCustomSelection(
  nextIds:        string[],
  currentIds:     string[],
  onCustomToggle: (id: string) => void,
  onCustomSet?:   (ids: string[]) => void,
) {
  if (onCustomSet) { onCustomSet(nextIds); return; }
  currentIds.forEach(id => onCustomToggle(id));
  nextIds.forEach(id => onCustomToggle(id));
}

// ── Trigger card ──────────────────────────────────────────────

function CustomRangeTrigger({
  selectedRuns,
  onOpen,
  onRemove,
}: {
  selectedRuns: Run[];
  onOpen:       () => void;
  onRemove:     (id: string) => void;
}) {
  const hasSelection = selectedRuns.length > 0;
  const isReady      = selectedRuns.length >= 2;

  // Title + description based on state
  const title = hasSelection
    ? isReady
      ? `Comparing trends across ${selectedRuns.length} runs`
      : selectedRuns[0].label
    : 'Build your comparison';

  const description = hasSelection
    ? isReady
      ? 'View flakiness trends, regressions, and stability over time'
      : 'Add 1 more run to start comparing'
    : 'Select runs to analyze trends and changes over time';

  const CHIP_LIMIT = 4;
  const visibleRuns  = selectedRuns.slice(0, CHIP_LIMIT);
  const hiddenCount  = selectedRuns.length - CHIP_LIMIT;

  return (
    <div className={[
      'flex flex-col gap-3 rounded-[1.2rem] border-2 px-4 py-4 transition-all duration-200',
      isReady
        ? 'border-success/25 bg-success/[0.02]'
        : hasSelection
          ? 'border-info/20 bg-surface'
          : 'border-info/15 bg-info/[0.02]',
    ].join(' ')}>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted mb-1">
            Custom range
          </p>
          <p className="text-sm font-semibold text-primary">{title}</p>
          <p className="mt-0.5 text-xs text-muted">{description}</p>
        </div>

        <div className="flex items-center gap-2">
          {hasSelection && (
            <span className={[
              'text-[10px] font-bold px-2 py-1 rounded-full border tabular-nums',
              isReady
                ? 'bg-success/10 text-success border-success/25'
                : 'bg-warning/10 text-warning border-warning/25',
            ].join(' ')}>
              {selectedRuns.length} selected
            </span>
          )}
          <button type="button" onClick={onOpen} className={[
            'qara-chip type-chip',
            !hasSelection && 'border-info/30 text-info hover:bg-info/5',
          ].join(' ')}>
            {hasSelection ? 'Edit selection' : 'Pick runs to compare'}
          </button>
        </div>
      </div>

      {/* Selected chips with remove buttons */}
      {hasSelection && (
        <div className="flex flex-wrap items-center gap-2">
          {visibleRuns.map((run, index) => (
            <div
              key={run.id}
              className={[
                'group inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-lg border text-xs font-medium text-primary',
                'shadow-sm hover:shadow transition-all duration-150',
                chipColor(run.passRate),
              ].join(' ')}
            >
              {selectedRuns.length === 2 && (
                <span className="text-[10px] text-faint font-semibold">{index === 0 ? 'A' : 'B'}</span>
              )}
              <span className={`font-bold ${passRateColor(run.passRate)}`}>
                {Math.round(run.passRate * 100)}%
              </span>
              <span>{run.label}</span>
              <Tooltip content={`Remove ${run.label}`} className="inline-flex flex-shrink-0">
                <button
                  onClick={(e) => { e.stopPropagation(); onRemove(run.id); }}
                  className="flex h-4 w-4 items-center justify-center rounded text-muted hover:text-danger transition-colors"
                >
                  <svg width="8" height="8" viewBox="0 0 10 10" fill="none">
                    <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
          ))}

          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={onOpen}
              className="text-xs text-info hover:text-primary font-medium transition-colors"
            >
              View all selected runs ({selectedRuns.length})
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Chip pass-rate border/bg color ───────────────────────────

function chipColor(rate: number): string {
  if (rate >= 0.8) return 'border-success/30 bg-success/[0.04] hover:border-success/50 hover:bg-success/[0.08]';
  if (rate >= 0.6) return 'border-warning/30 bg-warning/[0.04] hover:border-warning/50 hover:bg-warning/[0.08]';
  return 'border-danger/30 bg-danger/[0.04] hover:border-danger/50 hover:bg-danger/[0.08]';
}

// ── Modal run row ─────────────────────────────────────────────

function ModalRunRow({ run, selected, onToggle }: { run: Run; selected: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={[
        'relative w-full flex items-center gap-3 rounded-[0.875rem] border pl-0 pr-3 py-3 text-left transition-all duration-150 overflow-hidden',
        selected
          ? 'border-info/25 bg-info/[0.04] shadow-sm'
          : 'border-transparent hover:border-border-default hover:bg-hover',
      ].join(' ')}
    >
      {/* Left accent bar — selected state */}
      <div className={[
        'absolute left-0 top-0 bottom-0 w-[3px] rounded-l-[0.875rem] transition-all duration-150',
        selected ? 'bg-info' : 'bg-transparent',
      ].join(' ')} />

      {/* Checkbox — tucked after accent bar */}
      <div className="pl-3 flex-shrink-0">
        <span
          className={[
            'inline-flex h-4 w-4 items-center justify-center rounded border text-[10px] font-bold transition-all',
            selected
              ? 'border-info/50 bg-info/15 text-info'
              : 'border-border-default bg-surface text-transparent',
          ].join(' ')}
          aria-hidden="true"
        >
          ✓
        </span>
      </div>

      {/* Main content */}
      <div className="min-w-0 flex-1">
        {/* Primary line: pass rate (dominant) + run label */}
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={`text-base font-bold tabular-nums leading-none ${passRateColor(run.passRate)}`}>
            {Math.round(run.passRate * 100)}%
          </span>
          <span className={['text-sm font-semibold truncate', selected ? 'text-primary' : 'text-secondary'].join(' ')}>
            {run.label}
          </span>
        </div>
        {/* Secondary line: metadata */}
        <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
          <span className="text-xs text-muted">{fmtDate(run.startedAt)}</span>
          <span className="text-faint text-[10px]">·</span>
          <span className="text-xs text-muted">{run.totalTests} tests</span>
          {run.failedCount > 0 && (
            <>
              <span className="text-faint text-[10px]">·</span>
              <span className="text-xs font-medium text-danger">{run.failedCount} failed</span>
            </>
          )}
          {run.branch && (
            <>
              <span className="text-faint text-[10px]">·</span>
              <span className="qara-pill">{run.branch}</span>
            </>
          )}
        </div>
      </div>

      {/* Run sequence — right-aligned */}
      <div className="text-right text-[11px] text-muted shrink-0 tabular-nums">
        #{run.sequence}
      </div>
    </button>
  );
}

// ── Modal ─────────────────────────────────────────────────────

function CustomRangeModal({
  open,
  runs,
  draftSelected,
  setDraftSelected,
  onClose,
  onApply,
}: {
  open:             boolean;
  runs:             Run[];
  draftSelected:    string[];
  setDraftSelected: (ids: string[]) => void;
  onClose:          () => void;
  onApply:          () => void;
}) {
  const [search, setSearch] = useState('');
  const selectedBarRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (!open) setSearch(''); }, [open]);

  const filteredRuns = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return runs;
    return runs.filter(run => buildRunSearchText(run).includes(query));
  }, [runs, search]);

  const draftRuns = useMemo(
    () => runs.filter(r => draftSelected.includes(r.id)),
    [runs, draftSelected],
  );

  const toggleDraft = (id: string) => {
    setDraftSelected(
      draftSelected.includes(id)
        ? draftSelected.filter(rid => rid !== id)
        : [...draftSelected, id],
    );
  };

  // Dynamic guidance
  const selectionHint = draftSelected.length === 0
    ? 'Select 2 runs to compare · 3+ for trends'
    : draftSelected.length === 1
      ? 'Select 1 more run to compare'
      : draftSelected.length === 2
        ? 'Pairwise comparison ready'
        : 'Trend analysis ready';

  const hintTone = draftSelected.length >= 2 ? 'text-success' : draftSelected.length === 1 ? 'text-warning' : 'text-muted';

  return (
    <Modal
      open={open}
      title="Build your comparison"
      meta={(
        <span className="text-sm text-muted">
          Select runs to analyze regressions, flakiness trends, and stability over time.
        </span>
      )}
      onClose={onClose}
      widthClassName="max-w-5xl"
      footer={(
        <>
          {/* Preset quick-selects */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mr-1">Quick</span>
            <button
              type="button"
              onClick={() => setDraftSelected(runs.slice(0, 2).map(r => r.id))}
              className="qara-chip type-chip"
            >
              Latest 2
            </button>
            <button
              type="button"
              onClick={() => setDraftSelected(runs.slice(0, 5).map(r => r.id))}
              className="qara-chip type-chip"
            >
              Last 5
            </button>
            <button
              type="button"
              onClick={() => setDraftSelected(runs.slice(0, 10).map(r => r.id))}
              className="qara-chip type-chip"
            >
              Last 10
            </button>
            {draftSelected.length > 0 && (
              <button
                type="button"
                onClick={() => setDraftSelected([])}
                className="qara-chip type-chip text-muted"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button type="button" onClick={onClose} className="qara-chip type-chip">
              Cancel
            </button>
            <button
              type="button"
              onClick={onApply}
              disabled={draftSelected.length === 0}
              className={[
                'qara-chip type-chip',
                draftSelected.length > 0 ? 'qara-chip-active' : 'opacity-40 cursor-not-allowed',
              ].join(' ')}
            >
              {draftSelected.length > 0 ? `Apply (${draftSelected.length} runs)` : 'Apply'}
            </button>
          </div>
        </>
      )}
    >
      <div className="space-y-3">

        {/* ── Sticky selected bar ────────────────────────────── */}
        <div
          ref={selectedBarRef}
          className={[
            'rounded-xl border-2 transition-all duration-200 overflow-hidden',
            draftSelected.length >= 2
              ? 'border-success/25 bg-success/[0.02]'
              : draftSelected.length === 1
                ? 'border-warning/25 bg-warning/[0.02]'
                : 'border-dashed border-border-default bg-surface-subtle',
          ].join(' ')}
        >
          <div className="flex items-center justify-between gap-3 px-3 py-2">
            <div className="flex items-center gap-2.5">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted flex-shrink-0">
                Selected
              </span>
              <span className={[
                'text-[10px] font-bold px-1.5 py-0.5 rounded-full border tabular-nums',
                draftSelected.length >= 2
                  ? 'bg-success/10 text-success border-success/25'
                  : draftSelected.length === 1
                    ? 'bg-warning/10 text-warning border-warning/25'
                    : 'bg-surface-raised text-muted border-border-default',
              ].join(' ')}>
                {draftSelected.length}
              </span>
              <p className={`text-[11px] font-medium ${hintTone}`}>{selectionHint}</p>
            </div>
          </div>

          {draftRuns.length > 0 && (
            <div className="flex flex-wrap gap-2 px-3 pb-2.5">
              {draftRuns.map((run, i) => (
                <div
                  key={run.id}
                  className={[
                    'chip-enter group inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-lg border text-xs font-medium text-primary',
                    'shadow-sm hover:shadow transition-all duration-150',
                    chipColor(run.passRate),
                  ].join(' ')}
                >
                  {draftSelected.length === 2 && (
                    <span className="text-[10px] text-faint font-semibold">{i === 0 ? 'A' : 'B'}</span>
                  )}
                  <span className={`font-bold ${passRateColor(run.passRate)}`}>
                    {Math.round(run.passRate * 100)}%
                  </span>
                  <span>{run.label}</span>
                  <Tooltip content={`Remove ${run.label}`} className="inline-flex flex-shrink-0">
                    <button
                      onClick={() => toggleDraft(run.id)}
                      className="flex h-4 w-4 items-center justify-center rounded text-muted hover:text-danger transition-colors"
                    >
                      <svg width="8" height="8" viewBox="0 0 10 10" fill="none">
                        <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>
                      </svg>
                    </button>
                  </Tooltip>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Search ─────────────────────────────────────────── */}
        <div className="qara-control w-full px-3">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="shrink-0 text-muted">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search runs…"
            className="qara-input h-11 text-sm"
          />
        </div>

        {/* ── Run list ───────────────────────────────────────── */}
        <div className="rounded-[1.2rem] border border-border-default bg-surface">
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">Run</span>
            <span className="text-[10px] text-muted">
              Sorted by: <span className="font-semibold">Latest runs</span>
            </span>
          </div>

          <div className="max-h-[26rem] overflow-y-auto p-2">
            {filteredRuns.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-muted">
                No runs match this search.
              </div>
            ) : (
              <div className="space-y-1">
                {filteredRuns.map(run => (
                  <ModalRunRow
                    key={run.id}
                    run={run}
                    selected={draftSelected.includes(run.id)}
                    onToggle={() => toggleDraft(run.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}

// ── CustomPicker orchestrator ─────────────────────────────────

function CustomPicker({
  runs,
  selected,
  onCustomToggle,
  onCustomSet,
}: {
  runs:           Run[];
  selected:       string[];
  onCustomToggle: (id: string) => void;
  onCustomSet?:   (ids: string[]) => void;
}) {
  const [isOpen, setIsOpen]           = useState(false);
  const [draftSelected, setDraftSelected] = useState(selected);

  useEffect(() => { setDraftSelected(selected); }, [selected]);
  useEffect(() => { setIsOpen(true); }, []);

  const selectedRuns = useMemo(
    () => runs.filter(run => selected.includes(run.id)),
    [runs, selected],
  );

  const closeModal = () => { setDraftSelected(selected); setIsOpen(false); };

  const applySelection = () => {
    syncCustomSelection(draftSelected, selected, onCustomToggle, onCustomSet);
    setIsOpen(false);
    if (draftSelected.length > 0) scrollToResults();
  };

  const removeRun = (id: string) => {
    syncCustomSelection(
      selected.filter(s => s !== id),
      selected,
      onCustomToggle,
      onCustomSet,
    );
  };

  if (runs.length === 0) {
    return (
      <div className="rounded-[1.2rem] bg-subtle px-4 py-8 text-center">
        <p className="text-sm text-muted italic">No runs available</p>
      </div>
    );
  }

  return (
    <>
      <CustomRangeTrigger
        selectedRuns={selectedRuns}
        onOpen={() => setIsOpen(true)}
        onRemove={removeRun}
      />
      <CustomRangeModal
        open={isOpen}
        runs={runs}
        draftSelected={draftSelected}
        setDraftSelected={setDraftSelected}
        onClose={closeModal}
        onApply={applySelection}
      />
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Public component
// ─────────────────────────────────────────────────────────────

export function RunPicker({ runs, selected, timeMode, onCustomToggle, onCustomSet }: RunPickerProps) {
  if (timeMode === 'latest_vs_previous') return <PairwisePicker runs={runs} />;
  if (timeMode === 'last5' || timeMode === 'last10') return <AutoHistoryPicker timeMode={timeMode} runs={runs} />;
  return <CustomPicker runs={runs} selected={selected} onCustomToggle={onCustomToggle} onCustomSet={onCustomSet} />;
}

// ─────────────────────────────────────────────────────────────
// CompactRunChip — used for history and pairwise modes
// ─────────────────────────────────────────────────────────────

function CompactRunChip({ run }: { run: Run }) {
  return (
    <Tooltip
      content={`${run.label} · ${fmtDate(run.startedAt)} · ${run.totalTests} tests · ${run.failedCount} failed`}
      className="flex-shrink-0"
    >
      <div className="flex flex-col items-center px-3 py-2 border border-border-default rounded-lg bg-surface hover:bg-hover transition-colors cursor-default group">
        <span className="text-xs font-semibold text-primary">{run.label}</span>
        <div className="flex items-center gap-1 mt-1">
          <span className={`text-xs font-medium ${passRateColor(run.passRate)}`}>
            {Math.round(run.passRate * 100)}%
          </span>
        </div>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity text-[9px] text-muted mt-0.5">
          {fmtDate(run.startedAt)}
        </div>
      </div>
    </Tooltip>
  );
}
