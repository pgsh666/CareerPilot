<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { art, destinations } from "./home";
import { usePageMotion } from "../ui/pageMotion";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import { latestUpdate } from "./updates";

const activeSlide = ref(0);
const announcementOpen = ref(false);
const direction = ref(1);
const viewport = ref<HTMLElement>();
const snapshots = ref<HTMLElement>();
const slideMotion = usePageMotion(viewport, snapshots, {
  direction,
  distance: () => viewport.value?.clientWidth || 0,
  snapshotClass: "carousel-slide-snapshot",
  snapshotLeft: "0",
});
const slideNames = ["产品介绍", "产品特色", "更新公告"];
const hovered = ref(false),
  focused = ref(false);
const visible = ref(!document.hidden);
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
const reducedMotion = ref(motionPreference.matches);
let mounted = false;
let timer: ReturnType<typeof setTimeout> | undefined;
function restart() {
  clearTimeout(timer);
  if (
    !mounted ||
    hovered.value ||
    focused.value ||
    !visible.value ||
    reducedMotion.value ||
    announcementOpen.value
  )
    return;
  timer = setTimeout(
    () => selectSlide((activeSlide.value + 1) % slideNames.length, 1),
    3000,
  );
}
function selectSlide(index: number, travelDirection?: number) {
  direction.value = travelDirection || (index < activeSlide.value ? -1 : 1);
  activeSlide.value = index;
  restart();
}
function focusOut(event: FocusEvent) {
  focused.value =
    event.relatedTarget instanceof Node &&
    (event.currentTarget as HTMLElement).contains(event.relatedTarget);
}
function visibilityChanged() {
  visible.value = !document.hidden;
}
function preferenceChanged() {
  reducedMotion.value = motionPreference.matches;
}
watch(
  [activeSlide, hovered, focused, visible, reducedMotion, announcementOpen],
  restart,
);
onMounted(() => {
  mounted = true;
  document.addEventListener("visibilitychange", visibilityChanged);
  motionPreference.addEventListener("change", preferenceChanged);
  restart();
});
onBeforeUnmount(() => {
  mounted = false;
  clearTimeout(timer);
  document.removeEventListener("visibilitychange", visibilityChanged);
  motionPreference.removeEventListener("change", preferenceChanged);
});
const capabilities = [
  {
    icon: "file",
    title: "围绕你的经历出题",
    lines: ["结合简历项目与目标 JD，", "让问题贴近本次求职方向。"],
    foot: "简历信息 × 岗位要求",
  },
  {
    icon: "conversation",
    title: "追问关键缺失信息",
    lines: ["沿着回答澄清细节，", "偏离主题时引导回到重点。"],
    foot: "缺项追问 · 偏题引导",
  },
  {
    icon: "evidence",
    title: "有证据的反馈与复练",
    lines: ["引用回答中的具体内容，", "先改写，再用变式题检验。"],
    foot: "原题改写 → 变式检验",
  },
];
async function moveSlide(event: KeyboardEvent, index: number) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? 2
        : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3;
  selectSlide(
    next,
    event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : undefined,
  );
  await nextTick();
  document.getElementById(`home-slide-tab-${activeSlide.value}`)?.focus();
}
</script>

