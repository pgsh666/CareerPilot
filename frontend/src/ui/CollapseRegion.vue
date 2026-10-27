<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  open: boolean;
  availableHeight?: () => number;
  animateHeader?: boolean;
}>();
const emit = defineEmits<{ expanded: [] }>();
const region = ref<HTMLElement>();
const content = ref<HTMLElement>();
const rendered = ref(props.open);
const busy = ref(false);
const preference = matchMedia("(prefers-reduced-motion: reduce)");
let animations: Animation[] = [];
let generation = 0;
let lastHeaderHeight = 0;
type HeaderPart = {
  element: HTMLElement;
  kind: string;
  left: number;
  top: number;
  width: number;
  height: number;
  opacity: string;
};
let lastHeaderParts: HeaderPart[] = [];
let observer: ResizeObserver | undefined;
function header() {
  return props.animateHeader
    ? (region.value?.previousElementSibling as HTMLElement | null)
    : null;
}
function measureHeader(): HeaderPart[] {
  const head = header();
  if (!head) return [];
  const bounds = head.getBoundingClientRect();
  return Array.from(
    head.querySelectorAll<HTMLElement>("[data-record-part]"),
  ).map((element) => {
    const rect = element.getBoundingClientRect();
    return {
      element,
      kind: element.dataset.recordPart || "",
      left: rect.left - bounds.left - head.clientLeft,
      top: rect.top - bounds.top - head.clientTop,
      width: rect.width,
      height: rect.height,
      opacity: getComputedStyle(element).opacity,
    };
  });
}
function targetHeight() {
  const border = region.value?.parentElement
    ? getComputedStyle(region.value.parentElement)
    : null;
  const borderHeight = border
    ? parseFloat(border.borderTopWidth) + parseFloat(border.borderBottomWidth)
    : 0;
  return Math.max(
    0,
    props.availableHeight
      ? props.availableHeight() -
          (header()?.getBoundingClientRect().height || 0) -
          borderHeight
      : content.value?.scrollHeight || 0,
  );
}
function cancel() {
  animations.forEach((animation) => animation.cancel());
  animations = [];
}
async function change(open: boolean) {
  const token = ++generation;
  const from = region.value?.getBoundingClientRect().height || 0;
  const fromHeader = animations.length
    ? header()?.getBoundingClientRect().height || 0
    : lastHeaderHeight || header()?.getBoundingClientRect().height || 0;
  const fromParts = animations.length ? measureHeader() : lastHeaderParts;
  cancel();
  if (open) rendered.value = true;
  await nextTick();
  if (token !== generation || !region.value) return;
  const head = header();
  const toHeader = head?.getBoundingClientRect().height || 0;
  const toParts = measureHeader();
  lastHeaderHeight = toHeader;
  const to = open ? targetHeight() : 0;
  if (content.value) content.value.style.height = `${open ? to : from}px`;
  region.value.style.height = `${to}px`;
  if (preference.matches) {
    rendered.value = open;
    busy.value = false;
    if (open) emit("expanded");
    return;
  }
  busy.value = true;
  animations = [
    region.value.animate([{ height: `${from}px` }, { height: `${to}px` }], {
      duration: 500,
      easing: "cubic-bezier(.32,.08,.18,1)",
      fill: "both",
    }),
  ];
  if (head)
    animations.push(
      head.animate(
        [
          { height: `${fromHeader}px`, minHeight: `${fromHeader}px` },
          { height: `${toHeader}px`, minHeight: `${toHeader}px` },
        ],
        { duration: 500, easing: "cubic-bezier(.32,.08,.18,1)", fill: "both" },
      ),
    );
  for (const toPart of toParts) {
    const fromPart = fromParts.find((part) => part.element === toPart.element);
    if (!fromPart) continue;
    let frames: Keyframe[];
    if (toPart.kind === "layout") {
      // Temporarily position the three header groups independently. Flex centering
      // would otherwise move them again while the header itself changes height.
      frames = [fromPart, toPart].map((part) => ({
        position: "absolute",
        left: `${part.left}px`,
        top: `${part.top}px`,
        width: `${part.width}px`,
        height: `${part.height}px`,
      }));
    } else if (toPart.kind === "summary") {
      frames = [fromPart, toPart].map((part) => ({
        height: `${part.height}px`,
        opacity: part.opacity,
      }));
    } else {
      frames = [fromPart, toPart].map((part) => ({
        width: `${part.width}px`,
        height: `${part.height}px`,
      }));
    }
    animations.push(
      toPart.element.animate(frames, {
        duration: 500,
        easing: "cubic-bezier(.32,.08,.18,1)",
        fill: "both",
      }),
    );
  }
  await Promise.allSettled(animations.map((animation) => animation.finished));
  if (token !== generation) return;
  // Keep every final keyframe through a paint before removing the editor.
  // Otherwise the header's natural layout and form teardown compete at the
  // last frame, while the scroll container may still be changing its gutter.
  await new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
  if (token !== generation) return;
  cancel();
  lastHeaderParts = measureHeader();
  rendered.value = open;
  busy.value = false;
  if (open) emit("expanded");
}
function settle() {
  animations.forEach((animation) => animation.finish());
  if (props.open && region.value && content.value && !busy.value) {
    const height = targetHeight();
    region.value.style.height = `${height}px`;
    content.value.style.height = `${height}px`;
  }
  if (!busy.value)
    lastHeaderHeight = header()?.getBoundingClientRect().height || 0;
  if (!busy.value) lastHeaderParts = measureHeader();
}
watch(() => props.open, change, { flush: "pre" });
onMounted(() => {
  lastHeaderHeight = header()?.getBoundingClientRect().height || 0;
  lastHeaderParts = measureHeader();
  if (props.open) change(true);
  observer = new ResizeObserver(() => {
    if (!busy.value) settle();
  });
  if (region.value?.parentElement?.parentElement)
    observer.observe(region.value.parentElement.parentElement);
  if (header()) observer.observe(header()!);
  window.addEventListener("resize", settle);
  preference.addEventListener("change", settle);
});
onBeforeUnmount(() => {
  generation++;
  cancel();
  observer?.disconnect();
  window.removeEventListener("resize", settle);
  preference.removeEventListener("change", settle);
});
</script>

<template>
  <div
    ref="region"
    class="collapse-region"
    :data-expanding="busy || undefined"
    :aria-hidden="!open"
    :inert="!open"
  >
    <div v-if="rendered" ref="content" class="collapse-content"><slot /></div>
  </div>
</template>

<style>
.collapse-region {
  height: 0;
  overflow: clip;
  flex: none;
  contain: layout paint;
}
.collapse-content {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.collapse-region[data-expanding] > .collapse-content {
  will-change: transform;
}
.record-summary {
  display: flow-root;
  overflow: clip;
}
.expanded .record-summary {
  height: 0;
  opacity: 0;
}
</style>
