<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import Pagination from "../ui/Pagination.vue";
import UiIcon from "../ui/UiIcon.vue";
import { fixtures, state } from "../core/state";
import { historyRecords, roleNames } from "../core/history";
import { isPreviewMode } from "../core/runtime";
import ServiceHistory from "./ServiceHistory.vue";
const route = useRoute();
const role = ref(String(route.query.role || "backend")),
  target = ref(String(route.query.target || "campus-v1")),
  period = ref(30),
  tab = ref(route.query.tab === "practice" ? "practice" : "interview"),
  status = ref("all"),
  page = ref(1);
const technical = ref(true),
  expression = ref(true);
const targets = computed(() => {
  const seed = isPreviewMode
    ? (fixtures.history.targets as Record<string, string[][]>)[role.value] || []
    : [];
  const local = state.runs
    .filter((r) => r.role === role.value)
    .map((r) => [
      r.target,
      `${r.session.job.title} · JD v${r.session.job.version}`,
    ]);
  return Array.from(
    new Map([...seed, ...local].map((item) => [item[0], item])).values(),
  );
});
watch(role, () => {
  target.value = targets.value[0]?.[0] || "";
  page.value = 1;
});
watch([target, period, status, tab], () => (page.value = 1));
watch(tab, () => (status.value = "all"));
const scoped = computed(() => {
  const threshold = Date.now() - period.value * 86400000;
  return historyRecords.value.filter(
    (r) =>
      r.role === role.value &&
      r.target === target.value &&
      (!period.value ||
        Date.parse(r.date.replaceAll(".", "-") + "T23:59:59") >= threshold),
  );
});
const samples = computed(() => {
  const eligible = scoped.value.filter(
    (r) =>
      r.kind === "interview" &&
      r.comparable &&
      r.status === "completed" &&
      r.coverage >= 80 &&
      r.score !== null,
  );
  const version = [...eligible].sort((a, b) =>
    (b.date + b.time).localeCompare(a.date + a.time),
  )[0]?.version;
  return eligible
    .filter((r) => r.version === version)
    .sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
});
const filtered = computed(() =>
  scoped.value
    .filter(
      (r) =>
        r.kind === tab.value &&
        (status.value === "all" || status.value === r.status),
    )
    .sort((a, b) => (b.date + b.time).localeCompare(a.date + a.time)),
);
const visible = computed(() =>
  filtered.value.slice((page.value - 1) * 3, page.value * 3),
);
const techLabel = computed(() =>
  role.value === "application" ? "场景与系统方案" : "接口与数据设计",
);
const x = (i: number) =>
  samples.value.length === 1
    ? 626
    : 45 + (1161 * i) / (samples.value.length - 1);
const y = (score: number | null) => 99 - (score || 0) * 0.91;
const points = (key: "technical" | "expression") =>
  samples.value.map((s, i) => `${x(i)},${y(s[key])}`).join(" ");
