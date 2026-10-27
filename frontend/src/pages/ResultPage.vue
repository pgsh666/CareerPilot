<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import UiIcon from "../ui/UiIcon.vue";
import {
  clone,
  fixtures,
  notify,
  startSession,
  state,
  uid,
} from "../core/state";
import { historyRecords } from "../core/history";
import { isPreviewMode } from "../core/runtime";
import ServiceResult from "./ServiceResult.vue";
const route = useRoute(),
  router = useRouter();
const kind = computed(() =>
    route.meta.kind === "practice" ? "practice" : "report",
  ),
  id = computed(() => String(route.params.id));
const local = computed(() => state.runs.find((r) => r.id === id.value));
const record = computed(() =>
  historyRecords.value.find((r) => r.id === id.value),
);
const reportNumber = computed(() =>
  isPreviewMode && /^interview-[1-7]$/.test(id.value)
    ? Number(id.value.split("-")[1])
    : 0,
);
type PracticeFixture =
  (typeof fixtures.results.practices)[keyof typeof fixtures.results.practices];
const practiceSeed = computed<PracticeFixture | undefined>(() =>
  isPreviewMode
    ? (fixtures.results.practices as Record<string, PracticeFixture>)[id.value]
    : undefined,
);
const valid = computed(
  () =>
    !!local.value ||
    (kind.value === "report" ? !!reportNumber.value : !!practiceSeed.value),
);
const partial = computed(() => reportNumber.value === 7);
const answered = computed(() =>
  local.value
    ? new Set(
        local.value.session.answers
          .filter((a) => !a.skipped && a.text)
          .map((a) => a.main),
      ).size
    : partial.value
      ? 2
      : 5,
);
const total = computed(() => local.value?.session.count || 5);
const sourceId = computed(
  () => local.value?.source || `interview-${practiceSeed.value?.source || 6}`,
);
const seedQuestions = fixtures.results.questions;
const taskId = computed(
  () => local.value?.session.task || practiceSeed.value?.task || "idempotency",
);
const seedQuestion = computed(
  () => seedQuestions.find((q) => q.id === taskId.value) || seedQuestions[0]!,
);
const done = computed(() =>
  local.value
    ? !!local.value.session.originalText && !!local.value.session.variantText
    : !!practiceSeed.value?.done,
);
const tab = ref("overview"),
  questionIndex = ref(0);
