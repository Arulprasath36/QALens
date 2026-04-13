import { useState, useEffect } from 'react';
import type { CompareState, ComparisonResult, Owner, Run, Suite } from '../types';
import {
  MOCK_OWNERS,
  MOCK_RUNS,
  MOCK_SUITES,
  MOCK_COMPARISON_FATIMA_VS_ARJUN,
  MOCK_COMPARISON_RUN53_VS_RUN52,
} from '../mockData';

// ─────────────────────────────────────────────────────────────
// Catalogue hook — feeds pickers
// ─────────────────────────────────────────────────────────────

export function useCatalogue() {
  const [owners]  = useState<Owner[]>(MOCK_OWNERS);
  const [runs]    = useState<Run[]>(MOCK_RUNS);
  const [suites]  = useState<Suite[]>(MOCK_SUITES);
  return { owners, runs, suites };
}

// ─────────────────────────────────────────────────────────────
// Comparison result hook — executes the compare query
// ─────────────────────────────────────────────────────────────

interface UseCompareDataReturn {
  result:  ComparisonResult | null;
  loading: boolean;
  error:   string | null;
}

export function useCompareData(state: CompareState): UseCompareDataReturn {
  const [result,  setResult]  = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const canFetch = state.selections.length >= 2;

  useEffect(() => {
    if (!canFetch) {
      setResult(null);
      setError(null);
      return;
    }

    let cancelled = false;

    async function fetchComparison() {
      setLoading(true);
      setError(null);
      try {
        // ── Real API call (replace mock when backend supports dimensions) ──
        // const params = new URLSearchParams({
        //   dimension: state.dimension,
        //   timeMode:  state.timeMode,
        //   a:         state.selections[0],
        //   b:         state.selections[1],
        // });
        // const res = await fetch(`/api/compare/engine?${params}`);
        // if (!res.ok) throw new Error(await res.text());
        // const data: ComparisonResult = await res.json();

        // ── Mock data (remove when API is ready) ──
        await new Promise(r => setTimeout(r, 600)); // simulate latency
        const data = resolveMockResult(state);

        if (!cancelled) {
          setResult(data);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Comparison failed');
          setLoading(false);
        }
      }
    }

    void fetchComparison();
    return () => { cancelled = true; };
  }, [state.dimension, state.timeMode, state.selections.join(','), canFetch]); // eslint-disable-line

  return { result, loading, error };
}

// ── Mock resolver ─────────────────────────────────────────────

function resolveMockResult(state: CompareState): ComparisonResult {
  if (state.dimension === 'owners') {
    return MOCK_COMPARISON_FATIMA_VS_ARJUN;
  }
  return MOCK_COMPARISON_RUN53_VS_RUN52;
}
