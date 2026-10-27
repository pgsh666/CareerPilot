<script setup lang="ts">
import { ref, watch } from "vue";
import { usePageMotion } from "./pageMotion";

const props = defineProps<{ active: string; order: string[] }>();
const viewport = ref<HTMLElement>();
const snapshots = ref<HTMLElement>();
const direction = ref(1);
watch(
  () => props.active,
  (next, previous) => {
    direction.value =
      props.order.indexOf(next) < props.order.indexOf(previous) ? -1 : 1;
  },
  { flush: "sync" },
);
const motion = usePageMotion(viewport, snapshots, {
  direction,
  distance: () => viewport.value?.clientWidth || 0,
  snapshotClass: "tab-slide-snapshot",
  snapshotLeft: "0",
});
</script>

<template>
  <div ref="viewport" class="tab-slide-viewport">
    <Transition :css="false" v-on="motion">
      <div :key="active" class="tab-slide-pane"><slot /></div>
    </Transition>
    <div ref="snapshots" class="tab-slide-snapshots" aria-hidden="true" inert />
  </div>
</template>

<style>
.tab-slide-viewport,
.tab-slide-pane {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}
.tab-slide-viewport {
  position: relative;
  overflow: clip;
}
.tab-slide-snapshots {
  position: absolute;
  inset: 0;
  overflow: clip;
  pointer-events: none;
}
.tab-slide-snapshot {
  pointer-events: none;
  will-change: transform;
}
</style>
