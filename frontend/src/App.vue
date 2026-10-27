<script setup lang="ts">
import { RouterView } from "vue-router";
import { useRoute } from "vue-router";
import { computed, nextTick, ref, watch } from "vue";
import { state, toast, storageError } from "./core/state";
import AppHeader from "./ui/AppHeader.vue";
import BottomNav from "./ui/BottomNav.vue";
import { usePageMotion } from "./ui/pageMotion";
const route = useRoute();
const viewport = ref<HTMLElement>();
const snapshots = ref<HTMLElement>();
const identitySwitching = ref(false);
const pageMotion = usePageMotion(viewport, snapshots, {
  disabled: identitySwitching,
});
const entryViewport = ref<HTMLElement>();
const entrySnapshots = ref<HTMLElement>();
const entryDirection = computed(() => (route.meta.nav ? 1 : -1));
const entryMotion = usePageMotion(entryViewport, entrySnapshots, {
  direction: entryDirection,
  snapshotClass: "entry-snapshot",
  snapshotLeft: "0",
  disabled: identitySwitching,
});
watch(
  () => state.account.id,
  async (id, previous) => {
    if (!id || !previous || id === previous) return;
    identitySwitching.value = true;
    await nextTick();
    identitySwitching.value = false;
  },
  { flush: "sync" },
);
</script>
<template>
  <svg class="glass-filter-definitions" aria-hidden="true" focusable="false">
    <defs>
      <filter
        id="careerpilot-glass-refraction"
        x="-20%"
        y="-20%"
        width="140%"
        height="140%"
        color-interpolation-filters="sRGB"
      >
        <feTurbulence
          type="fractalNoise"
          baseFrequency=".012 .022"
          numOctaves="1"
          seed="8"
          result="ripple"
        />
        <feGaussianBlur in="ripple" stdDeviation="1.5" result="smooth-ripple" />
        <feDisplacementMap
          in="SourceGraphic"
          in2="smooth-ripple"
          scale="16"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
    </defs>
  </svg>
  <div ref="entryViewport" class="entry-viewport">
    <RouterView v-slot="{ Component, route: screen }">
      <Transition :css="false" v-on="entryMotion">
        <div
          v-if="screen.meta.nav && state.signedIn"
          key="application"
          class="home-page application-shell"
        >
          <AppHeader />
          <div ref="viewport" class="route-viewport">
            <Transition :css="false" v-on="pageMotion">
              <component
                :is="Component"
                :key="`${screen.path}:${state.account.id}`"
              />
            </Transition>
            <div
              ref="snapshots"
              class="route-snapshots"
              aria-hidden="true"
              inert
            />
          </div>
          <div class="persistent-navigation"><BottomNav /></div>
        </div>
        <component
          v-else-if="!screen.meta.nav"
          :is="Component"
          key="authentication"
        />
      </Transition>
    </RouterView>
    <div
      ref="entrySnapshots"
      class="entry-snapshots"
      aria-hidden="true"
      inert
    />
  </div>
  <div v-if="toast" class="global-toast" role="status">{{ toast }}</div>
  <div v-if="storageError" class="global-toast error" role="alert">
    {{ storageError }}
  </div>
</template>
