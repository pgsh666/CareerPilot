import { computed } from "vue";
import { fixtures, state } from "./state";
import { isPreviewMode } from "./runtime";
export interface HistoryRow {
  id: string;
  kind: string;
  role: string;
  target: string;
  version: string;
  date: string;
  time: string;
  status: string;
  score: number | null;
  coverage: number;
  technical: number | null;
  expression: number | null;
  comparable: boolean;
  number: number;
  title: string;
  original: boolean;
  variant: boolean;
  source: number | string;
  local: boolean;
}
export const historyRecords = computed<HistoryRow[]>(() => [
  ...state.runs.map((r) => ({ ...r, local: true })),
  ...(isPreviewMode ? fixtures.history.records : []).map((r) => ({
    score: null,
    coverage: 0,
    technical: null,
    expression: null,
    comparable: false,
    number: 0,
    title: "",
    original: false,
    variant: false,
    source: "",
    ...r,
    local: false,
  })),
]);
export const roleNames: Record<string, string> = fixtures.history.roleNames;
