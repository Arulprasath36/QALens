import { useReducer, useCallback } from 'react';
import type { CompareState, CompareDimension, TimeMode } from '../types';
import { DIMENSION_CONFIG } from '../types';

// ─────────────────────────────────────────────────────────────
// Action types
// ─────────────────────────────────────────────────────────────

type Action =
  | { type: 'SET_DIMENSION';       dimension: CompareDimension }
  | { type: 'SET_TIME';            timeMode: TimeMode }
  | { type: 'TOGGLE_SELECTION';    id: string }
  | { type: 'SET_SELECTIONS';      selections: string[] }
  | { type: 'SET_CUSTOM_RUNS';     runIds: string[] }
  | { type: 'TOGGLE_CUSTOM_RUN';   id: string }
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
        timeMode: cfg.defaultTimeMode,
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
        // Hard limit — do not auto-deselect. UI layer shows the constraint.
        return state;
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

    // Individual toggle for runs custom mode — add/remove without rotating.
    case 'TOGGLE_CUSTOM_RUN': {
      const { id } = action;
      const already = state.customRunIds.includes(id);
      const next = already
        ? state.customRunIds.filter(r => r !== id)
        : [...state.customRunIds, id];
      return { ...state, customRunIds: next, timeMode: 'custom' };
    }

    case 'RESET':
      return {
        ...state,
        selections: [],
        customRunIds: [],
      };

    default:
      return state;
  }
}

// ─────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────

export interface UseCompareStateReturn {
  state: CompareState;
  setDimension:     (d: CompareDimension) => void;
  setTimeMode:      (t: TimeMode)         => void;
  toggleSelection:  (id: string)          => void;
  setSelections:    (ids: string[])       => void;
  setCustomRuns:    (ids: string[])       => void;
  toggleCustomRun:  (id: string)          => void;
  reset:            ()                    => void;
  /**
   * True when there is enough state to fire a comparison fetch and show results.
   *
   * - runs + last5 / last10 / latest_vs_previous  → always true (auto-fetch)
   * - runs + custom                               → at least 1 custom run selected
   * - owners / suites                             → at least 2 selections
   */
  canCompare: boolean;
}

export function useCompareState(): UseCompareStateReturn {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  const setDimension    = useCallback((d: CompareDimension) => dispatch({ type: 'SET_DIMENSION',     dimension: d }),   []);
  const setTimeMode     = useCallback((t: TimeMode)         => dispatch({ type: 'SET_TIME',          timeMode: t }),    []);
  const toggleSelection = useCallback((id: string)          => dispatch({ type: 'TOGGLE_SELECTION',  id }),             []);
  const setSelections   = useCallback((ids: string[])       => dispatch({ type: 'SET_SELECTIONS',    selections: ids }),[]);
  const setCustomRuns   = useCallback((ids: string[])       => dispatch({ type: 'SET_CUSTOM_RUNS',   runIds: ids }),    []);
  const toggleCustomRun = useCallback((id: string)          => dispatch({ type: 'TOGGLE_CUSTOM_RUN', id }),             []);
  const reset           = useCallback(()                    => dispatch({ type: 'RESET' }),                             []);

  const isRunsDimension = state.dimension === 'runs';
  const canCompare = isRunsDimension
    ? (state.timeMode === 'custom' ? state.customRunIds.length >= 1 : true)
    : (state.selections.length >= 2 && (state.timeMode !== 'custom' || state.customRunIds.length >= 1));

  return {
    state,
    setDimension,
    setTimeMode,
    toggleSelection,
    setSelections,
    setCustomRuns,
    toggleCustomRun,
    reset,
    canCompare,
  };
}
