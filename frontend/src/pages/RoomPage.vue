<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import { finishSession, fixtures, notify, state, tasks } from "../core/state";
import { useSpeech } from "../core/speech";
import { isPreviewMode } from "../core/runtime";
import ServiceRoom from "./ServiceRoom.vue";
const router = useRouter(),
  route = useRoute();
const s = computed(() => (isPreviewMode ? state.session : null)),
  practice = computed(() => s.value?.mode === "practice"),
  task = computed(() => tasks.value.find((t) => t.id === s.value?.task));
const dialog = ref("");
const speech = useSpeech(
  () => s.value?.draft || "",
  (text) => {
    if (s.value) s.value.draft = text;
  },
);
const { recording, transcribing, speaking, error, seconds } = speech;
const question = computed(() => {
  if (!s.value) return "";
  if (practice.value)
    return s.value.stage === "variant"
      ? task.value?.variant || ""
      : task.value?.question || "";
  if (s.value.follow === 1)
    return "请补充你在这一方案中独立负责的部分，并说明作出这个选择的依据。";
  if (s.value.follow === 2)
    return "如果实际情况与预期不同，你会怎样验证原因并调整方案？";
  return fixtures.interview.questions[s.value.main - 1] || "";
});
const canSubmit = computed(
  () => !!s.value?.draft.trim() && !recording.value && !transcribing.value,
);
const duration = computed(
  () =>
    `${String(Math.floor(seconds.value / 60)).padStart(2, "0")}:${String(seconds.value % 60).padStart(2, "0")}`,
);
onMounted(() => {
  if (!isPreviewMode) return;
  if (!s.value || s.value.finished) {
    notify("没有未完成的练习，请先确认材料。");
    router.replace("/interview?tab=prepare");
    return;
  }
  if (
    route.query.stage === "variant" &&
    s.value.mode === "practice" &&
    s.value.originalText
  )
    s.value.stage = "variant";
  speech.speak(question.value);
});
function record() {
  if (recording.value) {
    speech.stop();
    return;
  }
  if (s.value?.draft.trim()) dialog.value = "replace";
  else speech.start();
}
function submit() {
  if (!s.value || !canSubmit.value) return;
  speech.stopSpeaking();
  s.value.answers.push({
    question: question.value,
    text: s.value.draft.trim(),
    main: s.value.main,
    follow: s.value.follow,
    skipped: false,
  });
  if (practice.value) {
    if (s.value.stage === "original")
      s.value.originalText = s.value.draft.trim();
    else s.value.variantText = s.value.draft.trim();
    s.value.draft = "";
    s.value.feedback = true;
  } else {
    s.value.draft = "";
    if (s.value.follow < 2) s.value.follow++;
    else nextMain();
    if (s.value && !s.value.finished)
      nextTick(() => speech.speak(question.value));
  }
}
function nextMain() {
  if (!s.value) return;
  if (s.value.main >= s.value.count) end(false);
  else {
    s.value.main++;
    s.value.follow = 0;
  }
}
function skip() {
  if (!s.value || recording.value || transcribing.value) return;
  dialog.value = "skip";
}
function end(early: boolean) {
  speech.cancel();
  const id = finishSession(early);
  if (id) router.push(practice.value ? `/practice/${id}` : `/reports/${id}`);
}
function nextStage() {
  if (!s.value) return;
  if (s.value.stage === "variant") {
    end(false);
    return;
  }
  s.value.stage = "variant";
  s.value.main = 2;
  s.value.feedback = false;
  s.value.draft = "";
  nextTick(() => speech.speak(question.value));
}
function confirm() {
  const action = dialog.value;
  dialog.value = "";
  if (action === "replace") speech.start();
  else if (action === "end") end(true);
  else if (action === "skip" && s.value) {
    speech.stopSpeaking();
    s.value.answers.push({
      question: question.value,
      text: "",
      main: s.value.main,
      follow: s.value.follow,
      skipped: true,
    });
    s.value.draft = "";
    if (practice.value) end(true);
    else {
      nextMain();
      if (!s.value.finished) nextTick(() => speech.speak(question.value));
    }
  }
}
</script>
<template>
  <ServiceRoom v-if="!isPreviewMode" :key="String(route.query.id || 'active')" />
  <AppShell v-else :title="practice ? '薄弱项复练' : '模拟面试'"
    ><template #actions
      ><button
        v-if="s && !s.finished"
        class="ui-button"
        @click="dialog = 'end'"
      >
        {{ practice ? "结束复练" : "结束面试" }}
      </button></template
    >
    <section v-if="s && !s.finished" class="ui-panel room-panel">
      <SlidingTabs
        :active="`${s.stage}-${s.main}-${s.follow}-${s.feedback ? 'feedback' : 'answer'}`"
        :order="[]"
      >
        <template v-if="s.feedback"
          ><div class="room-feedback">
            <span class="ui-badge green">已提交</span>
            <h2>{{ s.stage === "original" ? "原题重答" : "变式验证" }}</h2>
            <blockquote>
              {{ s.stage === "original" ? s.originalText : s.variantText }}
            </blockquote>
            <div class="feedback-placeholders">
              <section>
                <h3>已补充</h3>
                <p>反馈待生成</p>
              </section>
              <section>
                <h3>仍需补充</h3>
                <p>反馈待生成</p>
              </section>
            </div>
            <button class="ui-button primary" @click="nextStage">
              {{ s.stage === "original" ? "进入变式练习" : "查看复练详情"
              }}<UiIcon name="arrow" :size="18" />
            </button></div></template
        ><template v-else
          ><div class="room-top">
            <span>{{
              practice
                ? s.stage === "original"
                  ? "原题复练"
                  : "变式练习"
                : `第 ${s.main} 题 / 共 ${s.count} 道主问题${s.follow ? " · 追问 " + s.follow + " / 2" : ""}`
            }}</span
            ><span>{{ practice ? task?.dimension : s.job.role }}</span>
          </div>
          <div class="room-question">
            <div>
              <span>面试官</span
              ><button
                class="text-button"
                :aria-pressed="speaking"
                :disabled="recording || transcribing"
                @click="speech.speak(question)"
              >
                <UiIcon :name="speaking ? 'pause' : 'speaker'" :size="18" />{{
                  speaking ? "暂停播报" : "重播问题"
                }}
              </button>
            </div>
            <p>{{ question }}</p>
          </div>
          <div class="room-answer-heading">
            <label for="room-answer">你的回答</label
            ><span :class="{ recording }" role="status">{{
              recording
                ? `● 录音中 ${duration}`
                : transcribing
                  ? "转写中…"
                  : s.draft
                    ? "已转写 · 可编辑"
                    : "待录音"
            }}</span>
          </div>
          <div class="room-answer-wrap">
            <textarea
              id="room-answer"
              v-model="s.draft"
              aria-label="回答文字"
              :disabled="recording || transcribing"
            />
            <div v-if="recording" class="room-wave" aria-label="录音中">
              <i
                v-for="n in 31"
                :key="n"
                :style="{
                  height: `${10 + ((n * 17 + 11) % 34)}px`,
                  animationDelay: `${(n % 5) * -0.16}s`,
                }"
              />
            </div>
            <div v-if="transcribing" class="room-transcribing">正在转写…</div>
          </div>
          <div class="room-actions">
            <button
              class="text-button skip-button"
              :disabled="recording || transcribing"
              @click="skip"
            >
              跳过本题</button
            ><button
              class="ui-button"
              :class="recording ? 'recording-button' : s.draft ? '' : 'primary'"
              :disabled="transcribing"
              @click="record"
            >
              <UiIcon
                :name="recording ? 'stop' : s.draft ? 'refresh' : 'mic'"
                :size="19"
              />{{
                recording
                  ? "结束录音"
                  : transcribing
                    ? "转写中…"
                    : s.draft
                      ? "重新录音"
                      : "开始录音"
              }}</button
            ><button
              class="ui-button primary"
              :disabled="!canSubmit"
              @click="submit"
            >
              提交回答<UiIcon name="arrow" :size="18" />
            </button>
          </div>
          <p class="room-error inline-error" role="alert">
            {{ error }}
          </p></template
        >
      </SlidingTabs>
    </section>
    <div v-else class="ui-panel empty-state">正在返回面试准备…</div>
    <UiModal
      :open="!!dialog"
      :title="
        dialog === 'replace'
          ? '重新录音'
          : dialog === 'skip'
            ? '跳过本题'
            : practice
              ? '结束复练'
              : '结束面试'
      "
      @close="dialog = ''"
      ><p class="confirm-copy">
        {{
          dialog === "replace"
            ? "重新录音将替换未提交的回答文字，是否继续？"
            : dialog === "skip"
              ? "本题将不生成评价，是否跳过？"
              : "确认结束本次练习？已提交的回答会保留。"
        }}
      </p>
      <template #footer
        ><button class="ui-button" @click="dialog = ''">取消</button
        ><button class="ui-button primary" @click="confirm">
          确认
        </button></template
      ></UiModal
    ></AppShell
  >