<template>
  <section
    class="home-carousel"
    aria-label="首页轮播"
    aria-roledescription="轮播图"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
    @focusin="focused = true"
    @focusout="focusOut"
  >
    <img
      class="hero-decoration"
      :src="art['hero-orbits']"
      alt=""
      aria-hidden="true"
    />
    <div
      ref="viewport"
      id="home-slide-panel"
      role="tabpanel"
      aria-live="off"
      :aria-labelledby="`home-slide-tab-${activeSlide}`"
    >
      <Transition :css="false" v-on="slideMotion">
        <div
          v-if="activeSlide === 0"
          class="carousel-slide intro-slide"
          data-slide="intro"
        >
          <p class="hero-eyebrow">CareerPilot · AI 求职与模拟面试助手</p>
          <h1 class="hero-title">围绕目标岗位，练好每一次面试</h1>
          <p class="hero-copy">
            结合简历与岗位要求，模拟追问、查看反馈，再针对薄弱项复练。
          </p>
          <a class="hero-start" :href="destinations.newInterview"
            ><span>开始新面试</span><UiIcon name="arrow"
          /></a>
        </div>
        <div
          v-else-if="activeSlide === 1"
          class="carousel-slide feature-slide"
          data-slide="features"
        >
          <div class="feature-introduction">
            <p class="feature-eyebrow">产品特色 · 三大核心能力</p>
            <h1>个性化提问，<br />针对性练习</h1>
            <p class="feature-intro">
              围绕真实经历，<br />让每次练习都有明确方向。
            </p>
          </div>
          <div class="feature-capabilities">
            <article
              v-for="(capability, index) in capabilities"
              :key="capability.icon"
              class="capability"
            >
              <span class="capability-icon"
                ><UiIcon :name="capability.icon"
              /></span>
              <span class="capability-number">0{{ index + 1 }}</span>
              <h2>{{ capability.title }}</h2>
              <p>{{ capability.lines[0] }}<br />{{ capability.lines[1] }}</p>
              <span class="capability-foot">{{ capability.foot }}</span>
            </article>
          </div>
        </div>
        <div v-else class="carousel-slide" data-slide="announcement">
          <div class="announcement-slide">
            <span class="announcement-icon"
              ><UiIcon name="announcement"
            /></span>
            <div class="announcement-copy">
              <p class="announcement-eyebrow">
                更新公告 · {{ latestUpdate.date }}
              </p>
              <h1>{{ latestUpdate.title }}</h1>
              <p class="announcement-summary">{{ latestUpdate.summary }}</p>
              <button
                class="announcement-details"
                @click="announcementOpen = true"
              >
                查看更新详情 <UiIcon name="next" :size="15" />
              </button>
            </div>
          </div>
        </div>
      </Transition>
      <div
        ref="snapshots"
        class="carousel-slide-snapshots"
        aria-hidden="true"
        inert
      />
    </div>
    <div class="carousel-dots" role="tablist" aria-label="轮播页面">
      <button
        v-for="(name, index) in slideNames"
        :id="`home-slide-tab-${index}`"
        :key="name"
        type="button"
        role="tab"
        :aria-label="name"
        :aria-selected="activeSlide === index"
        aria-controls="home-slide-panel"
        :tabindex="activeSlide === index ? 0 : -1"
        :class="{ active: activeSlide === index }"
        @click="selectSlide(index)"
        @keydown="moveSlide($event, index)"
      >
        <span></span>
      </button>
    </div>
    <UiModal
      :open="announcementOpen"
      wide
      title="更新公告"
      @close="announcementOpen = false"
    >
      <div class="release-notes">
        <p class="release-date">{{ latestUpdate.date }}</p>
        <h3>{{ latestUpdate.title }}</h3>
        <section v-for="item in latestUpdate.items" :key="item.title">
          <h4>{{ item.title }}</h4>
          <p>{{ item.text }}</p>
        </section>
      </div>
      <template #footer
        ><button class="ui-button primary" @click="announcementOpen = false">
          知道了
        </button></template
      >
    </UiModal>
  </section>
</template>
<style scoped>
#home-slide-panel {
  position: absolute;
  inset: 0;
  overflow: clip;
}
.carousel-slide,
.carousel-slide-snapshots {
  position: absolute;
  inset: 0;
}
.release-notes {
  color: #61738e;
  line-height: 1.8;
}
.release-date {
  color: #95a1b4;
  font-size: 13px;
}
.release-notes h3 {
  color: #344764;
  font-size: 18px;
  margin: 8px 0 18px;
}
.release-notes section {
  margin: 14px 0;
}
.release-notes h4 {
  color: #526784;
  margin: 0 0 4px;
  font-size: 15px;
}
.release-notes p {
  margin: 0;
}
.carousel-slide-snapshots {
  pointer-events: none;
}
</style>
