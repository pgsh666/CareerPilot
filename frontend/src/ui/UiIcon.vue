<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  type ComponentPublicInstance,
} from "vue";
import { MorphIcon } from "morphicons/vue";
import "./icons/morphRuntime";
import {
  icons,
  navigationIcons,
  type NavigationIconName,
} from "./icons/catalog";

const props = defineProps<{
  name: string;
  size?: number | string;
  active?: boolean;
  hoverName?: string;
}>();
const glyph = ref<ComponentPublicInstance>();
const engaged = ref(false);
let hovered = false,
  focused = false;
let control: HTMLElement | null = null;
const navigation = computed(
  () => navigationIcons[props.name as NavigationIconName],
);
const emphasized = computed(() => !!props.active || engaged.value);
const shape = computed(() =>
  navigation.value
    ? navigation.value[emphasized.value ? "solid" : "outline"]
    : icons[engaged.value && props.hoverName ? props.hoverName : props.name] ||
      icons.file,
);
function update() {
  engaged.value =
    !!control &&
    !control.matches(':disabled,[aria-disabled="true"]') &&
    !control.closest("[inert]") &&
    (hovered || focused);
}
function enter(event: PointerEvent) {
  if (event.pointerType !== "touch") {
    hovered = true;
    update();
  }
}
function leave() {
  hovered = false;
  update();
}
function focus() {
  focused = true;
  update();
}
function blur(event: FocusEvent) {
  focused =
    event.relatedTarget instanceof Node &&
    !!control?.contains(event.relatedTarget);
  update();
}
onMounted(() => {
  if (!navigation.value && !props.hoverName) return;
  control =
    (glyph.value?.$el as SVGElement | undefined)?.closest<HTMLElement>(
      "button, a, [role=button]",
    ) || null;
  control?.addEventListener("pointerenter", enter);
  control?.addEventListener("pointerleave", leave);
  control?.addEventListener("focusin", focus);
  control?.addEventListener("focusout", blur);
});
onBeforeUnmount(() => {
  control?.removeEventListener("pointerenter", enter);
  control?.removeEventListener("pointerleave", leave);
  control?.removeEventListener("focusin", focus);
  control?.removeEventListener("focusout", blur);
});
</script>
<template>
  <MorphIcon
    ref="glyph"
    class="ui-icon"
    :data-icon="name"
    :data-icon-emphasized="navigation ? emphasized : undefined"
    :icon="shape"
    :size="size || 20"
    :stroke-width="1.7"
    spring="smooth"
    reduced-motion="user"
    aria-hidden="true"
    focusable="false"
  />
</template>
