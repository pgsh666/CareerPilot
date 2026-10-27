import { computed, onBeforeUnmount, ref } from "vue";

export function useCodeCountdown(identity: () => string) {
  const deadlines = new Map<string, number>();
  const now = ref(Date.now());
  const timer = setInterval(() => (now.value = Date.now()), 500);
  onBeforeUnmount(() => clearInterval(timer));
  return {
    remaining: computed(() =>
      Math.max(
        0,
        Math.ceil(((deadlines.get(identity()) || 0) - now.value) / 1000),
      ),
    ),
    markSent(key = identity()) {
      deadlines.set(key, Date.now() + 60_000);
      now.value = Date.now();
    },
  };
}
