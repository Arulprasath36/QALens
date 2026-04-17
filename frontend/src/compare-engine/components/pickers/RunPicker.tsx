import { useEffect, useMemo, useState } from 'react';
import { Modal } from '../../../components/Modal';
import type { Run, TimeMode } from '../../types';

interface RunPickerProps {
  runs:           Run[];
  selected:       string[];
  timeMode:       TimeMode;
  /** Used for custom mode: toggles a run into/out of customRunIds */
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
  return [
    run.label,
    fmtDate(run.startedAt),
    `${Math.round(run.passRate * 100)}%`,
    `${run.failedCount}`,
    `${run.totalTests}`,
  ]
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

      {/* Context line */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-medium">Comparing latest vs previous</span>
        {dateRange && (
          <>
            <span>•</span>
            <span>{dateRange}</span>
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// last5 / last10: horizontal scrolling run cards
// ─────────────────────────────────────────────────────────────

function AutoHistoryPicker({ timeMode, runs }: { timeMode: TimeMode; runs: Run[] }) {
  const limit = timeMode === 'last5' ? 5 : 10;
  const visible = runs.slice(0, limit);

  if (visible.length === 0) {
    return <span className="text-xs text-muted italic">Loading runs…</span>;
  }

  const dateRange = visible.length >= 2
    ? `${fmtDate(visible[visible.length - 1].startedAt)} → ${fmtDate(visible[0].startedAt)}`
    : fmtDate(visible[0]?.startedAt || '');

  return (
    <div className="space-y-2">
      {/* Horizontal run strip */}
      <div className="relative">
        <div
          className="flex gap-2 overflow-x-auto pb-1 scroll-smooth"
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: 'rgb(203 213 225) transparent'
          }}
        >
          {visible.map(run => (
            <CompactRunChip key={run.id} run={run} />
          ))}
        </div>

        {/* Fade gradient for scroll indication */}
        {visible.length > 4 && (
          <div className="absolute right-0 top-0 bottom-1 w-8 bg-gradient-to-l from-surface to-transparent pointer-events-none" />
        )}
      </div>

      {/* Context line */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-medium">Showing last {visible.length} run{visible.length !== 1 ? 's' : ''}</span>
        {dateRange && (
          <>
            <span>•</span>
            <span>{dateRange}</span>
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// custom: modal-based multi-select for scalable run history
// ─────────────────────────────────────────────────────────────

function scrollToResults() {
  document.getElementById('compare-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function syncCustomSelection(
  nextIds: string[],
  currentIds: string[],
  onCustomToggle: (id: string) => void,
  onCustomSet?: (ids: string[]) => void,
) {
  if (onCustomSet) {
    onCustomSet(nextIds);
    return;
  }

  currentIds.forEach(id => onCustomToggle(id));
  nextIds.forEach(id => onCustomToggle(id));
}

function describeSelection(selectedRuns: Run[]) {
  if (selectedRuns.length === 0) {
    return {
      title: 'Select runs to compare',
      detail: 'Choose one run for details, two for pairwise, or more for a history matrix.',
    };
  }

  if (selectedRuns.length === 1) {
    return { title: selectedRuns[0].label, detail: 'Single run detail view' };
  }

  if (selectedRuns.length === 2) {
    return {
      title: `${selectedRuns[0].label} vs ${selectedRuns[1].label}`,
      detail: 'Pairwise comparison ready',
    };
  }

  return {
    title: `${selectedRuns.length} runs selected`,
    detail: 'History matrix ready',
  };
}

function SelectedRunChip({ run, index, pairwise }: { run: Run; index: number; pairwise: boolean }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border-default bg-surface px-3 py-1.5 text-xs">
      {pairwise && <span className="text-faint">{index === 0 ? 'A' : 'B'}</span>}
      <span className="font-semibold text-primary">{run.label}</span>
      <span className={`font-medium ${passRateColor(run.passRate)}`}>
        {Math.round(run.passRate * 100)}%
      </span>
    </div>
  );
}

function CustomRangeTrigger({
  selectedRuns,
  onOpen,
}: {
  selectedRuns: Run[];
  onOpen: () => void;
}) {
  const summary = describeSelection(selectedRuns);

  return (
    <div className="flex flex-col gap-3 rounded-[1.2rem] border border-border-default bg-subtle px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
            Custom Range
          </p>
          <p className="mt-1 text-sm font-semibold text-primary">{summary.title}</p>
          <p className="mt-1 text-xs text-muted">{summary.detail}</p>
        </div>

        <div className="flex items-center gap-2">
          {selectedRuns.length > 0 && (
            <span className="qara-pill qara-pill-active">{selectedRuns.length} selected</span>
          )}
          <button type="button" onClick={onOpen} className="qara-chip type-chip">
            {selectedRuns.length > 0 ? 'Edit selection' : 'Select runs'}
          </button>
        </div>
      </div>

      {selectedRuns.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {selectedRuns.slice(0, 4).map((run, index) => (
            <SelectedRunChip
              key={run.id}
              run={run}
              index={index}
              pairwise={selectedRuns.length === 2}
            />
          ))}
          {selectedRuns.length > 4 && (
            <span className="qara-pill">+{selectedRuns.length - 4} more</span>
          )}
        </div>
      )}
    </div>
  );
}

function ModalRunRow({
  run,
  selected,
  onToggle,
}: {
  run: Run;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={[
        'grid w-full grid-cols-[24px_minmax(0,1.4fr)_auto] items-center gap-3 rounded-[1rem] border px-3 py-3 text-left transition-all duration-150',
        selected
          ? 'border-info/25 bg-selected'
          : 'border-transparent hover:border-border-default hover:bg-hover',
      ].join(' ')}
    >
      <span
        className={[
          'inline-flex h-5 w-5 items-center justify-center rounded-md border text-[11px] font-semibold',
          selected
            ? 'border-info/30 bg-info/10 text-info'
            : 'border-border-default bg-surface text-transparent',
        ].join(' ')}
        aria-hidden="true"
      >
        ✓
      </span>

      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-primary">{run.label}</span>
          <span className="text-xs text-muted">{fmtDate(run.startedAt)}</span>
          {run.branch && <span className="qara-pill">{run.branch}</span>}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span className={`font-semibold ${passRateColor(run.passRate)}`}>
            {Math.round(run.passRate * 100)}% pass
          </span>
          <span>{run.totalTests} tests</span>
          <span className={run.failedCount > 0 ? 'font-semibold text-danger' : ''}>
            {run.failedCount} fail{run.failedCount === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      <div className="text-right text-xs text-muted">
        <div>Run {run.sequence}</div>
      </div>
    </button>
  );
}

function CustomRangeModal({
  open,
  runs,
  draftSelected,
  setDraftSelected,
  onClose,
  onApply,
}: {
  open: boolean;
  runs: Run[];
  draftSelected: string[];
  setDraftSelected: (ids: string[]) => void;
  onClose: () => void;
  onApply: () => void;
}) {
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!open) setSearch('');
  }, [open]);

  const filteredRuns = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return runs;
    return runs.filter(run => buildRunSearchText(run).includes(query));
  }, [runs, search]);

  const toggleDraft = (id: string) => {
    setDraftSelected(
      draftSelected.includes(id)
        ? draftSelected.filter(runId => runId !== id)
        : [...draftSelected, id],
    );
  };

  return (
    <Modal
      open={open}
      title="Select Runs to Compare"
      meta={(
        <div className="flex flex-wrap items-center gap-2">
          <span className="qara-pill qara-pill-active">{draftSelected.length} selected</span>
          <span>Search history and build the comparison set without leaving the results view.</span>
        </div>
      )}
      onClose={onClose}
      widthClassName="max-w-5xl"
      footer={(
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setDraftSelected(runs.slice(0, 2).map(run => run.id))}
              className="qara-chip type-chip"
            >
              Select latest 2
            </button>
            <button
              type="button"
              onClick={() => setDraftSelected(runs.slice(0, 5).map(run => run.id))}
              className="qara-chip type-chip"
            >
              Select last 5
            </button>
            <button
              type="button"
              onClick={() => setDraftSelected([])}
              className="qara-chip type-chip"
            >
              Clear all
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="qara-chip type-chip">
              Cancel
            </button>
            <button
              type="button"
              onClick={onApply}
              className="qara-chip qara-chip-active type-chip"
            >
              {draftSelected.length > 0 ? `Compare ${draftSelected.length} selected` : 'Apply'}
            </button>
          </div>
        </>
      )}
    >
      <div className="space-y-4">
        <div className="qara-control w-full px-3">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="shrink-0 text-muted">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search runs..."
            className="qara-input h-11 text-sm"
          />
        </div>

        <div className="rounded-[1.2rem] border border-border-default bg-surface">
          <div className="grid grid-cols-[24px_minmax(0,1.4fr)_auto] gap-3 border-b border-border-subtle px-3 py-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">
            <span />
            <span>Run</span>
            <span>Context</span>
          </div>

          <div className="max-h-[28rem] overflow-y-auto p-2">
            {filteredRuns.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-muted">
                No runs match this search.
              </div>
            ) : (
              <div className="space-y-1.5">
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

function CustomPicker({
  runs,
  selected,
  onCustomToggle,
  onCustomSet,
}: {
  runs: Run[];
  selected: string[];
  onCustomToggle: (id: string) => void;
  onCustomSet?: (ids: string[]) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [draftSelected, setDraftSelected] = useState(selected);

  useEffect(() => {
    setDraftSelected(selected);
  }, [selected]);

  useEffect(() => {
    setIsOpen(true);
  }, []);

  const selectedRuns = useMemo(
    () => runs.filter(run => selected.includes(run.id)),
    [runs, selected],
  );

  const closeModal = () => {
    setDraftSelected(selected);
    setIsOpen(false);
  };

  const applySelection = () => {
    syncCustomSelection(draftSelected, selected, onCustomToggle, onCustomSet);
    setIsOpen(false);
    if (draftSelected.length > 0) scrollToResults();
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
      <CustomRangeTrigger selectedRuns={selectedRuns} onOpen={() => setIsOpen(true)} />
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
  if (timeMode === 'latest_vs_previous') {
    return <PairwisePicker runs={runs} />;
  }

  if (timeMode === 'last5' || timeMode === 'last10') {
    return <AutoHistoryPicker timeMode={timeMode} runs={runs} />;
  }

  // custom
  return <CustomPicker runs={runs} selected={selected} onCustomToggle={onCustomToggle} onCustomSet={onCustomSet} />;
}

// ─────────────────────────────────────────────────────────────
// CompactRunChip — used for history and pairwise modes
// ─────────────────────────────────────────────────────────────

function CompactRunChip({ run }: { run: Run }) {
  return (
    <div
      className="flex-shrink-0 flex flex-col items-center px-3 py-2 border border-border-default rounded-lg bg-surface hover:bg-hover transition-colors cursor-default group"
      title={`${run.label} · ${fmtDate(run.startedAt)} · ${run.totalTests} tests · ${run.failedCount} failed`}
    >
      {/* Run number */}
      <span className="text-xs font-semibold text-primary">{run.label}</span>

      {/* Pass rate with color */}
      <div className="flex items-center gap-1 mt-1">
        <span className={`text-xs font-medium ${passRateColor(run.passRate)}`}>
          {Math.round(run.passRate * 100)}%
        </span>
      </div>

      {/* Hover tooltip - shown on hover */}
      <div className="opacity-0 group-hover:opacity-100 transition-opacity text-[9px] text-muted mt-0.5">
        {fmtDate(run.startedAt)}
      </div>
    </div>
  );
}
