<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import UiIcon from "../ui/UiIcon.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import AnswerEvidence from "../ui/AnswerEvidence.vue";
import { errorMessage } from "../core/api";
import { state } from "../core/state";
import {
  getTraining,
  retryGeneration,
  statusLabel,
  trainingState,
  loadTrainingSummary,
  type Training,
} from "../core/training";
const route = useRoute(),
  row = ref<Training | null>(null),
  error = ref(""),
  tab = ref("overview"),
  selected = ref(1),
  busy = ref(false);
const isPractice = computed(() => route.meta.kind === "practice");
const tabs = computed(() =>
  isPractice.value
    ? [
        { id: "original", name: "原题对照" },
        { id: "variant", name: "变式验证" },
      ]
    : [
        { id: "overview", name: "报告概览" },
        { id: "questions", name: "逐题回顾" },
        { id: "dimensions", name: "维度评分" },
      ],
);
const mainNumbers = computed(() => [
  ...new Set(row.value?.questions.map((q) => q.main) || []),
]);
const groupQuestions = computed(
  () => row.value?.questions.filter((q) => q.main === selected.value) || [],
);
const groupFeedback = computed(() =>
  row.value?.report?.questions.find(
    (f) =>
      row.value?.questions.find((q) => q.id === f.question_id)?.main ===
      selected.value,
  ),
);
const stage = computed(() => (tab.value === "variant" ? 2 : 1));
const stageQuestion = computed(
  () => row.value?.questions.filter((q) => q.main === stage.value).slice(-1)[0],
);
const stageAnswer = computed(() =>
  row.value?.answers.find((a) => a.question_id === stageQuestion.value?.id),
);
const sourceQuestion = computed(
  () => trainingState.tasks.find((t) => t.id === row.value?.taskId)?.questionId,
);
let version = 0,
  alive = true,
  polling = false;
