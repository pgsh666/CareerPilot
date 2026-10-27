<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import UiIcon from "./UiIcon.vue";
import { state } from "../core/state";
import {
  navigationLabels,
  previousNavigation,
  navigationDuration,
} from "./navigationMotion";
const route = useRoute();
const current = computed(() => String(route.meta.nav || "首页"));
const index = computed(() =>
  Math.max(0, navigationLabels.indexOf(current.value)),
);
const indicator = ref<HTMLElement>();
let animation: Animation | undefined;
function glide(from: number, to: number) {
  const origin = indicator.value
    ? getComputedStyle(indicator.value).transform
    : "none";
  const originIndex =
    indicator.value && origin !== "none"
      ? new DOMMatrixReadOnly(origin).m41 / indicator.value.offsetWidth / 2
      : from;
  animation?.cancel();
  if (
    !indicator.value ||
    from === to ||
    matchMedia("(prefers-reduced-motion: reduce)").matches
  )
    return;
  animation = indicator.value.animate(
    [
      {
        transform: origin === "none" ? `translateX(${from * 200}%)` : origin,
        offset: 0,
      },
      {
        transform: `translateX(${(originIndex + (to - originIndex) * 0.58) * 200}%) scaleX(1.18) scaleY(.94)`,
        offset: 0.47,
      },
      {
        transform: `translateX(${to * 200}%) scaleX(1.055) scaleY(.985)`,
        offset: 0.8,
      },
      { transform: `translateX(${to * 200}%) scaleX(.985)`, offset: 0.93 },
      { transform: `translateX(${to * 200}%) scaleX(1)`, offset: 1 },
    ],
    { duration: navigationDuration, easing: "cubic-bezier(.32, .08, .18, 1)" },
  );
  indicator.value.dataset.moving = "true";
  const running = animation;
  running.finished
    .catch(() => {})
    .finally(() => {
      if (animation === running && indicator.value)
        delete indicator.value.dataset.moving;
    });
}
onMounted(() => glide(previousNavigation.value, index.value));
watch(index, (next, previous) => glide(previous, next), { flush: "pre" });
onBeforeUnmount(() => animation?.cancel());
const entries = computed(() => [
  { label: "首页", icon: "home", to: "/home" },
  { label: "面试", icon: "interview", to: "/interview" },
  { label: "简历", icon: "resume", to: "/resumes" },
  { label: "历史", icon: "history", to: "/history" },
  {
    label: "设置",
    icon: "settings",
    to: state.account.role === "admin" ? "/admin" : "/settings",
  },
]);
</script>
<template>
  <nav class="home-navigation" aria-label="主导航">
    <span
      ref="indicator"
      class="navigation-indicator"
      aria-hidden="true"
      :style="{ transform: `translateX(${index * 200}%)` }"
    />
    <RouterLink
      v-for="item in entries"
      :key="item.label"
      :to="item.to"
      :class="{ current: current === item.label }"
      :aria-current="current === item.label ? 'page' : undefined"
      ><UiIcon
        class="navigation-icon"
        :name="item.icon"
        :active="current === item.label"
      /><span>{{ item.label }}</span></RouterLink
    >
  </nav>
</template>
