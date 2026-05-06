// Public API of the Compare Engine module
export { CompareEngine } from './CompareEngine';
export { useCompareState } from './hooks/useCompareState';
export { useCompareData, useCatalogue } from './hooks/useCompareData';
export { CompareControlBar } from './components/CompareControlBar';
export { OwnerPicker } from './components/pickers/OwnerPicker';
export { RunPicker } from './components/pickers/RunPicker';
export { SuitePicker } from './components/pickers/SuitePicker';
export { ComparisonSummaryCards } from './components/output/ComparisonSummaryCards';
export { ComparisonTable } from './components/output/ComparisonTable';
export type {
  CompareState,
  CompareDimension,
  TimeMode,
  Owner,
  Run,
  Suite,
  ComparisonResult,
  ComparisonMetrics,
  ComparisonRow,
} from './types';