let timer: ReturnType<typeof setInterval>;
const owner = state.account.id;
async function load() {
  if (polling || !alive || owner !== state.account.id) return;
  polling = true;
  const v = version,
    id = String(route.params.id);
  try {
    const result = await getTraining(id);
    if (!alive || v !== version || owner !== state.account.id) return;
    if ((result.mode === "practice") !== isPractice.value)
      throw new Error("记录类型不匹配，请从历史记录打开对应详情");
    const first = row.value === null;
    row.value = result;
    error.value = "";
    if (first && route.query.question)
      selected.value =
        result.questions.find((q) => q.id === route.query.question)?.main || 1;
  } catch (e) {
    if (alive && v === version) error.value = errorMessage(e);
  } finally {
    polling = false;
    if (alive && v !== version) void load();
  }
}
watch(
  () => [route.params.id, route.meta.kind],
  async () => {
    version++;
    row.value = null;
    selected.value = 1;
    error.value = "";
    tab.value = String(
      route.query.tab || (isPractice.value ? "original" : "overview"),
    );
    clearInterval(timer);
    await load();
    await loadTrainingSummary();
    timer = setInterval(() => {
      if (
        document.visibilityState === "visible" &&
        row.value?.jobs.some((j) =>
          ["queued", "running", "ready", "paused"].includes(j.state),
        )
      )
        void load();
    }, 2000);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  alive = false;
  version++;
  clearInterval(timer);
});
function answer(id: string) {
  return row.value?.answers.find((a) => a.question_id === id);
}
const failed = computed(
  () =>
    row.value?.jobs.filter(
      (j) => j.state === "failed" && !["asr", "tts"].includes(j.kind),
    ) || [],
);
async function retry(id: string) {
  busy.value = true;
  try {
    await retryGeneration(id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function displayTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}
</script>
<template>
  <AppShell :title="isPractice ? '复练详情' : '面试报告'">
    <template #actions
      ><RouterLink
        class="ui-button"
        :to="`/history?tab=${isPractice ? 'practice' : 'interview'}`"
        ><UiIcon name="back" :size="17" />返回历史</RouterLink
      ></template
    >
    <section v-if="!row" class="ui-panel empty-state">
      <h2 v-if="error">该记录暂无详情</h2>
      <p role="alert">{{ error || "正在加载记录…" }}</p>
      <button v-if="error" class="ui-button" @click="load">重新加载</button>
    </section>
    <section v-else class="ui-panel result-panel">
      <header class="result-meta">
        <div class="result-meta-copy">
          <div class="result-meta-title">
            <h2>
              {{ row.job.title }} · {{ isPractice ? "薄弱项复练" : "模拟面试" }}
            </h2>
            <span
              class="ui-badge"
              :class="{ green: row.status === 'completed' }"
              >{{ statusLabel(row.status) }}</span
            >
          </div>
          <p>
            {{ displayTime(row.startedAt) }}<i />JD v{{ row.job.version
            }}<i />{{ row.resume.title }}
          </p>
        </div>
        <template v-if="!isPractice"
          ><div class="result-metric">
            <span>已答主问题</span
            ><strong
              >{{ row.answeredMain }}<small> / {{ row.count }}</small></strong
            >
          </div>
          <div class="result-metric"><span>评分证据覆盖</span><strong>{{ row.evidenceCoverage === null ? '—' : `${row.evidenceCoverage}%` }}</strong></div>
          <div class="result-metric score">
            <span>综合分</span><strong>{{ row.score ?? '—' }}</strong>
          </div></template
        >
        <div v-else class="result-stages">
          <span
            >{{ row.answers.filter((a) => a.text && !a.skipped).length }} / 2
            阶段已提交</span
          >
        </div>
      </header>
      <div
        class="ui-tabs result-tabs"
        role="tablist"
        :aria-label="isPractice ? '复练详情内容' : '面试报告内容'"
      >
        <button
          v-for="item in tabs"
          :key="item.id"
          role="tab"
          :aria-selected="tab === item.id"
          :class="{ active: tab === item.id }"
          @click="tab = item.id"
        >
          {{ item.name }}
        </button>
      </div>
      <div
        v-for="j in failed"
        :key="j.id"
        class="result-error inline-error"
        role="alert"
      >
        {{ j.errorMessage }}
        <button
          v-if="j.retryAllowed"
          class="text-button"
          :disabled="busy"
          @click="retry(j.id)"
        >
          重试生成
        </button>
      </div>
      <p v-if="error" class="result-error inline-error" role="alert">
        {{ error }}
      </p>
      <div
        v-if="
          ['active', 'interrupted'].includes(row.status) ||
          (isPractice && row.status === 'early_ended')
        "
        class="result-resume"
      >
        <RouterLink
          class="ui-button primary"
          :to="`/interview/room?id=${row.id}`"
          >{{ isPractice ? "继续复练" : "继续面试" }}</RouterLink
        >
      </div>
      <SlidingTabs :active="tab" :order="tabs.map((item) => item.id)">
        <section
          v-if="!isPractice && tab === 'overview'"
          class="result-overview ui-scroll"
        >
          <p class="report-summary">
            {{
              row.report?.summary ||
              (row.status === "active" || row.status === "interrupted"
                ? "练习尚未结束，结束后统一生成反馈。"
                : row.reportState === "failed"
                  ? "报告暂未生成，已保留真实问答。"
                  : "报告正在生成，已保留真实问答。")
            }}
          </p>
          <div class="section-heading">
            <h3>优先改进</h3>
            <span class="muted-copy"
              >{{ row.report?.improvements.length || 0 }} 项</span
            >
          </div>
          <div class="priority-grid">
            <article
              v-for="item in row.report?.improvements || []"
              :key="item.question_id"
              class="priority-card"
            >
              <div class="priority-heading">
                <span>{{ item.focus }}</span
                ><RouterLink
                  class="text-button"
                  :to="{
                    path: '/interview',
                    query: {
                      tab: 'tasks',
                      task: trainingState.tasks.find(
                        (t) =>
                          t.sourceId === row!.id &&
                          t.questionId === item.question_id,
                      )?.id,
                      source: row.id,
                    },
                  }"
                  >去复练<UiIcon name="next" :size="14"
                /></RouterLink>
              </div>
              <h4>
                {{ row.questions.find((q) => q.id === item.question_id)?.text }}
              </h4>
              <blockquote>{{ item.quote }}</blockquote>
              <p>{{ item.suggestion }}</p>
            </article>
          </div>
          <p
            v-if="row.report && !row.report.improvements.length"
            class="muted-copy"
          >
            本次没有生成待复练任务。
          </p>
        </section>
        <section
          v-else-if="!isPractice && tab === 'questions'"
          class="service-question-review"
        >
          <nav aria-label="主问题" class="question-list ui-scroll">
            <button
              v-for="main in mainNumbers"
              :key="main"
              :class="{ active: selected === main }"
              @click="selected = main"
            >
              主问题 {{ main }}
            </button>
          </nav>
          <div class="service-review-copy ui-scroll">
            <template v-for="q in groupQuestions" :key="q.id"
              ><h3>{{ q.follow ? `追问 ${q.follow}` : `主问题 ${q.main}` }}</h3>
              <p>{{ q.text }}</p>
              <blockquote class="actual-answer">
                {{
                  answer(q.id)?.skipped
                    ? "已跳过"
                    : answer(q.id)?.text || "未作答"
                }}
              </blockquote>
              <details v-if="q.referencePoints?.length">
                <summary>出题时锁定的参考要点</summary>
                <ul><li v-for="point in q.referencePoints" :key="point">{{ point }}</li></ul>
                <p class="muted-copy">有依据的不同解法也可认可，无须逐字匹配。</p>
              </details></template
            ><AnswerEvidence
              :feedback="groupFeedback"
              :pending="
                row.reportState === 'empty'
                  ? '没有有效回答，暂无评价'
                  : '本题反馈待生成'
              "
            />
          </div>
        </section>
        <section v-else-if="!isPractice" class="result-dimensions ui-scroll">
          <template v-if="row.scoring">
            <p class="report-summary">评分版本 {{ row.scoreVersion }} · 已答 {{ row.answeredMain }}/{{ row.count }} 题组 · 有评分依据 {{ row.scoring.scorableGroups }} 组</p>
            <p v-if="row.scoring.reasons.length" class="inline-error" role="status">综合分暂不展示：{{ row.scoring.reasons.join('；') }}。</p>
            <div class="dimension-grid">
              <article v-for="d in row.scoring.dimensions" :key="d.id">
                <div><h4>{{ d.name }}</h4><strong>{{ d.score ?? 'N/A' }}</strong></div>
                <div v-if="d.score !== null" class="dimension-bar"><i :style="{ width: `${d.score}%` }" /></div>
                <span>权重 {{ d.weight }}% · 有依据 {{ d.coveredGroups }}/{{ d.plannedGroups }} 题组 · 覆盖 {{ d.coverage }}%</span>
                <details v-if="d.ratings.length">
                  <summary>查看分档及原话依据</summary>
                  <section v-for="rating in d.ratings" :key="rating.questionId" class="service-rating-evidence">
                    <strong>主问题 {{ row.questions.find(q => q.id === rating.questionId)?.main }} · {{ rating.level === null ? 'N/A' : `${rating.level}档（${rating.level * 25}分）` }}</strong>
                    <p>{{ rating.reason }}</p>
                    <blockquote v-for="e in rating.evidence" :key="`${e.answer_id}-${e.quote}`">{{ e.quote }}</blockquote>
                  </section>
                </details>
              </article>
            </div>
            <p class="muted-copy">主问与追问合为一个题组，同维度有效题组分数等权平均；N/A不补零。覆盖率衡量可评价范围，不表示回答正确率。</p>
          </template>
          <template v-else-if="row.scoreState === 'rules_pending'">
            <h3>本场保留原版本反馈</h3>
            <p class="report-summary">本场开始时尚未启用固定评分规则，保留当时的定性反馈，不回填正式分数，也不计入评分趋势。</p>
          </template>
          <template v-else>
            <h3>{{ row.scoreState === 'generating' ? '评分生成中' : '暂无可展示的维度评分' }}</h3>
            <p class="report-summary">{{ row.scoreState === 'failed' ? '本次报告生成未完成，请按任务提示重试；已提交问答仍保留。' : '结束训练后依据实际回答生成；无评分依据时不补零或编造分数。' }}</p>
          </template>
        </section>
        <section v-else class="practice-detail ui-scroll">
          <div class="section-heading">
            <h3>{{ stage === 1 ? "原题对照" : "变式验证" }}</h3>
            <RouterLink
              v-if="row.sourceId"
              class="text-button"
              :to="{
                path: `/reports/${row.sourceId}`,
                query: { tab: 'questions', question: sourceQuestion },
              }"
              >返回来源题目<UiIcon name="next" :size="14"
            /></RouterLink>
          </div>
          <p>{{ stageQuestion?.text || "完成原题重答后进入变式练习。" }}</p>
          <div v-if="stage === 1" class="source-original">
            <h3>来源原答 · 只读</h3>
            <blockquote class="actual-answer">
              {{ row.sourceAnswer }}
            </blockquote>
          </div>
          <h3>{{ stage === 1 ? "本次重答" : "变式回答" }}</h3>
          <blockquote class="actual-answer">
            {{
              stageAnswer?.skipped
                ? "已跳过，未完成本阶段"
                : stageAnswer?.text || "尚未提交"
            }}
          </blockquote>
          <details v-if="stageAnswer?.rawTranscript">
            <summary>查看语音原始转写</summary>
            <blockquote class="actual-answer">
              {{ stageAnswer.rawTranscript }}
            </blockquote>
          </details>
          <AnswerEvidence
            :feedback="row.feedback[String(stage)]"
            :pending="
              stageAnswer?.text ? '回答已提交，反馈待生成' : '提交后生成反馈'
            "
          />
        </section>
      </SlidingTabs>
    </section>
  </AppShell>
</template>
<style scoped src="./result.css"></style>
