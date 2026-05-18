import type { ComparisonMetrics } from '../../types';

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function fmt(val: number, format: 'percent' | 'count'): string {
  if (format === 'percent') return `${Math.round(val * 100)}%`;
  return String(val);
}

function fmtDelta(diff: number, format: 'percent' | 'count'): string {
  const sign = diff > 0 ? '+' : '';
  if (format === 'percent') return `${sign}${Math.round(diff * 100)}%`;
  return `${sign}${Math.round(diff)}`;
}

// ─────────────────────────────────────────────────────────────
// MetricCard
// ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  label:  string;
  valueA: number;   // A = baseline (left / older)
  valueB: number;   // B = latest  (right / newer)
  labelA: string;
  labelB: string;
  format: 'percent' | 'count';
  higher: 'better' | 'worse';
}

function MetricCard({ label, valueA, valueB, format, higher }: MetricCardProps) {
  const diff  = valueB - valueA;                               // positive = B is higher
  const equal = diff === 0;

  // Is the change an improvement?
  // higher=worse → lower B is better → diff < 0 is improvement
  // higher=better → higher B is better → diff > 0 is improvement
  const improved = !equal && (higher === 'worse' ? diff < 0 : diff > 0);

  // Color classes
  const deltaClass = equal      ? 'text-muted'   :
                     improved   ? 'text-success'  :
                                  'text-danger';

  const valueBClass = equal      ? 'text-primary'  :
                      improved   ? 'text-success'   :
                                   'text-danger';

  // Direction indicator
  const arrow = equal    ? '—'  :
                improved ? '↑'  :
                           '↓';

  const dirLabel = equal    ? 'no change' :
                   improved ? 'better'    :
                              'worse';

  return (
    <article className="qalens-card qalens-fade-up flex-1 min-w-[180px] p-5">

      {/* Title */}
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted mb-4">
        {label}
      </p>

      {/* Side-by-side values */}
      <div className="flex items-end gap-5">
        <div className="flex flex-col items-start">
          <span className={`text-2xl font-semibold tabular-nums leading-none ${valueBClass}`}>
            {fmt(valueB, format)}
          </span>
          <span className="text-[9px] font-semibold uppercase tracking-[0.15em] text-muted mt-1">Latest</span>
        </div>
        <div className="flex flex-col items-start">
          <span className="text-2xl font-semibold text-secondary tabular-nums leading-none">
            {fmt(valueA, format)}
          </span>
          <span className="text-[9px] font-semibold uppercase tracking-[0.15em] text-muted mt-1">Previous</span>
        </div>
      </div>

      {/* Delta + direction */}
      <div className={`flex items-center gap-1.5 mt-4 ${deltaClass}`}>
        <span className="text-base leading-none font-medium">{arrow}</span>
        {equal ? (
          <span className="text-sm font-medium">No change</span>
        ) : (
          <>
            <span className="text-sm font-semibold tabular-nums">
              {fmtDelta(diff, format)}
            </span>
            <span className="text-xs font-medium opacity-75">{dirLabel}</span>
          </>
        )}
      </div>

    </article>
  );
}

// ─────────────────────────────────────────────────────────────
// ComparisonSummaryCards
// ─────────────────────────────────────────────────────────────

interface ComparisonSummaryCardsProps {
  metricsA: ComparisonMetrics;
  metricsB: ComparisonMetrics;
}

export function ComparisonSummaryCards({ metricsA, metricsB }: ComparisonSummaryCardsProps) {
  const cards: MetricCardProps[] = [
    {
      label:  'Failure Rate',
      valueA: metricsA.failureRate,
      valueB: metricsB.failureRate,
      labelA: metricsA.label,
      labelB: metricsB.label,
      format: 'percent',
      higher: 'worse',
    },
    {
      label:  'New Failures',
      valueA: metricsA.newFailures,
      valueB: metricsB.newFailures,
      labelA: metricsA.label,
      labelB: metricsB.label,
      format: 'count',
      higher: 'worse',
    },
    {
      label:  'Recovered Tests',
      valueA: metricsA.fixedTests,
      valueB: metricsB.fixedTests,
      labelA: metricsA.label,
      labelB: metricsB.label,
      format: 'count',
      higher: 'better',
    },
    {
      label:  'Total Tests',
      valueA: metricsA.totalTests,
      valueB: metricsB.totalTests,
      labelA: metricsA.label,
      labelB: metricsB.label,
      format: 'count',
      higher: 'better',
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
      {cards.map(card => (
        <MetricCard key={card.label} {...card} />
      ))}
    </div>
  );
}
