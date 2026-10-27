<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import UiIcon from "../ui/UiIcon.vue";
import ScoreExplanation from "../ui/ScoreExplanation.vue";
import Pagination from "../ui/Pagination.vue";
import { api, errorMessage } from "../core/api";
import { state } from "../core/state";
import { statusLabel, type Training } from "../core/training";
const route = useRoute();
const role = ref(String(route.query.role || "all")),
  target = ref(String(route.query.target || "all")),
  days = ref(30),
  mode = ref(route.query.tab === "practice" ? "practice" : "interview"),
  status = ref("all"),
  page = ref(1);
const targets = ref<
  {
    id: string;
    role: string;
    name: string;
    version: number;
    direction: string;
  }[]
>([]);
const choices = computed(() =>
  targets.value.filter((t) => role.value === "all" || t.role === role.value),
);
const rows = ref<Training[]>([]),
  total = ref(0),
  counts = ref({ interview: 0, practice: 0 }),
  loading = ref(false),
  error = ref("");
interface Trend {
  version: string;
  versions: { id: string; samples: number }[];
  sampleCount: number;
  dimensions: { id: string; name: string }[];
  points: { id: string; at: string; values: number[]; coverage: number }[];
  group: { title: string; direction: string; jdVersion: number } | null;
}
const trend = ref<Trend | null>(null),
  trendError = ref("");
let trendGeneration = 0;
async function loadTrend() {
  const v = ++trendGeneration;
  try {
    const p = new URLSearchParams({
      role: role.value,
      target: target.value,
      days: String(days.value),
      scoring_version: "auto",
    });
    const result = await api<Trend>(`/training/trend?${p}`);
    if (alive && v === trendGeneration && owner === state.account.id) {
      trend.value = result;
      trendError.value = "";
    }
  } catch (e) {
    if (alive && v === trendGeneration && owner === state.account.id) {
      trend.value = null;
      trendError.value = errorMessage(e);
    }
  }
}
const px = (i: number) =>
  (trend.value?.points.length || 0) < 2
    ? 390
    : 50 + (i * 680) / (trend.value!.points.length - 1);
const py = (value: number) => 175 - value * 1.4;
const line = (d: number) =>
  trend.value?.points.map((p, i) => `${px(i)},${py(p.values[d]!)}`).join(" ");
const owner = state.account.id;
let version = 0,
  alive = true;
function params(type: string) {
  return new URLSearchParams({
    mode: type,
    role: role.value,
    target: target.value,
    days: String(days.value),
    status: status.value,
    offset: String((page.value - 1) * 3),
    limit: "3",
  });
}
async function load() {
  const v = ++version;
  loading.value = true;
  try {
    const filters = params(mode.value);
    const countParams = (kind: string) => {
      const p = params(kind);
      p.set("status", "all");
      p.set("offset", "0");
      p.set("limit", "1");
      return p;
    };
    const [list, interviews, practices] = await Promise.all([
      api<{ items: Training[]; total: number }>(`/training/history?${filters}`),
      api<{ total: number }>(`/training/history?${countParams("interview")}`),
      api<{ total: number }>(`/training/history?${countParams("practice")}`),
    ]);
    if (!alive || v !== version || owner !== state.account.id) return;
    rows.value = list.items;
    total.value = list.total;
    counts.value = { interview: interviews.total, practice: practices.total };
    page.value = Math.min(page.value, Math.max(1, Math.ceil(list.total / 3)));
    error.value = "";
  } catch (e) {
    if (alive && v === version) {
      error.value = errorMessage(e);
      rows.value = [];
    }
  } finally {
    if (v === version) loading.value = false;
  }
}
watch([role, target, days, status, mode], () => {
  page.value = 1;
});
watch(role, () => {
  target.value = "all";
});
watch(mode, () => {
  status.value = "all";
});
watch([role, target, days, status, mode, page], () => void load(), {
  immediate: true,
});
watch([role, target, days], () => void loadTrend(), { immediate: true });
void api<{ targets: typeof targets.value }>("/training/filters")
  .then((r) => {
    if (alive && owner === state.account.id) targets.value = r.targets;
  })
  .catch((e) => {
    if (alive) error.value = errorMessage(e);
  });