watch(
  () => [
    route.params.id,
    route.meta.kind,
    route.query.tab,
    route.query.question,
  ],
  () => {
    tab.value = String(
      route.query.tab || (kind.value === "practice" ? "original" : "overview"),
    );
    const i = seedQuestions.findIndex((q) => q.id === route.query.question);
    questionIndex.value = i >= 0 ? i : 0;
  },
  { immediate: true },
);
const tabs = computed(() =>
  kind.value === "report"
    ? [
        { id: "overview", name: "报告概览" },
        { id: "questions", name: "逐题回顾" },
        { id: "dimensions", name: "维度评分" },
      ]
    : [
        { id: "original", name: "原题对照" },
        { id: "variant", name: "变式验证" },
      ],
);
const reviewQuestions = computed(() =>
  local.value
    ? Array.from({ length: total.value }, (_, i) => {
        const entries = local.value!.session.answers.filter(
          (a) => a.main === i + 1,
        );
        const main = entries.find((a) => a.follow === 0);
        return {
          id: String(i),
          title: `主问题 ${i + 1}`,
          question: main?.question || fixtures.interview.questions[i] || "",
          answer: main?.text || "",
          followups: entries
            .filter((a) => a.follow > 0)
            .map((a) => [a.question, a.text]),
          strength: "",
          action: "",
          answered: !!main?.text && !main.skipped,
        };
      })
    : seedQuestions.map((q, i) => ({ ...q, answered: i < answered.value })),
);
const current = computed(
  () => reviewQuestions.value[questionIndex.value] || reviewQuestions.value[0],
);
const priorities = computed(() =>
  local.value ? [] : seedQuestions.slice(0, partial.value ? 2 : 3),
);
const score = computed(() => record.value?.score ?? null);
const dimensions = computed(() => {
  const names = [
    "回答相关性",
    "逻辑表达",
    "回答依据与职责说明",
    "接口与数据设计",
    "可靠性与异常处理",
    "性能与技术取舍",
  ];
  let values: (number | null)[] = local.value
    ? names.map(() => null)
    : partial.value
      ? [72, 67, 65, 68, 62, null]
      : [82, 81, 85, 83, 80, 81].map((v) => v + (score.value || 82) - 82);
  if (!local.value && !partial.value && reportNumber.value) {
    values[1] = [64, 67, 70, 73, 74, 81][reportNumber.value - 1]!;
    values[3] = [68, 64, 73, 76, 80, 83][reportNumber.value - 1]!;
  }
  return names.map((name, i) => ({
    name,
    value: values[i],
    basis:
      i === 0 || i === 1
        ? `第 1–${answered.value} 题`
        : i === 2
          ? partial.value
            ? "第 1、2 题"
            : "第 1、4 题"
          : `第 ${i - 2} 题`,
  }));
});
const rewrite = computed(
  () => local.value?.session.originalText || practiceSeed.value?.rewrite || "",
);
const originalDone = computed(() => !!rewrite.value);
const variantAnswer = computed(
  () =>
    local.value?.session.variantText ||
    (practiceSeed.value && "variantAnswer" in practiceSeed.value
      ? practiceSeed.value.variantAnswer
      : "") ||
    "",
);
const variantQuestion = computed(
  () =>
    practiceSeed.value?.variant ||
    fixtures.interview.tasks.find((t) => t.id === taskId.value)?.variant ||
    "",
);
const originalAnswer = computed(() => {
  const source = state.runs.find((r) => r.id === sourceId.value);
  if (source)
    return (
      source.session.answers.find(
        (a) => a.question === seedQuestion.value.question,
      )?.text || "来源记录中没有这道题的回答。"
    );
  return /^interview-[1-7]$/.test(sourceId.value)
    ? seedQuestion.value.answer
    : "来源记录暂无回答。";
});
const historyLink = computed(() => ({
  path: "/history",
  query: {
    tab: kind.value === "practice" ? "practice" : "interview",
    ...(record.value
      ? { role: record.value.role, target: record.value.target }
      : {}),
  },
}));
function practiceLink(task: string) {
  return {
    path: "/interview",
    query: { tab: "tasks", task, source: id.value },
  };
}
function review(index: number) {
  questionIndex.value = index;
  tab.value = "questions";
}
function resumePractice() {
  if (!isPreviewMode) {
    notify("复练服务尚未接入，请稍后重试");
    return;
  }
  if (local.value) {
    state.session = clone(local.value.session);
    state.session.finished = false;
    state.session.feedback = false;
    state.session.stage = originalDone.value ? "variant" : "original";
    state.session.main = originalDone.value ? 2 : 1;
    state.session.draft = "";
  } else {
    const j = state.jobs.find((j) => j.status === "confirmed"),
      r = state.resumes.find((r) => r.status === "confirmed");
    if (!j || !r) {
      notify("请先确认岗位 JD 和简历");
      router.push("/interview?tab=prepare");
      return;
    }
    const s = startSession(j, r, 2, "practice", taskId.value, sourceId.value);
    if (!s) return;
    s.id = uid("practice");
    s.originalText = rewrite.value;
    s.stage = "variant";
    s.main = 2;
    s.answers.push({
      question: seedQuestion.value.question,
      text: rewrite.value,
      main: 1,
      follow: 0,
      skipped: false,
    });
  }
  router.push(
    `/interview/room?stage=${originalDone.value ? "variant" : "original"}`,
  );
}
</script>
<template>
  <ServiceResult v-if="!isPreviewMode" />
  <AppShell v-else :title="kind === 'report' ? '面试报告' : '复练详情'"
    ><template #actions
      ><span v-if="!local && valid" class="example-label">示例数据</span
      ><RouterLink class="ui-button" :to="historyLink"
        ><UiIcon name="back" :size="17" />返回历史</RouterLink
      ></template
    >
    <section v-if="!valid" class="ui-panel empty-state">
      <h2>该记录暂无详情</h2>
      <RouterLink class="ui-button" to="/history">返回历史</RouterLink>
    </section>
    <section v-else class="ui-panel result-panel">
      <header class="result-meta">
        <div class="result-meta-copy">
          <div class="result-meta-title">
            <h2>
              {{
                kind === "report"
                  ? local?.title || `后端开发 · 第 ${reportNumber} 次模拟面试`
                  : local?.title || seedQuestion.title
              }}
            </h2>
            <span
              class="ui-badge"
              :class="
                kind === 'practice'
                  ? done
                    ? 'green'
                    : ''
                  : partial || local?.status === 'ended'
                    ? 'gray'
                    : 'green'
              "
              >{{
                kind === "practice"
                  ? done
                    ? "已完成"
                    : "进行中"
                  : partial || local?.status === "ended"
                    ? "提前结束"
                    : "已完成"
              }}</span
            >
          </div>
          <p v-if="kind === 'report'">
            {{ record?.date }} {{ record?.time }}<i />{{
              local
                ? `${local.session.job.title} · JD v${local.session.job.version}`
                : "校园知识助手 · JD v1"
            }}<i />{{ local?.session.resume.title || "后端开发 · 校招版" }}
          </p>
          <p v-else>
            {{ record?.date }} {{ record?.time }}<i />{{ seedQuestion.dimension
            }}<i /><RouterLink
              :to="{
                path: `/reports/${sourceId}`,
                query: { tab: 'questions', question: taskId },
              }"
              >来源：{{
                sourceId.startsWith("interview-")
                  ? `第 ${sourceId.split("-")[1]} 次模拟面试`
                  : "模拟面试"
              }}<UiIcon name="next" :size="13"
            /></RouterLink>
          </p>
        </div>
        <template v-if="kind === 'report'"
          ><div class="result-metric">
            <span>已答主问题</span
            ><strong
              >{{ answered }}<small> / {{ total }}</small></strong
            >
          </div>
          <div class="result-metric">
            <span>覆盖率</span
            ><strong>{{ record?.coverage }}<small>%</small></strong>
          </div>
          <div class="result-metric score">
            <span>综合分</span
            ><strong
              >{{ score ?? "—"
              }}<small v-if="score !== null"> / 100</small></strong
            >
          </div></template
        >
        <div v-else class="result-stages">
          <span :class="originalDone ? 'done' : 'pending'"
            ><UiIcon v-if="originalDone" name="check" :size="16" /><b v-else
              >1</b
            >原题重答</span
          ><i /><span :class="done ? 'done' : 'pending'"
            ><UiIcon v-if="done" name="check" :size="16" /><b v-else>2</b
            >变式验证</span
          >
        </div>
      </header>
      <div
        class="ui-tabs result-tabs"
        role="tablist"
        :aria-label="kind === 'report' ? '面试报告内容' : '复练详情内容'"
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
      <SlidingTabs :active="tab" :order="tabs.map((item) => item.id)">
        <section
          v-if="kind === 'report' && tab === 'overview'"
          class="result-overview ui-scroll"
        >
          <div v-if="partial" class="coverage-alert">
            覆盖不足，暂不生成综合分。仅依据已提交的 2 道主问题给出反馈。
          </div>
          <div class="section-heading">
            <h3>优先改进</h3>
            <span class="muted-copy">{{
              local ? "反馈待生成" : `${priorities.length} 项 · 按本次回答整理`
            }}</span>
          </div>
          <div v-if="local" class="empty-state">
            已保留本次回答，报告反馈待后端生成。
          </div>
          <div v-else class="priority-grid" :class="{ partial }">
            <article
              v-for="(q, i) in priorities"
              :key="q.id"
              class="priority-card"
            >
              <div class="priority-heading">
                <span class="priority-number">0{{ i + 1 }}</span
                ><span>{{ q.dimension }}</span
                ><button class="text-button" @click="review(i)">
                  第 {{ i + 1 }} 题<UiIcon name="next" :size="13" />
                </button>
              </div>
              <h4>{{ q.gap }}</h4>
              <blockquote>
                <UiIcon name="quote" :size="18" /><span>{{ q.evidence }}</span>
              </blockquote>
              <p>{{ q.action }}</p>
              <RouterLink class="text-button" :to="practiceLink(q.id)"
                >去复练<UiIcon name="arrow" :size="16"
              /></RouterLink>
            </article>
          </div>
        </section>
        <section
          v-else-if="kind === 'report' && tab === 'questions'"
          class="result-review"
        >
          <nav class="question-list" aria-label="主问题列表">
            <button
              v-for="(q, i) in reviewQuestions"
              :key="q.id"
              :class="{ active: questionIndex === i }"
              @click="questionIndex = i"
            >
              <span>{{ String(i + 1).padStart(2, "0") }}</span>
              <div>
                <strong>{{ q.title }}</strong
                ><small>{{
                  q.answered
                    ? q.followups.length
                      ? `${q.followups.length} 次追问`
                      : "无追问"
                    : "未作答"
                }}</small>
              </div>
              <UiIcon name="next" :size="14" />
            </button>
          </nav>
          <div v-if="current" class="review-body ui-scroll">
            <div class="review-question">
              <span>主问题 {{ questionIndex + 1 }}</span>
              <h3>{{ current.question }}</h3>
            </div>
            <template v-if="current.answered"
              ><div class="answer-label">你的回答</div>
              <blockquote class="original-answer">
                {{ current.answer }}
              </blockquote>
              <details v-if="current.followups.length" class="followups">
                <summary>
                  查看 {{ current.followups.length }} 次追问与回答
                </summary>
                <div v-for="(pair, i) in current.followups" :key="i">
                  <span>追问 {{ i + 1 }}</span>
                  <p>{{ pair[0] }}</p>
                  <blockquote>{{ pair[1] || "未作答" }}</blockquote>
                </div>
              </details>
              <div class="question-feedback">
                <section>
                  <h4>已体现</h4>
                  <p>{{ current.strength || "反馈待生成" }}</p>
                </section>
                <section>
                  <h4>待补充</h4>
                  <p>{{ current.action || "反馈待生成" }}</p>
                </section>
              </div>
              <RouterLink
                v-if="!local && questionIndex < 3"
                class="ui-button primary review-practice"
                :to="practiceLink(current.id)"
                >复练这道题<UiIcon name="arrow" :size="16" /></RouterLink
            ></template>
            <div v-else class="empty-state">本题未作答，不生成评价。</div>
          </div>
        </section>
        <section
          v-else-if="kind === 'report'"
          class="result-dimensions ui-scroll"
        >
          <div class="section-heading">
            <h3>维度表现</h3>
            <span class="muted-copy">{{
              local ? "评分待生成" : "评分 v1 · 参考分 / 100"
            }}</span>
          </div>
          <div class="dimension-layout">
            <div class="dimension-grid">
              <article v-for="d in dimensions" :key="d.name">
                <div>
                  <h4>{{ d.name }}</h4>
                  <strong>{{ d.value ?? "N/A" }}</strong>
                </div>
                <div class="dimension-bar">
                  <i
                    v-if="d.value !== null"
                    :style="{ width: `${d.value}%` }"
                  />
                </div>
                <span>{{
                  local
                    ? "等待评分依据"
                    : d.value === null
                      ? "未覆盖，无作答依据"
                      : `依据：${d.basis}`
                }}</span>
              </article>
            </div>
            <aside class="score-rules">
              <h4>本次评分依据</h4>
              <dl>
                <div>
                  <dt>已答主问题</dt>
                  <dd>{{ answered }} / {{ total }}</dd>
                </div>
                <div>
                  <dt>覆盖率</dt>
                  <dd>{{ record?.coverage }}%</dd>
                </div>
                <div>
                  <dt>岗位维度覆盖</dt>
                  <dd>{{ local ? "—" : partial ? "2 / 3" : "3 / 3" }}</dd>
                </div>
              </dl>
              <p>
                {{
                  local
                    ? "反馈与评分待后端生成。"
                    : partial
                      ? "未达到综合分生成条件，保留已覆盖维度的参考分。"
                      : "综合分基于本次已覆盖维度的作答依据生成。"
                }}
              </p>
              <small
                >未覆盖维度记为 N/A；综合分需至少 3
                道已答主问题、岗位维度全部有依据，且覆盖率不低于 80%。</small
              >
            </aside>
          </div>
        </section>
        <section
          v-else-if="tab === 'original'"
          class="practice-detail ui-scroll"
        >
          <div class="review-question">
            <span>原题</span>
            <h3>{{ seedQuestion.question }}</h3>
          </div>
          <div class="answer-comparison">
            <article>
              <header>
                <h4>原始回答</h4>
                <span>来源面试</span>
              </header>
              <p>{{ originalAnswer }}</p>
              <div class="original-gap">
                <span>当时缺少</span>{{ seedQuestion.action }}
              </div>
            </article>
            <article class="after">
              <header>
                <h4>本次重答</h4>
                <span
                  ><UiIcon v-if="originalDone" name="check" :size="14" />{{
                    originalDone ? "已提交" : "未作答"
                  }}</span
                >
              </header>
              <p>{{ rewrite || "本题未作答，不生成评价。" }}</p>
            </article>
          </div>
          <div class="practice-feedback">
            <section>
              <h4><i class="green" />已补充</h4>
              <p>{{ local ? "反馈待生成" : practiceSeed?.added }}</p>
            </section>
            <section>
              <h4><i />仍需补充</h4>
              <p>{{ local ? "反馈待生成" : practiceSeed?.remaining }}</p>
            </section>
          </div>
          <div class="practice-detail-bottom">
            <span>{{
              done
                ? "原题与变式均已完成"
                : originalDone
                  ? "已完成原题重答，变式尚未提交"
                  : "原题与变式尚未完成"
            }}</span
            ><button
              class="ui-button primary"
              @click="done ? (tab = 'variant') : resumePractice()"
            >
              {{
                done
                  ? "查看变式验证"
                  : originalDone
                    ? "继续变式练习"
                    : "继续原题练习"
              }}<UiIcon name="arrow" :size="17" />
            </button>
          </div>
        </section>
        <section v-else class="variant-detail ui-scroll">
          <div class="review-question">
            <span>变式问题</span>
            <h3>{{ variantQuestion }}</h3>
          </div>
          <div v-if="done" class="variant-columns">
            <section>
              <div class="answer-label">你的回答</div>
              <blockquote class="original-answer">
                {{ variantAnswer }}
              </blockquote>
              <div class="variant-evidence">
                <span>作答依据</span>
                <p>
                  {{
                    local
                      ? "待后端分析"
                      : practiceSeed && "variantEvidence" in practiceSeed
                        ? practiceSeed.variantEvidence
                        : ""
                  }}
                </p>
              </div>
            </section>
            <aside class="variant-feedback">
              <h3>变式反馈</h3>
              <section>
                <h4><i class="green" />已体现</h4>
                <p>
                  {{
                    local
                      ? "反馈待生成"
                      : practiceSeed && "variantFeedback" in practiceSeed
                        ? practiceSeed.variantFeedback
                        : ""
                  }}
                </p>
              </section>
              <section>
                <h4><i />仍需补充</h4>
                <p>
                  {{
                    local
                      ? "反馈待生成"
                      : practiceSeed && "variantRemaining" in practiceSeed
                        ? practiceSeed.variantRemaining
                        : ""
                  }}
                </p>
              </section>
            </aside>
          </div>
          <div v-else class="empty-state">
            <span class="pending-circle">2</span>
            <h3>变式尚未作答</h3>
            <button class="ui-button primary" @click="resumePractice">
              继续变式练习<UiIcon name="arrow" :size="17" />
            </button>
          </div>
        </section>
      </SlidingTabs></section
  ></AppShell>