const coverage = computed(() =>
  samples.value.length
    ? `覆盖率 ${Math.min(...samples.value.map((s) => s.coverage))}%–${Math.max(...samples.value.map((s) => s.coverage))}%`
    : "",
);
</script>
<template>
  <ServiceHistory v-if="!isPreviewMode" />
  <AppShell v-else title="历史记录"
    ><div class="history-layout">
      <section class="ui-panel trend-panel">
        <div class="trend-heading">
          <h2>面试表现趋势</h2>
          <div class="history-filters">
            <label
              ><span>岗位</span
              ><select v-model="role" aria-label="岗位">
                <option
                  v-for="(name, key) in roleNames"
                  :key="key"
                  :value="key"
                >
                  {{ name }}
                </option>
              </select></label
            ><label class="target-filter"
              ><span>目标</span
              ><select v-model="target" aria-label="目标岗位与JD版本">
                <option v-for="item in targets" :key="item[0]" :value="item[0]">
                  {{ item[1] }}
                </option>
                <option v-if="!targets.length" value="">暂无目标岗位</option>
              </select></label
            ><label
              ><span>时间</span
              ><select v-model="period" aria-label="时间范围">
                <option :value="30">最近 30 天</option>
                <option :value="7">最近 7 天</option>
                <option :value="0">全部时间</option>
              </select></label
            >
          </div>
        </div>
        <div class="chart-meta">
          <div class="chart-legend">
            <button
              :aria-pressed="technical"
              :class="{ disabled: !technical }"
              @click="technical = !technical"
            >
              <i />{{ techLabel }}</button
            ><button
              :aria-pressed="expression"
              :class="{ disabled: !expression }"
              @click="expression = !expression"
            >
              <i class="mint" />逻辑表达
            </button>
          </div>
          <span
            >{{ samples.length }} 场可比面试 · 评分
            {{ samples[0]?.version || "v1" }}</span
          >
        </div>
        <div class="trend-chart">
          <svg
            v-if="samples.length"
            viewBox="0 0 1232 128"
            role="img"
            :aria-label="`${techLabel}与逻辑表达的面试参考分趋势`"
            preserveAspectRatio="none"
          >
            <g v-for="value in [0, 50, 100]" :key="value">
              <text x="26" :y="y(value) + 4" text-anchor="end">
                {{ value }}
              </text>
              <line
                x1="45"
                x2="1206"
                :y1="y(value)"
                :y2="y(value)"
                stroke="#e9eef7"
                stroke-dasharray="5 6"
              />
            </g>
            <g v-if="technical">
              <polygon
                v-if="samples.length > 1"
                :points="`${x(0)},99 ${points('technical')} ${x(samples.length - 1)},99`"
                fill="#5b80e5"
                opacity=".055"
              />
              <polyline
                v-if="samples.length > 1"
                :points="points('technical')"
                fill="none"
                stroke="#5b80e5"
                stroke-width="2.3"
              />
              <circle
                v-for="(sample, i) in samples"
                :key="sample.id"
                :cx="x(i)"
                :cy="y(sample.technical)"
                r="3.5"
                fill="#fff"
                stroke="#5b80e5"
                stroke-width="2"
              >
                <title>
                  {{ sample.date }} {{ techLabel }}：{{ sample.technical }}
                </title>
              </circle>
            </g>
            <g v-if="expression">
              <polyline
                v-if="samples.length > 1"
                :points="points('expression')"
                fill="none"
                stroke="#72b9a5"
                stroke-width="2.3"
                stroke-dasharray="6 5"
              />
              <circle
                v-for="(sample, i) in samples"
                :key="sample.id"
                :cx="x(i)"
                :cy="y(sample.expression)"
                r="3"
                fill="#fff"
                stroke="#72b9a5"
                stroke-width="2"
              >
                <title>
                  {{ sample.date }} 逻辑表达：{{ sample.expression }}
                </title>
              </circle>
            </g>
            <text
              v-for="(sample, i) in samples"
              :key="sample.id"
              :x="x(i)"
              y="122"
              text-anchor="middle"
            >
              {{ sample.date.slice(5) }}
            </text>
          </svg>
          <div v-else class="empty-state">
            <UiIcon name="chart" :size="28" /><span>暂无可比较的面试记录</span>
          </div>
        </div>
        <div class="trend-foot">
          <span>同岗位 · 同 JD 版本 · 同评分版本</span
          ><span>{{ coverage }}</span>
        </div>
      </section>
      <section class="ui-panel history-records">
        <div class="history-record-heading">
          <div class="ui-tabs" role="tablist" aria-label="记录类型">
            <button
              v-for="item in [
                { id: 'interview', name: '模拟面试' },
                { id: 'practice', name: '薄弱项复练' },
              ]"
              :key="item.id"
              role="tab"
              :aria-selected="tab === item.id"
              :class="{ active: tab === item.id }"
              @click="tab = item.id"
            >
              {{ item.name
              }}<span>{{
                scoped.filter((r) => r.kind === item.id).length
              }}</span>
            </button>
          </div>
          <div>
            <select v-model="status" class="ui-select" aria-label="记录状态">
              <option value="all">全部状态</option>
              <option value="completed">已完成</option>
              <option v-if="tab === 'interview'" value="ended">提前结束</option>
              <option v-else value="active">进行中</option></select
            ><span>训练时间 ↓</span>
          </div>
        </div>
        <SlidingTabs :active="tab" :order="['interview', 'practice']">
          <div class="data-grid history-grid data-head">
            <span>训练内容</span><span>训练时间</span
            ><span>{{ tab === "interview" ? "综合分" : "原题改写" }}</span
            ><span>{{ tab === "interview" ? "覆盖率" : "变式作答" }}</span
            ><span>状态</span><span class="align-right">操作</span>
          </div>
          <div class="history-rows ui-scroll">
            <div
              v-for="r in visible"
              :key="r.id"
              class="data-grid history-grid data-row"
            >
              <div class="history-row-title">
                <UiIcon
                  :name="r.kind === 'interview' ? 'file' : 'refresh'"
                  :size="23"
                />
                <div>
                  <strong>{{
                    r.title ||
                    `${roleNames[r.role]} · 第 ${r.number} 次模拟面试`
                  }}</strong
                  ><small>{{
                    r.local
                      ? "本次练习记录"
                      : r.kind === "interview"
                        ? targets.find((t) => t[0] === r.target)?.[1]
                        : `来自第 ${r.source} 次面试`
                  }}</small>
                </div>
              </div>
              <span class="muted-copy">{{ r.date }} {{ r.time }}</span
              ><template v-if="tab === 'interview'"
                ><strong class="history-score">{{ r.score ?? "—" }}</strong
                ><span>{{ r.coverage }}%</span></template
              ><template v-else
                ><span class="muted-copy">{{
                  r.original ? "已提交" : "未作答"
                }}</span
                ><span class="muted-copy">{{
                  r.variant ? "已提交" : "未作答"
                }}</span></template
              ><span
                ><span
                  class="ui-badge"
                  :class="
                    r.status === 'completed'
                      ? 'green'
                      : r.status === 'ended'
                        ? 'gray'
                        : ''
                  "
                  >{{
                    {
                      completed: "已完成",
                      ended: "提前结束",
                      active: "进行中",
                    }[r.status] || r.status
                  }}</span
                ></span
              ><RouterLink
                class="text-button align-right"
                :to="
                  r.kind === 'interview'
                    ? `/reports/${r.id}`
                    : `/practice/${r.id}`
                "
                >{{ r.kind === "interview" ? "查看报告" : "查看复练"
                }}<UiIcon name="next" :size="14"
              /></RouterLink>
            </div>
            <div v-if="!visible.length" class="empty-state">暂无相关记录</div>
          </div>
          <footer class="list-footer">
            <span>共 {{ filtered.length }} 条记录</span
            ><Pagination v-model="page" :total="filtered.length" :size="3" />
          </footer>
        </SlidingTabs>
      </section></div
  ></AppShell>
