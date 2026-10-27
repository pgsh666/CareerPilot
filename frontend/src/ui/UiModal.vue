<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import UiIcon from "./UiIcon.vue";
const props = defineProps<{
  open: boolean;
  title: string;
  wide?: boolean;
  busy?: boolean;
}>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let previous: HTMLElement | null = null;
function close() {
  if (!props.busy) emit("close");
}
function keydown(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape") {
    e.preventDefault();
    close();
  }
  if (e.key !== "Tab") return;
  const nodes = Array.from(
    panel.value?.querySelectorAll<HTMLElement>(
      'button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),a[href],[tabindex="0"]',
    ) || [],
  ).filter((el) => !!el.getClientRects().length);
  const first = nodes[0],
    last = nodes.at(-1);
  if (!first) {
    e.preventDefault();
    panel.value?.focus();
  } else if (
    e.shiftKey &&
    (document.activeElement === first || document.activeElement === panel.value)
  ) {
    e.preventDefault();
    last?.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      previous = document.activeElement as HTMLElement;
      document.addEventListener("keydown", keydown);
      await nextTick();
      (
        panel.value?.querySelector<HTMLElement>(
          'input:not([type="hidden"]),textarea,button',
        ) || panel.value
      )?.focus();
    } else {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    }
  },
);
onBeforeUnmount(() => document.removeEventListener("keydown", keydown));
</script>
<template>
  <Teleport to="body"
    ><Transition
      name="modal-motion"
      @before-leave="
        (element) => {
          element.setAttribute('inert', '');
          element.setAttribute('aria-hidden', 'true');
        }
      "
    >
      <div v-if="open" class="modal-mask" @mousedown.self="close">
        <section
          ref="panel"
          class="ui-modal"
          :class="{ wide }"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          tabindex="-1"
        >
          <header>
            <h2>{{ title }}</h2>
            <button
              class="icon-button"
              :disabled="busy"
              aria-label="关闭弹窗"
              @click="close"
            >
              <UiIcon name="close" />
            </button>
          </header>
          <div class="modal-body"><slot /></div>
          <footer v-if="$slots.footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>
