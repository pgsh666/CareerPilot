<script setup lang="ts">
import HomeCarousel from "./HomeCarousel.vue";
import { computed } from "vue";
import { destinations, homeData as homeExample } from "./home";
import UiIcon from "../ui/UiIcon.vue";
import { state, tasks } from "../core/state";
import { isPreviewMode } from "../core/runtime";
import { trainingState } from "../core/training";
const activeSession = computed(() =>
  isPreviewMode ? (state.session && !state.session.finished ? state.session : null)
    : trainingState.active ? { mode: trainingState.active.mode, main: trainingState.active.currentQuestion?.main || 0,
      count: trainingState.active.count, originalText: trainingState.active.answers[0]?.text || '',
      variantText: trainingState.active.answers[1]?.text || '', stage: trainingState.active.currentQuestion?.main === 2 ? 'variant' : 'original' } : null,
);
const homeData = computed(() => ({
  ...homeExample,
  mainQuestion:
    activeSession.value?.mode === "practice"
      ? [
          activeSession.value.originalText,
          activeSession.value.variantText,
        ].filter(Boolean).length
      : activeSession.value?.main || 0,
  mainQuestionCount:
    activeSession.value?.mode === "practice"
      ? 2
      : activeSession.value?.count || 1,
  practiceCount: (isPreviewMode ? tasks.value : trainingState.tasks).filter((t) => !t.done).length,
  priority: isPreviewMode
    ? homeExample.priority
    : trainingState.tasks.find((t) => !t.done)?.title || "暂无待复练任务",
  priorityHint: isPreviewMode ? homeExample.priorityHint : trainingState.tasks.find(t => !t.done)?.suggestion || "",
  completedInterviews:
    isPreviewMode ? homeExample.completedInterviews + state.runs.filter((r) => r.kind === "interview" && r.status === "completed").length : trainingState.completedInterviews,
  practiceMinutes:
    isPreviewMode ? homeExample.practiceMinutes + state.runs.reduce((n, r) => n + r.session.minutes, 0) : trainingState.practiceMinutes ?? '—',
}));
</script>

<template>
  <main class="home-content home-dashboard route-screen">
    <HomeCarousel />
    <p v-if="!isPreviewMode && trainingState.error" class="inline-error" role="alert">{{ trainingState.error }}</p>
    <section class="home-cards" aria-label="面试训练">
      <article
        class="home-card continuation-card"
        aria-labelledby="continue-heading"
      >
        <span class="card-icon"><UiIcon name="bulb" /></span>
        <h2 id="continue-heading" class="card-title">继续上一次练习</h2>
        <p class="progress-label">
          <template v-if="activeSession?.mode === 'interview'">
            主问题 {{ homeData.mainQuestion }} /
            {{ homeData.mainQuestionCount }}
          </template>
          <template v-else-if="activeSession">
            {{
              activeSession.stage === "variant" ? "变式验证" : "原题复练"
            }}进行中
          </template>
          <template v-else>暂无进行中的面试</template>
        </p>
        <div
          class="interview-progress"
          role="progressbar"
          :aria-label="
            activeSession?.mode === 'practice' ? '复练进度' : '面试进度'
          "
          :aria-valuenow="homeData.mainQuestion"
          :aria-valuemax="homeData.mainQuestionCount"
          :aria-valuemin="0"
        >
          <span
            :style="{
              width: `${(homeData.mainQuestion / homeData.mainQuestionCount) * 100}%`,
            }"
          ></span>
        </div>
        <a
          class="card-action"
          :href="
            activeSession
              ? isPreviewMode ? destinations.continueInterview : `#/interview/room?id=${trainingState.active?.id}`
              : destinations.newInterview
          "
          ><UiIcon name="play" hover-name="circle-play" /><span>{{
            activeSession
              ? activeSession.mode === "practice"
                ? "继续复练"
                : "继续面试"
              : "开始新面试"
          }}</span></a
        >
      </article>
      <article
        class="home-card practice-card"
        aria-labelledby="practice-heading"
      >
        <span class="card-icon"><UiIcon name="target" /></span>
        <h2 id="practice-heading" class="card-title">薄弱项复练</h2>
        <a
          class="card-more"
          :href="destinations.allPractice"
          :aria-label="`查看全部${homeData.practiceCount}项复练任务`"
          ><span>{{ homeData.practiceCount }} 项待练</span><UiIcon name="next"
        /></a>
        <h3 class="priority-title" :title="homeData.priority">{{ homeData.priority }}</h3>
        <p class="priority-hint" :title="homeData.priorityHint">{{ homeData.priorityHint }}</p>
        <a class="card-action" :href="isPreviewMode ? destinations.priorityPractice : `#/interview?tab=tasks&task=${trainingState.tasks.find(t => !t.done)?.id || ''}`"
          ><UiIcon name="refresh" hover-name="refresh-cycle" /><span
            >开始复练</span
          ></a
        >
      </article>
      <article class="home-card recap-card" aria-labelledby="recap-heading">
        <span class="card-icon"><UiIcon name="chart" /></span>
        <h2 id="recap-heading" class="card-title">训练回顾</h2>
        <a
          class="card-more"
          :href="destinations.history"
          aria-label="查看同岗位、同JD、同评分版本的练习表现趋势"
          ><span>表现趋势</span><UiIcon name="next"
        /></a>
        <dl class="training-metrics">
          <div>
            <dt>已完成面试</dt>
            <dd>
              <strong>{{ homeData.completedInterviews }}</strong
              ><span>场</span>
            </dd>
          </div>
          <div>
            <dt>累计练习时间</dt>
            <dd>
              <strong>{{ homeData.practiceMinutes }}</strong
              ><span>分钟</span>
            </dd>
          </div>
        </dl>
        <a class="card-action" :href="destinations.history"
          ><UiIcon name="clock" hover-name="clock-history" /><span
            >查看训练记录</span
          ></a
        >
      </article>
    </section>
    <div class="home-navigation-row" aria-hidden="true">
      <div class="navigation-space" />
    </div>
  </main>
</template>