</template>
<style scoped>
.room-panel {
  padding: 24px 40px 14px;
}
.room-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  color: #8292ad;
  font-size: 0.95em;
  flex: none;
  margin-bottom: 20px;
}
.room-top > span:first-child {
  color: #5b80e5;
  background: #f1f5ff;
  padding: 5px 12px;
  border-radius: 6px;
}
.room-question {
  border: 1px solid #e4eaf4;
  background: #f8faff;
  border-radius: 16px;
  padding: 20px 24px;
  flex: none;
  min-height: 130px;
}
.room-question > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.9em;
  color: #8292ad;
}
.room-question p {
  font-size: clamp(18px, min(1.527778vw, 2.444444svh), 30px);
  line-height: 1.7;
  color: #344764;
  margin-top: 14px;
  font-weight: 500;
}
.room-answer-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 22px;
  margin-bottom: 12px;
  color: #667895;
  flex: none;
}
.room-answer-heading > span {
  color: #8b98ad;
  font-size: 0.85em;
}
.room-answer-heading > span.recording {
  color: #bc7474;
}
.room-answer-wrap {
  position: relative;
  flex: 1;
  min-height: 100px;
}
.room-answer-wrap textarea {
  width: 100%;
  height: 100%;
  min-height: 100px;
  border: 1px solid #dee5f0;
  border-radius: 12px;
  padding: 18px 20px;
  font: inherit;
  line-height: 1.9;
  resize: none;
  background: white;
}
.room-answer-wrap textarea:disabled {
  background: #fbfcff;
}
.room-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 20px;
  margin-top: 18px;
  flex: none;
}
.room-actions .ui-button {
  min-width: 156px;
}
.skip-button {
  margin-right: auto;
  font-size: 0.9em;
}
.recording-button {
  background: #fcf0f0;
  border-color: #e7bbbb;
  color: #b46c6c;
}
.room-error {
  font-size: 0.8em;
  min-height: 22px;
  padding-top: 4px;
  text-align: right;
}
.room-wave {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  pointer-events: none;
}
.room-wave i {
  width: 3px;
  background: #8ca9ea;
  border-radius: 3px;
  animation: pulse 1s infinite ease-in-out alternate;
}
.room-transcribing {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #8b98ad;
}
.room-feedback {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 18px;
  height: 100%;
  overflow-y: auto;
}
.room-feedback h2 {
  font-size: var(--ui-title);
}
.room-feedback blockquote {
  margin: 0;
  background: #f7f9fd;
  border: 1px solid #e4eaf4;
  border-radius: 12px;
  padding: 20px;
  line-height: 1.9;
  width: 100%;
  white-space: pre-wrap;
}
.feedback-placeholders {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  width: 100%;
  color: #8b98ad;
}
.feedback-placeholders section {
  border: 1px solid #e4eaf4;
  border-radius: 12px;
  padding: 18px;
}
.feedback-placeholders h3 {
  font-size: 1em;
  color: #667895;
  margin-bottom: 12px;
}
.feedback-placeholders p {
  font-size: 0.9em;
}
.room-feedback > .ui-button {
  align-self: flex-end;
  margin-top: auto;
}
@keyframes pulse {
  to {
    transform: scaleY(0.35);
    opacity: 0.55;
  }
}
@media (max-height: 820px) {
  .room-panel {
    padding: 18px 30px 10px;
  }
  .room-top {
    margin-bottom: 14px;
  }
  .room-question {
    min-height: 110px;
    padding: 16px 20px;
  }
  .room-question p {
    margin-top: 10px;
  }
  .room-answer-heading {
    margin-top: 16px;
    margin-bottom: 10px;
  }
  .room-actions {
    margin-top: 14px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .room-wave i {
    animation: none;
  }
}
</style>
