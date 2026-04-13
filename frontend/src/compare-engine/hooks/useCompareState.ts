import { useReducer, useCallback } from 'react';
import type { CompareState, CompareDimension, TimeMode } from '../types';
import { DIMENSION_CONFIG } from '../types';

// ─────────────────────────────────────────────────────────────
// Action types
// ─────────────────────────────────────────────────────────────

type Action =
  | { type: 'SET_DIMENSION';    dimension: CompareDimension }
  | { type: 'SET_TIME';         timeMode: TimeMode }
  | { type: 'TOGGLE_SELECTION'; id: string }
  | { type: 'SET_SELECTIONS';   selections: string[] }
  | { type: 'SET_CUSTOM_RUNS';  runIds: string[] }
  | { type: 'RESET' };

// ─────────────────────────────────────────────────────────────
// Reducer
// ─────────────────────────────────────────────────────────────

const INITIAL_STATE: CompareState = {
  dimension: 'runs',
  timeMode: 'latest_vs_previous',
  selections: [],
  customRunIds: [],
};

function reducer(state: CompareState, action: Action): CompareState {
  switch (action.type) {

    case 'SET_DIMENSION': {
      const cfg = DIMENSION_CONFIG[action.dimension];
      return {
        ...state,
        dimension: action.dimension,
        // Per-dimension intelligent default time scope
        timeMode: cfg.defaultTimeMode,
        // Always reset selections when dimension changes — they're incompatible
        selections: [],
        customRunIds: [],
      };
    }

    case 'SET_TIME':
      return {
        ...state,
        timeMode: action.timeMode,
        // Clear custom runs when switching away from custom
        customRunIds: action.timeMode !== 'custom' ? [] : state.customRunIds,
      };

    case 'TOGGLE_SELECTION': {
      const { id } = action;
      const max = DIMENSION_CONFIG[state.dimension].maxSelections;
      const already = state.selections.includes(id);

      if (already) {
        return { ...state, selections: state.selections.filter(s => s !== id) };
      }
      if (state.selections.length >= max) {
        // Rotate: drop oldest, add newest
        return { ...state, selections: [...state.selections.slice(1), id] };
      }
      return { ...state, selections: [...state.selections, id] };
    }

    case 'SET_SELECTIONS':
      return {
        ...state,
        selections: action.selections.slice(0, DIMENSION_CONFIG[state.dimension].maxSelections),
      };

    case 'SET_CUSTOM_RUNS':
      return { ...state, customRunIds: action.runIds, timeMode: 'custom' };

    case 'RESET':
      return INITIAL_STATE;

    default:
      return state;
  }
}

// ─────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────

export interface UseCompareStateReturn {
  state: CompareState;
  setDimension:   (d: CompareDimension) => void;
  setTimeMode:    (t: TimeMode)         => void;
  toggleSelection:(id: string)          => void;
  setSelections:  (ids: string[])       => void;
  setCustomRuns:  (ids: string[])       => void;
  reset:          ()                    => void;
  /** True when the minimum 2 selections are chosen */
  canCompare: boolean;
  /** Human-readable summary of the current compare intent */
  intentLabel: string;
}

export function useCompareState(): UseCompareStateReturn {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  const setDimension    = useCallback((d: CompareDimension) => dispatch({ type: 'SET_DIMENSION',    dimension: d }),   []);
  const setTimeMode     = useCallback((t: TimeMode)         => dispatch({ type: 'SET_TIME',         timeMode: t }),    []);
  const toggleSelection = useCallback((id: string)          => dispatch({ type: 'TOGGLE_SELECTION', id }),             []);
  const setSelections   = useCallback((ids: string[])       => dispatch({ type: 'SET_SELECTIONS',   selections: ids }),[]);
  const setCustomRuns   = useCallback((ids: string[])       => dispatch({ type: 'SET_CUSTOM_RUNS',  runIds: ids }),    []);
  const reset           = useCallback(()                    => dispatch({ type: 'RESET' }),                            []);

  const canCompare = state.selections.length >= 2;

  const intentLabel = canCompare
    ? `${DIMENSION_CONFIG[state.dimension].label}: ${state.selections.join(' vs ')}`
    : `Select ${DIMENSION_CONFIG[state.dimension].maxSelections} ${DIMENSION_CONFIG[state.dimension].label.toLowerCase()} to compare`;

  return {
    state,
    setDimension,
    setTimeMode,
    toggleSelection,
    setSelections,
    setCustomRuns,
    reset,
    canCompare,
    intentLabel,
  };
}