</template>
<style scoped>
.history-layout {
  height: 100%;
  display: grid;
  grid-template-rows: 44.117647% 52.205882%;
  gap: 3.676471%;
}
.trend-panel {
  padding: 16px 26px 10px;
  border-radius: 24px;
}
.trend-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  flex: none;
}
.trend-heading h2 {
  font-size: var(--ui-title);
  font-weight: 600;
  white-space: nowrap;
}
.history-filters {
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 0.88em;
}
.history-filters label {
  display: flex;
  gap: 9px;
  align-items: center;
  color: #8b98ad;
  white-space: nowrap;
}
.history-filters select {
  border: 1px solid #e0e6f0;
  border-radius: 7px;
  height: 34px;
  background: white;
  padding: 0 9px;
  font: inherit;
  color: #667895;
  max-width: 240px;
}
.chart-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #9aa6b8;
  font-size: 0.8em;
  margin-top: 14px;
  flex: none;
}
.chart-legend {
  display: flex;
  gap: 20px;
  align-items: center;
}
.chart-legend button {
  display: flex;
  gap: 8px;
  align-items: center;
  border: 0;
  background: transparent;
  padding: 0;
  color: #8292ad;
  font: inherit;
}
.chart-legend button.disabled {
  opacity: 0.35;
}
.chart-legend i {
  height: 3px;
  width: 18px;
  background: #5b80e5;
  display: block;
  border-radius: 2px;
}
.chart-legend i.mint {
  background: #72b9a5;
}
.trend-chart {
  flex: 1;
  min-height: 0;
  margin-top: 7px;
}
.trend-chart svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.trend-chart text {
  font:
    10px "Microsoft YaHei",
    sans-serif;
  fill: #9aa6b8;
}
.trend-chart .empty-state {
  min-height: 0;
  gap: 10px;
  font-size: 0.95em;
}
.trend-foot {
  display: flex;
  justify-content: space-between;
  color: #a1aabd;
  font-size: 0.76em;
  flex: none;
  margin-top: 4px;
}
.history-records {
  border-radius: 24px;
}
.history-record-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: none;
  min-height: 52px;
}
.history-record-heading .ui-tabs {
  border: 0;
  height: 52px;
  font-size: 0.95em;
  padding: 0 26px;
  gap: 24px;
}
.history-record-heading .ui-tabs button > span {
  margin-left: 9px;
  color: #9aa6b8;
  font-size: 0.8em;
  font-weight: 400;
}
.history-record-heading > div:last-child {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-right: 26px;
  font-size: 0.8em;
  color: #9aa6b8;
}
.history-record-heading .ui-select {
  font-size: inherit;
  min-height: 30px;
}
.history-grid {
  grid-template-columns:
    minmax(0, 3fr) minmax(0, 1.65fr) minmax(0, 0.75fr)
    minmax(0, 0.85fr) minmax(0, 1fr) minmax(0, 1.1fr);
  gap: 12px;
}
.history-records .data-head {
  min-height: 32px;
}
.history-rows {
  flex: 1;
}
.history-records .data-row {
  min-height: calc((var(--workspace-height) * 0.52205882 - 134px) / 3);
  font-size: 0.88em;
}
.history-row-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.history-row-title > svg {
  color: #8ba0c4;
  flex: none;
}
.history-row-title > div {
  min-width: 0;
}
.history-row-title strong {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-row-title small {
  font-size: 0.83em;
}
.history-score {
  font-size: 1.2em;
  font-weight: 600 !important;
}
.history-records .list-footer {
  min-height: 48px;
  font-size: 0.8em;
}
.history-rows .empty-state {
  min-height: 70px;
}
.history-grid > .text-button {
  justify-content: flex-end;
}
@media (max-width: 1200px) {
  .history-filters {
    gap: 10px;
    font-size: 12px;
  }
  .history-filters label {
    gap: 5px;
  }
  .history-filters select {
    max-width: 190px;
    padding: 0 6px;
  }
  .trend-panel {
    padding-left: 22px;
    padding-right: 22px;
  }
  .history-grid {
    padding: 0 22px;
    gap: 9px;
    grid-template-columns: 2.5fr 1.6fr 0.7fr 0.8fr 0.9fr 1.1fr;
  }
  .history-record-heading .ui-tabs {
    gap: 18px;
    padding-left: 22px;
  }
  .history-record-heading > div:last-child {
    gap: 10px;
    padding-right: 22px;
  }
}
</style>