onBeforeUnmount(() => {
  alive = false;
  version++;
});
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { hour12: false });
function stageDone(row: Training, main: number) {
  const ids = new Set(
    row.questions.filter((q) => q.main === main).map((q) => q.id),
  );
  return row.answers.some(
    (a) => ids.has(a.question_id) && a.text && !a.skipped,
  );
}
</script>
<template>
  <AppShell title="历史记录"
    ><div class="history-layout">
      <section class="ui-panel trend-panel">
        <div class="trend-heading">
          <div class="trend-title">
            <h2>练习表现趋势</h2>
            <ScoreExplanation :trend="trend" />
          </div>
          <div class="history-filters">
            <label
              >岗位<select v-model="role" aria-label="岗位">
                <option value="all">全部岗位</option>
                <option
                  v-for="r in [
                    '后端开发',
                    '前端开发',
                    '软件测试',
                    'AI 产品经理',
                    'AI 应用开发',
                  ]"
                  :key="r"
                >
                  {{ r }}
                </option>
              </select></label
            ><label
              >JD 版本<select v-model="target" aria-label="JD版本">
                <option value="all">全部版本</option>
                <option v-for="t in choices" :key="t.id" :value="t.id">
                  {{ t.name }} · {{ t.direction }} · v{{ t.version }}
                </option>
              </select></label
            ><label
              >时间<select v-model="days" aria-label="时间范围">
                <option :value="30">最近 30 天</option>
                <option :value="7">最近 7 天</option>
                <option :value="0">全部时间</option>
              </select></label
            >
          </div>
        </div>
        <div class="trend-chart">
          <svg
            v-if="trend?.points.length"
            viewBox="0 0 780 205"
            role="img"
            aria-label="专项代表维度与逻辑表达趋势，纵轴0到100分"
          >
            <g v-for="n in [0, 25, 50, 75, 100]" :key="n">
              <line x1="50" x2="730" :y1="py(n)" :y2="py(n)" stroke="#e4eaf4" />
              <text x="12" :y="py(n) + 4" fill="#667895" font-size="12">
                {{ n }}
              </text>
            </g>
            <g
              v-for="(dim, d) in trend.dimensions"
              :key="dim.id"
              :stroke="d === 0 ? '#587fe5' : '#3aa88b'"
              :fill="d === 0 ? '#587fe5' : '#3aa88b'"
            >
              <polyline
                v-if="trend.points.length > 1"
                :points="line(d)"
                fill="none"
                stroke-width="2"
              />
              <circle
                v-for="(p, i) in trend.points"
                :key="p.id"
                :cx="px(i)"
                :cy="py(p.values[d]!)"
                r="4"
              >
                <title>
                  {{ date(p.at) }} · {{ dim.name }} {{ p.values[d] }}分 ·
                  覆盖率{{ p.coverage }}%
                </title>
              </circle>
            </g>
            <text x="50" y="198" font-size="12" fill="#667895">
              {{ date(trend.points[0]!.at) }}
            </text>
            <text
              v-if="trend.points.length > 1"
              x="730"
              y="198"
              text-anchor="end"
              font-size="12"
              fill="#667895"
            >
              {{ date(trend.points[trend.points.length - 1]!.at) }}
            </text>
          </svg>
          <div v-else class="empty-state">
            <UiIcon name="chart" :size="28" /><span>{{
              trendError || "当前条件下暂无完整且有有效评分的可比面试"
            }}</span>
          </div>
        </div>
      </section>
      <section class="ui-panel history-records">
        <div class="history-record-heading">
          <div class="ui-tabs" role="tablist" aria-label="记录类型">
            <button
              v-for="m in ['interview', 'practice'] as const"
              :key="m"
              role="tab"
              :aria-selected="mode === m"
              :class="{ active: mode === m }"
              @click="mode = m"
            >
              {{ m === "interview" ? "模拟面试" : "薄弱项复练"
              }}<span>{{ counts[m] }}</span>
            </button>
          </div>
          <div>
            <select v-model="status" class="ui-select" aria-label="记录状态">
              <option value="all">全部状态</option>
              <option value="completed">已完成</option>
              <option value="active">进行中</option>
              <option value="interrupted">中途退出</option>
              <option value="early_ended">提前结束</option></select
            ><span>训练时间 ↓</span>
          </div>
        </div>
        <div class="data-grid history-grid data-head">
          <span>训练内容</span><span>训练时间</span
          ><span>{{ mode === "interview" ? "综合分" : "原题重答" }}</span
          ><span>{{ mode === "interview" ? "覆盖率" : "变式作答" }}</span
          ><span>状态</span><span class="align-right">操作</span>
        </div>
        <div class="history-rows ui-scroll">
          <div
            v-for="r in rows"
            :key="r.id"
            class="data-grid history-grid data-row"
          >
            <div class="history-row-title">
              <UiIcon
                :name="r.mode === 'interview' ? 'file' : 'refresh'"
                :size="23"
              />
              <div>
                <strong>{{ r.job.title }}</strong
                ><small
                  >{{ r.job.fields.direction }} · JD v{{ r.job.version }} ·
                  {{ Math.floor((r.activeSeconds || 0) / 60) }} 分钟</small
                >
              </div>
            </div>
            <span class="muted-copy">{{ date(r.startedAt) }}</span
            ><template v-if="mode === 'interview'"
              ><strong class="history-score">{{ r.score ?? "—" }}</strong
              ><span>{{
                r.evidenceCoverage == null ? "—" : r.evidenceCoverage + "%"
              }}</span></template
            ><template v-else
              ><span>{{ stageDone(r, 1) ? "已提交" : "未作答" }}</span
              ><span>{{
                stageDone(r, 2) ? "已提交" : "未作答"
              }}</span></template
            ><span
              ><span
                class="ui-badge"
                :class="{
                  green: r.status === 'completed',
                  gray: r.status === 'early_ended',
                }"
                >{{ statusLabel(r.status) }}</span
              ></span
            ><RouterLink
              class="text-button align-right"
              :to="
                ['active', 'interrupted'].includes(r.status)
                  ? `/interview/room?id=${r.id}`
                  : r.mode === 'interview'
                    ? `/reports/${r.id}`
                    : `/practice/${r.id}`
              "
              >{{
                ["active", "interrupted"].includes(r.status)
                  ? "继续训练"
                  : r.mode === "interview"
                    ? "查看报告"
                    : "查看复练"
              }}<UiIcon name="next" :size="14"
            /></RouterLink>
          </div>
          <div v-if="!rows.length" class="empty-state">
            {{
              loading ? "正在加载…" : error ? "记录加载失败" : "暂无相关记录"
            }}
          </div>
        </div>
        <p v-if="error" class="inline-error" role="alert">
          {{ error }}
          <button class="text-button" @click="load">重新加载</button>
        </p>
        <footer class="list-footer">
          <span>共 {{ total }} 条记录</span
          ><Pagination v-model="page" :total="total" :size="3" />
        </footer>
      </section></div
  ></AppShell>
</template>
<style scoped src="./history.css"></style>