</template>
<style scoped>
.result-meta {
  min-height: calc(var(--workspace-height) * 0.18382353);
  padding: 18px 28px;
  display: flex;
  gap: 28px;
  align-items: center;
  border-bottom: 1px solid #edf0f6;
  flex: none;
}
.result-meta-copy {
  flex: 1;
  min-width: 0;
}
.result-meta-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.result-meta-title h2 {
  font-size: var(--ui-title);
  font-weight: 600;
  line-height: 1.6;
}
.result-meta-copy p {
  font-size: 0.8em;
  color: #8b98ad;
  margin-top: 9px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.result-meta-copy p > i {
  height: 11px;
  width: 1px;
  background: #dfe5ef;
}
.result-meta-copy p > a {
  color: #6a83b5;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.result-metric {
  min-width: 80px;
  text-align: center;
  flex: none;
}
.result-metric > span {
  display: block;
  color: #8b98ad;
  font-size: 0.8em;
  margin-bottom: 8px;
}
.result-metric strong {
  font-size: clamp(24px, 2vw, 36px);
  line-height: 1.2;
}
.result-metric small {
  font-size: 12px;
  color: #9ba8bc;
  font-weight: 400;
}
.result-metric.score {
  border-left: 1px solid #e2e8f1;
  padding-left: 26px;
  color: #5b80e5;
}
.result-tabs {
  height: clamp(44px, 5.444444svh, 65px);
  gap: 34px;
  font-size: 0.95em;
}
.result-overview,
.result-dimensions,
.practice-detail,
.variant-detail {
  padding: 22px 28px;
  flex: 1;
  min-height: 0;
}
.section-heading > h3 {
  font-size: 1.06em;
  font-weight: 600;
}
.priority-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin-top: 18px;
  min-height: calc(var(--workspace-height) * 0.5);
}
.priority-grid.partial {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  min-height: calc(var(--workspace-height) * 0.39);
}
.priority-card {
  border: 1px solid #e3e9f3;
  background: #fbfcff;
  border-radius: 14px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
}
.priority-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #7b8ead;
  font-size: 0.76em;
  white-space: nowrap;
}
.priority-heading > .text-button {
  margin-left: auto;
  font-size: inherit;
}
.priority-number {
  font-size: 16px;
  font-weight: 600;
  color: #6f8fd8;
}
.priority-card h4 {
  font-size: 1.05em;
  line-height: 1.7;
  margin-top: 16px;
  font-weight: 600;
}
.priority-card blockquote {
  display: flex;
  gap: 8px;
  margin: 14px 0;
  padding: 12px;
  background: #f0f4fc;
  color: #7a8ca8;
  border-radius: 8px;
  font-size: 0.86em;
  line-height: 1.9;
}
.priority-card blockquote svg {
  flex: none;
  color: #9bb1da;
  margin-top: 4px;
}
.priority-card > p {
  font-size: 0.88em;
  color: #71809a;
  line-height: 1.9;
}
.priority-card > .text-button {
  margin-top: auto;
  align-self: flex-start;
  padding-top: 16px;
  font-size: 0.9em;
}
.coverage-alert {
  background: #fff7eb;
  color: #a68451;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.87em;
  margin-bottom: 16px;
}
.result-review {
  display: grid;
  grid-template-columns: 25% 75%;
  flex: 1;
  min-height: 0;
}
.question-list {
  border-right: 1px solid #e6ebf4;
  padding: 12px;
  overflow-y: auto;
}
.question-list button {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 0;
  background: white;
  color: #7c8da7;
  text-align: left;
  width: 100%;
  border-radius: 10px;
  padding: 15px 12px;
  font: inherit;
}
.question-list button.active {
  background: #f0f4ff;
  color: #5b80e5;
}
.question-list button > span {
  font-size: 0.88em;
  font-weight: 600;
}
.question-list button > div {
  flex: 1;
  min-width: 0;
}
.question-list strong {
  display: block;
  font-size: 0.93em;
  font-weight: 500;
}
.question-list small {
  display: block;
  font-size: 0.76em;
  color: #a0aabc;
  margin-top: 5px;
}
.review-body {
  padding: 22px 28px;
}
.review-question {
  margin-bottom: 18px;
}
.review-question > span {
  font-size: 0.8em;
  color: #8b98ad;
}
.review-question h3 {
  font-size: 1.1em;
  font-weight: 500;
  line-height: 1.8;
  margin-top: 7px;
}
.answer-label {
  color: #8292ad;
  font-size: 0.86em;
  margin-bottom: 10px;
}
.original-answer {
  margin: 0;
  background: #f6f8fd;
  border: 1px solid #e3e9f3;
  border-radius: 10px;
  padding: 16px 18px;
  font-size: 0.93em;
  line-height: 1.9;
  color: #596e8e;
  white-space: pre-wrap;
}
.followups {
  margin-top: 15px;
  border: 1px solid #e5eaf3;
  border-radius: 10px;
  padding: 13px 16px;
  color: #7a8ca8;
  font-size: 0.88em;
}
.followups summary {
  cursor: pointer;
}
.followups > div {
  padding-top: 16px;
}
.followups > div > span {
  font-size: 0.85em;
  color: #9ca8ba;
}
.followups p {
  margin-top: 5px;
  line-height: 1.7;
  color: #667895;
}
.followups blockquote {
  padding: 10px 13px;
  background: #f7f9fd;
  border-radius: 6px;
  margin: 8px 0 0;
  line-height: 1.8;
}
.question-feedback,
.practice-feedback {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 18px;
}
.question-feedback h4,
.practice-feedback h4,
.variant-feedback h4 {
  font-size: 0.87em;
  color: #7185a2;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.question-feedback p,
.practice-feedback p,
.variant-feedback p {
  font-size: 0.88em;
  color: #8292ad;
  line-height: 1.9;
}
.review-practice {
  float: right;
  margin-top: 18px;
}
.dimension-layout {
  display: grid;
  grid-template-columns: minmax(0, 2.7fr) minmax(0, 1fr);
  gap: 24px;
  margin-top: 18px;
}
.dimension-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.dimension-grid article {
  border: 1px solid #e3e9f3;
  border-radius: 12px;
  padding: 16px 18px;
}
.dimension-grid article > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.dimension-grid h4 {
  font-size: 0.93em;
  font-weight: 500;
}
.dimension-grid strong {
  font-size: 1.35em;
  color: #607fbf;
}
.dimension-bar {
  height: 5px;
  background: #f0f3f9;
  border-radius: 4px;
  margin: 13px 0 10px;
}
.dimension-bar i {
  display: block;
  height: 100%;
  background: #8eabea;
  border-radius: 4px;
}
.dimension-grid article > span {
  font-size: 0.78em;
  color: #98a5b8;
}
.score-rules {
  border: 1px solid #e4eaf4;
  border-radius: 12px;
  background: #f8faff;
  padding: 20px;
}
.score-rules h4 {
  font-size: 0.95em;
  font-weight: 500;
}
.score-rules dl > div {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
  font-size: 0.86em;
  gap: 16px;
}
.score-rules dt {
  color: #8292ad;
}
.score-rules p {
  font-size: 0.84em;
  color: #8292ad;
  line-height: 1.9;
  border-top: 1px solid #e2e8f2;
  padding-top: 18px;
  margin-top: 18px;
}
.score-rules > small {
  display: block;
  font-size: 0.75em;
  line-height: 1.9;
  color: #a0adbf;
  margin-top: 15px;
}
.result-stages {
  display: flex;
  align-items: center;
  gap: 14px;
  white-space: nowrap;
  font-size: 0.88em;
  color: #9aa8bb;
}
.result-stages > span {
  display: flex;
  align-items: center;
  gap: 6px;
}
.result-stages .done {
  color: #6a9c86;
}
.result-stages > i {
  width: 32px;
  height: 1px;
  background: #dfe6ef;
}
.result-stages b {
  display: grid;
  place-items: center;
  border: 1px solid #dce3ee;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  font-size: 11px;
}
.answer-comparison {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
.answer-comparison article {
  border: 1px solid #e4eaf4;
  border-radius: 12px;
  overflow: hidden;
}
.answer-comparison header {
  height: 42px;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #edf0f6;
  font-size: 0.88em;
}
.answer-comparison header h4 {
  font-weight: 500;
}
.answer-comparison header span {
  font-size: 0.85em;
  color: #9ba8bb;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.answer-comparison article.after {
  border-color: #d8e8e0;
}
.answer-comparison article.after header {
  background: #f5faf7;
  color: #608e79;
}
.answer-comparison p {
  padding: 16px 18px;
  line-height: 1.9;
  color: #71809a;
  font-size: 0.9em;
  white-space: pre-wrap;
}
.original-gap {
  border-top: 1px solid #edf0f6;
  margin: 0 18px;
  padding: 12px 0;
  font-size: 0.82em;
  line-height: 1.8;
  color: #8e9bb0;
}
.original-gap span {
  display: block;
  color: #b18b5c;
  margin-bottom: 5px;
}
.practice-feedback i,
.variant-feedback i {
  width: 6px;
  height: 6px;
  background: #c6a169;
  border-radius: 50%;
  display: inline-block;
}
.practice-feedback i.green,
.variant-feedback i.green {
  background: #7db19c;
}
.practice-detail-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  gap: 18px;
}
.practice-detail-bottom > span {
  font-size: 0.8em;
  color: #9ba8bb;
}
.variant-columns {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 28px;
}
.variant-evidence {
  border-left: 2px solid #b7c9ec;
  padding: 12px 16px;
  background: #f7f9fd;
  margin-top: 16px;
  font-size: 0.85em;
  color: #91a2bc;
}
.variant-evidence p {
  margin-top: 8px;
  line-height: 1.8;
  color: #7c90b0;
}
.variant-feedback {
  border: 1px solid #e3e9f3;
  border-radius: 12px;
  padding: 20px;
}
.variant-feedback h3 {
  font-size: 1em;
  font-weight: 500;
  margin-bottom: 20px;
}
.variant-feedback section + section {
  margin-top: 20px;
}
.pending-circle {
  height: 44px;
  width: 44px;
  border: 1px solid #dfe6f2;
  background: #f7f9fe;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #9baccc;
  font-size: 20px;
}
@media (max-width: 1200px) {
  .result-meta {
    padding: 16px 22px;
    gap: 18px;
  }
  .result-meta-title {
    gap: 9px;
  }
  .result-meta-title h2 {
    font-size: 16px;
  }
  .result-meta-copy p {
    gap: 7px;
    font-size: 11px;
  }
  .result-metric {
    min-width: 65px;
  }
  .result-metric.score {
    padding-left: 18px;
  }
  .priority-grid {
    gap: 14px;
  }
  .priority-card {
    padding: 14px;
  }
  .priority-heading {
    gap: 5px;
    font-size: 10px;
  }
  .priority-heading .text-button {
    font-size: 10px;
  }
  .result-overview,
  .result-dimensions,
  .practice-detail,
  .variant-detail {
    padding: 18px 22px;
  }
  .priority-card h4 {
    font-size: 13px;
  }
  .priority-card blockquote {
    font-size: 12px;
    padding: 10px;
    gap: 5px;
  }
  .priority-card > p {
    font-size: 12px;
  }
  .dimension-layout {
    gap: 18px;
    grid-template-columns: 2.4fr 1fr;
  }
  .dimension-grid {
    gap: 12px;
  }
  .dimension-grid article {
    padding: 12px 14px;
  }
  .score-rules {
    padding: 16px;
  }
  .question-list button {
    gap: 8px;
    padding: 14px 8px;
  }
  .result-stages {
    gap: 8px;
    font-size: 11px;
  }
  .result-stages > i {
    width: 20px;
  }
}
</style>
