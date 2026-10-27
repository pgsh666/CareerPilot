import { ref } from "vue";
import { api } from "./api";
import { state } from "./state";
export interface Budget {
  limitMicroCny: number;
  chargedUpperMicroCny: number;
  heldMicroCny: number;
  remainingMicroCny: number;
  sentCalls: number;
  estimatedMicroCny: number;
  verifiedMicroCny: number;
  unknownHeldMicroCny: number;
}
export interface AdminSnapshot {
  userCount: number;
  todayTraining: number;
  pendingJobs: number;
  successRate: number | null;
  unknownCalls: number;
  budgets: { month: Budget; test: Budget };
  services: Record<string, string>;
  allocations: {
    purpose: string;
    label: string;
    calls: number;
    chargedUpperMicroCny: number | null;
    promptTokens: number | null;
    completionTokens: number | null;
  }[];
}
export const adminSnapshot = ref<AdminSnapshot | null>(null);
export async function loadAdminSnapshot() {
  const owner = state.account.id;
  const result = await api<AdminSnapshot>("/admin/overview");
  if (owner === state.account.id && state.account.role === "admin")
    adminSnapshot.value = result;
  return result;
}
export const fee = (value: number | null | undefined) =>
  value == null
    ? "待核实"
    : (value / 1_000_000).toFixed(6).replace(/0+$/, "").replace(/\.$/, "") ||
      "0";
