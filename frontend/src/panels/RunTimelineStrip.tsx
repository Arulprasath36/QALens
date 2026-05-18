import { Tooltip } from '../components/Tooltip';

export interface RunTimelineRun {
  run_id: string;
  run_sequence: number;
  started_at: number | null;
  total_tests: number | null;
  passed_count: number | null;
  failed_count: number | null;
  skipped_count?: number | null;
  flaky_count?: number | null;
}

interface RunTimelineStripProps {
  runs: RunTimelineRun[];
  selectedRunId: string;
  scopeSize: number;
  mode: 'single' | 'window';
}

function fmtTs(ts: number | null) {
  if (ts == null) return 'No timestamp';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function passRate(run: RunTimelineRun) {
  if (!run.total_tests) return null;
  return Math.round(((run.passed_count ?? 0) / run.total_tests) * 100);
}

// Single solid fill for non-selected nodes — no inner dot, no layering
function nodeFill(run: RunTimelineRun): string {
  const rate = passRate(run);
  const failed = run.failed_count ?? 0;
  if (rate == null) return 'var(--border-strong)';
  if (failed > 0 && rate < 75) return 'rgba(239,68,68,0.45)';
  if (failed > 0 || rate < 90) return 'rgba(245,158,11,0.5)';
  return 'rgba(16,185,129,0.5)';
}

function TooltipBody({ run }: { run: RunTimelineRun }) {
  const rate = passRate(run);
  return (
    <div className="min-w-[160px] space-y-2">
      <div>
        <p className="font-semibold text-primary text-[12px]">Run #{run.run_sequence}</p>
        <p className="text-[11px] text-muted">{fmtTs(run.started_at)}</p>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
        <span className="text-muted">Pass rate</span>
        <span className="text-right font-semibold text-primary">{rate == null ? '—' : `${rate}%`}</span>
        <span className="text-muted">Failed</span>
        <span className="text-right font-semibold text-danger">{run.failed_count ?? 0}</span>
      </div>
    </div>
  );
}

export function RunTimelineStrip({
  runs,
  selectedRunId,
  scopeSize,
  mode,
}: RunTimelineStripProps) {
  const selectedIndex = runs.findIndex(run => run.run_id === selectedRunId);
  const selectedRun = selectedIndex >= 0 ? runs[selectedIndex] : null;
  const visibleRuns = mode === 'single'
    ? selectedRun ? [selectedRun] : []
    : selectedIndex >= 0
      ? runs.slice(Math.max(0, selectedIndex - scopeSize + 1), selectedIndex + 1)
      : [];

  if (visibleRuns.length === 0) return null;

  const count = visibleRuns.length;
  const scopeLabel = mode === 'single'
    ? `Run #${visibleRuns[0].run_sequence}`
    : `#${visibleRuns[0].run_sequence}–#${visibleRuns[visibleRuns.length - 1].run_sequence}`;

  // Spine runs between node centers — offset = half a column from each edge
  return (
    <section
      className="rounded-[1.25rem] bg-surface"
      style={{ boxShadow: '0 1px 2px rgba(15,23,42,0.04), 0 4px 16px rgba(15,23,42,0.03)' }}
    >
      {/* Compact header */}
      <div className="flex items-center justify-between px-5 pt-3 pb-2">
        <span className="type-eyebrow">Run Timeline</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>
          {mode === 'single' ? 'Run in scope:' : 'Runs in scope:'}{' '}
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{scopeLabel}</span>
        </span>
      </div>


      {/* Timeline body */}
      <div className="px-6 pt-4 pb-4">
        <div
          key={`${mode}-${scopeSize}-${visibleRuns.map(r => r.run_id).join('-')}`}
          className="qalens-run-timeline-frame w-full"
          style={{ minWidth: `${count * 56}px` }}
        >
          {/* Outer flex row: nodes separated by connector lines */}
          <div style={{ display: 'flex', alignItems: 'flex-start', width: '100%' }}>
            {visibleRuns.map((run, i) => {
              const selected = run.run_id === selectedRunId;
              const fill = nodeFill(run);
              const isLast = i === count - 1;

              return (
                <div
                  key={run.run_id}
                  className="qalens-run-timeline-item"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    flex: isLast ? '0 0 auto' : '1 1 0',
                    minWidth: 0,
                  }}
                >
                  {/* Row: node + connector — fixed 30px height keeps all nodes on the same axis */}
                  <div style={{ display: 'flex', alignItems: 'center', width: '100%', height: 30 }}>
                    {/* Node */}
                    <Tooltip content={<TooltipBody run={run} />} className="inline-flex flex-shrink-0">
                      <button
                        type="button"
                        aria-label={`Run ${run.run_sequence}${selected ? ', selected' : ''}`}
                        className="qalens-run-timeline-node focus:outline-none flex-shrink-0"
                        style={selected ? {
                          width: 26,
                          height: 26,
                          borderRadius: '50%',
                          background: 'rgb(79,70,229)',
                          border: 'none',
                          boxShadow: '0 0 0 5px rgba(79,70,229,0.12), 0 2px 10px rgba(79,70,229,0.3)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0,
                          cursor: 'default',
                        } : {
                          width: 10,
                          height: 10,
                          borderRadius: '50%',
                          background: fill,
                          border: 'none',
                          flexShrink: 0,
                          cursor: 'default',
                        }}
                      >
                        {selected && (
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'white', display: 'block' }} />
                        )}
                      </button>
                    </Tooltip>

                    {/* Connector line to next node */}
                    {!isLast && (
                      <div
                        aria-hidden="true"
                        style={{
                          flex: 1,
                          height: 1.5,
                          background: 'var(--border-default)',
                          borderRadius: 2,
                        }}
                      />
                    )}
                  </div>

                  {/* Labels centered under the node circle only */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: 5 }}>
                    <span
                      className="tabular-nums"
                      style={{
                        fontSize: 11,
                        fontWeight: selected ? 700 : 500,
                        color: selected ? 'rgb(79,70,229)' : 'var(--text-muted)',
                        lineHeight: 1,
                      }}
                    >
                      #{run.run_sequence}
                    </span>

                    {selected && (
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 500,
                          color: 'rgba(79,70,229,0.55)',
                          marginTop: 2,
                          whiteSpace: 'nowrap',
                          letterSpacing: '0.01em',
                        }}
                      >
                        {mode === 'single' ? 'selected' : 'window end'}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
