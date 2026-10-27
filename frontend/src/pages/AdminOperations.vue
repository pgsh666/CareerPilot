<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import Pagination from "../ui/Pagination.vue";
import UiModal from "../ui/UiModal.vue";
import { api, errorMessage } from "../core/api";
import {
  adminSnapshot as snapshot,
  fee,
  loadAdminSnapshot,
} from "../core/admin";
import { state } from "../core/state";
const props = defineProps<{ tab: string }>();
const status = ref("all"),
  purpose = ref("all"),
  page = ref(1),
  total = ref(0),
  error = ref(""),
  loading = ref(false);
interface Usage {
  id: string;
  purposeLabel: string;
  model: string;
  state: string;
  createdAt: string;
  durationMs: number | null;
  promptTokens: number | null;
  completionTokens: number | null;
  chargedUpperMicroCny: number | null;
  reservedMicroCny: number;
  feeSource: string;
  errorCode: string | null;
  taskId: string | null;
}
interface Diagnostic {
  availability: string;
  stageLabel: string | null;
  rule: string | null;
  reason: string;
  raw: Record<string, unknown> | null;
  issues: { path: string; type: string; reason: string }[];
}
interface CallDetail extends Usage {
  purpose: string;
  requestKey: string;
  provider: string;
  providerRequestId: string | null;
  attempt: number | null;
  cachedTokens: number | null;
  totalTokens: number | null;
  finishedAt: string | null;
  testMode: boolean;
  candidateAvailable: boolean;
  diagnostic: Diagnostic;
}
interface Task {
  id: string;
  kind: string;
  state: string;
  attempts: number;
  createdAt: string;
  durationMs: number | null;
  errorCode: string | null;
  errorMessage: string | null;
}
interface TaskDetail extends Task {
  startedAt: string | null;
  finishedAt: string | null;
  trainingId: string | null;
  interviewPolicy: string | null;
  scoringVersion: string | null;
  outputSaved: boolean;
  diagnostic: Diagnostic;
}
interface OperationDetail {
  task: TaskDetail | null;
  calls: CallDetail[];
  callCount: number;
  callsTruncated: boolean;
  chargedUpperMicroCny: number;
  unknownCallCount: number;
  selectedCallId: string | null;
  observedAt: string;
}
const usages = ref<Usage[]>([]),
  tasks = ref<Task[]>([]),
  detail = ref<OperationDetail | null>(null),
  detailTarget = ref<{ id: string; type: "tasks" | "usage" } | null>(null),
  detailLoading = ref(false),
  detailError = ref("");
let detailVersion = 0;
const owner = state.account.id;
let version = 0,
  alive = true;
const labels: Record<string, string> = {
  succeeded: "成功",
  failed: "失败",
  unknown: "费用待核实",
  queued: "排队中",
  running: "处理中",
  ready: "待保存",
  paused: "已暂停",
  stale: "已失效",
  reserved: "已预留",
  cancelled: "未发送",
  material_parse: "材料解析",
  plan: "面试出题",
  advance: "追问判断",
  report: "面试报告",
  variant: "变式出题",
  practice_feedback: "复练反馈",
  asr: "语音转写",
  tts: "问题播报",
};
const label = (v: string) => labels[v] || v;
const date = (v: string | null) =>
  v
    ? new Date(v).toLocaleString("zh-CN", {
        hour12: false,
        timeZone: "Asia/Shanghai",
      })
    : "—";
const json = (value: unknown) => JSON.stringify(value, null, 2);
const feeSource = (value: string) =>
  ({
    peak_upper_estimate: "峰值单价上界估算",
    provider_verified: "供应商凭据已核实",
    not_sent: "请求未发送",
    unknown: "待核实",
  })[value] || value;
function closeDetail() {
  detailVersion++;
  detailTarget.value = null;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = false;
}
function openDetail(value: Usage | Task) {
  closeDetail();
  detailTarget.value = {
    id: value.id,
    type: "purposeLabel" in value ? "usage" : "tasks",
  };
  void loadDetail();
}
async function loadDetail() {
  const target = detailTarget.value;
  if (!target) return;
  const current = ++detailVersion;
  detailLoading.value = true;
  detailError.value = "";
  try {
    const result = await api<OperationDetail>(
      `/admin/${target.type}/${encodeURIComponent(target.id)}`,
    );
    if (
      alive &&
      current === detailVersion &&
      owner === state.account.id &&
      state.account.role === "admin"
    )
      detail.value = result;
  } catch (e) {
    if (alive && current === detailVersion) detailError.value = errorMessage(e);
  } finally {
    if (current === detailVersion) detailLoading.value = false;
  }
}
async function load() {
  const v = ++version;
  loading.value = true;
  try {
    await loadAdminSnapshot();
    const params = new URLSearchParams({
      offset: String((page.value - 1) * 4),
      limit: "4",
    });
    if (props.tab === "usage") {
      params.set("purpose", purpose.value);
      params.set("state", status.value);
      const r = await api<{ items: Usage[]; total: number }>(
        `/admin/usage?${params}`,
      );
      if (!alive || owner !== state.account.id || v !== version) return;
      usages.value = r.items;
      total.value = r.total;
    } else {
      params.set("status", status.value);
      const r = await api<{ items: Task[]; total: number }>(
        `/admin/tasks?${params}`,
      );
      if (!alive || owner !== state.account.id || v !== version) return;
      tasks.value = r.items;
      total.value = r.total;
    }
    error.value = "";
  } catch (e) {
    if (alive && v === version) error.value = errorMessage(e);
  } finally {
    if (v === version) loading.value = false;
  }
}
watch(
  () => props.tab,
  () => {
    closeDetail();
    status.value = "all";
    purpose.value = "all";
    page.value = 1;
  },
);
watch([status, purpose], () => {
  page.value = 1;
});
watch([() => props.tab, status, purpose, page], () => void load(), {
  immediate: true,
});
onBeforeUnmount(() => {
  alive = false;
  version++;
  closeDetail();
});
const services = computed(() =>
  Object.entries(snapshot.value?.services || {}).map(([id, value]) => ({
    name:
      {
        database: "数据库",
        email: "邮件服务",
        model: "模型配置",
        speech: "离线语音",
      }[id] || id,
    good: ["ready", "reachable", "configured", "installed"].includes(value),
    text:
      {
        ready: "正常",
        reachable: "连接可达",
        unreachable: "连接失败",
        configured: "已配置",
        unconfigured: "未配置",
        installed: "已安装",
        unavailable: "未就绪",
      }[value] || value,
  })),
);
</script>
<template>
  <div class="operations ui-scroll">
    <p v-if="error" class="inline-error" role="alert">
      {{ error }} <button class="text-button" @click="load">重新加载</button>
    </p>
    <template v-if="tab === 'overview'"
      ><div class="operations-columns">
        <aside class="ui-scroll">
          <h3>服务状态</h3>
          <div v-for="s in services" :key="s.name" class="service-line">
            <span>{{ s.name }}</span
            ><span class="ui-badge" :class="{ green: s.good }">{{
              s.text
            }}</span>
          </div>
          <div class="success-rate">
            <span>本月调用成功率</span
            ><strong>{{
              snapshot?.successRate == null ? "—" : snapshot.successRate + "%"
            }}</strong
            ><small>{{ snapshot?.unknownCalls || 0 }} 次费用待核实</small>
          </div>
        </aside>
        <section class="overview-records">
          <div class="section-heading">
            <h3>近期任务</h3>
            <select v-model="status" class="ui-select" aria-label="任务状态">
              <option value="all">全部状态</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
              <option value="pending">待处理</option>
            </select>
          </div>
          <div class="task-rows ui-scroll">
            <div v-for="t in tasks" :key="t.id" class="operation-row">
              <div>
                <strong>{{ label(t.kind) }}</strong
                ><small>{{ date(t.createdAt) }}</small>
              </div>
              <span>{{
                t.durationMs == null ? "—" : t.durationMs + " ms"
              }}</span
              ><span
                class="ui-badge"
                :class="{ green: t.state === 'succeeded' }"
                >{{ label(t.state) }}</span
              ><button class="text-button" @click="openDetail(t)">详情</button>
            </div>
            <p v-if="!tasks.length" class="empty-state">
              {{ loading ? "正在加载…" : "暂无任务" }}
            </p>
          </div>
        </section>
      </div></template
    >
    <template v-else
      ><div class="operations-columns usage-columns">
        <aside class="usage-summary ui-scroll">
          <h3>费用汇总</h3>
          <div class="budget-summary">
            <article>
              <span>本月预算</span
              ><strong
                >¥ {{ fee(snapshot?.budgets.month.limitMicroCny) }}</strong
              >
            </article>
            <article>
              <span>已用 · 估算与核实合计</span
              ><strong
                >¥
                {{ fee(snapshot?.budgets.month.chargedUpperMicroCny) }}</strong
              >
            </article>
            <article>
              <span>处理中 / 待核实预留</span
              ><strong
                >¥ {{ fee(snapshot?.budgets.month.heldMicroCny) }}</strong
              >
            </article>
            <article>
              <span>可用余额</span
              ><strong
                >¥ {{ fee(snapshot?.budgets.month.remainingMicroCny) }}</strong
              >
            </article>
          </div>
          <p class="budget-note">
            累计测试上限 ¥{{
              fee(snapshot?.budgets.test.limitMicroCny)
            }}，已用上界 ¥{{
              fee(snapshot?.budgets.test.chargedUpperMicroCny)
            }}，已发起
            {{ snapshot?.budgets.test.sentCalls || 0 }}
            次。未核实费用按峰值单价估算，实际扣费以供应商账单为准。 本月估算
            ¥{{ fee(snapshot?.budgets.month.estimatedMicroCny) }}，已核实 ¥{{
              fee(snapshot?.budgets.month.verifiedMicroCny)
            }}； 未知费用占用预留 ¥{{
              fee(snapshot?.budgets.month.unknownHeldMicroCny)
            }}。
          </p>
          <div class="allocation-row">
            <span v-for="a in snapshot?.allocations || []" :key="a.purpose"
              >{{ a.label }} · {{ a.calls }} 次 · ¥{{
                fee(a.chargedUpperMicroCny)
              }}</span
            >
          </div>
        </aside>
        <section class="usage-records">
          <div class="section-heading">
            <h3>本月调用明细</h3>
            <div>
              <select v-model="purpose" class="ui-select" aria-label="调用用途">
                <option value="all">全部用途</option>
                <option
                  v-for="a in snapshot?.allocations || []"
                  :key="a.purpose"
                  :value="a.purpose"
                >
                  {{ a.label }}
                </option></select
              ><select v-model="status" class="ui-select" aria-label="调用状态">
                <option value="all">全部状态</option>
                <option value="succeeded">成功</option>
                <option value="failed">失败</option>
                <option value="unknown">费用待核实</option>
                <option value="running">处理中</option>
                <option value="reserved">已预留 · 未发送</option>
                <option value="cancelled">已取消 · 未发送</option>
              </select>
            </div>
          </div>
          <div class="usage-table">
            <div class="usage-grid data-head">
              <span>用途 / 模型</span><span>时间</span
              ><span>输入 / 输出 Token</span><span>记录费用</span
              ><span>状态</span><span>操作</span>
            </div>
            <div class="usage-rows ui-scroll">
              <div v-for="u in usages" :key="u.id" class="usage-grid data-row">
                <div>
                  <strong>{{ u.purposeLabel }}</strong
                  ><small>{{ u.model }}</small>
                </div>
                <span>{{ date(u.createdAt) }}</span
                ><span
                  >{{ u.promptTokens ?? "—" }} /
                  {{ u.completionTokens ?? "—" }}</span
                ><span>¥{{ fee(u.chargedUpperMicroCny) }}</span
                ><span
                  class="ui-badge"
                  :class="{ green: u.state === 'succeeded' }"
                  >{{ label(u.state) }}</span
                ><button class="text-button" @click="openDetail(u)">
                  详情
                </button>
              </div>
              <p v-if="!usages.length" class="empty-state">
                {{ loading ? "正在加载…" : "暂无调用" }}
              </p>
            </div>
          </div>
        </section>
      </div></template
    >
    <footer class="list-footer">
      <span>共 {{ total }} 条</span
      ><Pagination v-model="page" :total="total" :size="4" />
    </footer>
    <UiModal
      :open="!!detailTarget"
      wide
      title="任务与调用详情"
      @close="closeDetail"
    >
      <p v-if="detailLoading && !detail" role="status">正在读取完整详情…</p>
      <p v-if="detailError" class="inline-error" role="alert">
        {{ detailError }}
        <button class="text-button" @click="loadDetail">重新加载</button>
      </p>
      <div v-if="detail" class="operation-detail-content">
        <section v-if="detail.task">
          <h3>任务概况</h3>
          <dl class="operation-detail">
            <dt>任务编号</dt>
            <dd class="operation-code">{{ detail.task.id }}</dd>
            <dt>任务类型</dt>
            <dd>{{ label(detail.task.kind) }}</dd>
            <dt>当前状态</dt>
            <dd>{{ label(detail.task.state) }} · {{ detail.task.state }}</dd>
            <dt>请求时间</dt>
            <dd>{{ date(detail.task.createdAt) }}</dd>
            <dt>最近开始</dt>
            <dd>{{ date(detail.task.startedAt) }}</dd>
            <dt>最近结束</dt>
            <dd>{{ date(detail.task.finishedAt) }}</dd>
            <dt>最近耗时</dt>
            <dd>
              {{
                detail.task.durationMs == null
                  ? "—"
                  : detail.task.durationMs + " ms"
              }}
            </dd>
            <dt>尝试次数</dt>
            <dd>{{ detail.task.attempts }}</dd>
            <dt>当前错误码</dt>
            <dd class="operation-code">
              {{ detail.task.errorCode || "无当前错误" }}
            </dd>
            <dt>错误摘要</dt>
            <dd>
              {{
                detail.task.errorMessage ||
                "无当前错误；历史失败保留在下方调用记录中。"
              }}
            </dd>
            <dt>关联训练</dt>
            <dd class="operation-code">
              {{ detail.task.trainingId || "不关联训练" }}
            </dd>
            <dt>出题策略</dt>
            <dd class="operation-code">
              {{ detail.task.interviewPolicy || "旧版或不适用" }}
            </dd>
            <dt>评分版本</dt>
            <dd class="operation-code">
              {{ detail.task.scoringVersion || "不适用" }}
            </dd>
            <dt>结果保存</dt>
            <dd>
              {{ detail.task.outputSaved ? "结果已保存" : "尚无可应用结果" }}
            </dd>
          </dl>
          <div v-if="detail.task.diagnostic.raw" class="diagnostic-panel">
            <strong
              >{{ detail.task.diagnostic.stageLabel }} ·
              {{ detail.task.diagnostic.rule }}</strong
            >
            <p>{{ detail.task.diagnostic.reason }}</p>
            <pre class="diagnostic-json">{{
              json(detail.task.diagnostic.raw)
            }}</pre>
          </div>
          <p v-else-if="detail.task.errorCode" class="detail-note">
            {{ detail.task.diagnostic.reason }}
          </p>
        </section>
        <section>
          <h3>
            逐次调用记录
            <small
              >共 {{ detail.callCount }} 条 · 已知费用合计 ¥{{
                fee(detail.chargedUpperMicroCny)
              }}</small
            >
          </h3>
          <p class="detail-note">
            时间为北京时间。调用记录保留每次原始状态，任务成功后也可查看之前的失败。
          </p>
          <p v-if="detail.unknownCallCount" class="detail-note">
            另有 {{ detail.unknownCallCount }} 次费用待核实，未计入已知金额。
          </p>
          <p v-if="detail.callsTruncated" class="detail-note">
            此处最多展示100条调用，汇总覆盖全部调用。
          </p>
          <p v-if="!detail.calls.length" class="detail-note">
            没有关联模型调用记录。
          </p>
          <details
            v-for="call in detail.calls"
            :key="call.id"
            class="attempt-detail"
            :open="call.id === detail.selectedCallId || !!call.errorCode"
          >
            <summary>
              <span
                >{{
                  call.attempt == null
                    ? "独立调用"
                    : `第 ${call.attempt} 次尝试`
                }}
                · {{ label(call.state) }}</span
              ><span>¥{{ fee(call.chargedUpperMicroCny) }}</span>
            </summary>
            <dl class="operation-detail">
              <dt>调用编号</dt>
              <dd class="operation-code">{{ call.id }}</dd>
              <dt>内部请求号</dt>
              <dd class="operation-code">{{ call.requestKey }}</dd>
              <dt>供应商请求号</dt>
              <dd class="operation-code">
                {{ call.providerRequestId || "未取得" }}
              </dd>
              <dt>用途 / 模型</dt>
              <dd>
                {{ call.purposeLabel }} · {{ call.provider }} / {{ call.model }}
              </dd>
              <dt>原始状态</dt>
              <dd>{{ label(call.state) }} · {{ call.state }}</dd>
              <dt>开始 / 结束</dt>
              <dd>
                {{ date(call.createdAt) }}<br />{{ date(call.finishedAt) }}
              </dd>
              <dt>调用耗时</dt>
              <dd>
                {{ call.durationMs == null ? "—" : call.durationMs + " ms" }}
              </dd>
              <dt>输入 / 输出</dt>
              <dd>
                {{ call.promptTokens ?? "—" }} /
                {{ call.completionTokens ?? "—" }} Token
              </dd>
              <dt>缓存命中</dt>
              <dd>
                {{ call.cachedTokens ?? "—" }} Token · 总量
                {{ call.totalTokens ?? "—" }}
              </dd>
              <dt>记录费用</dt>
              <dd>
                ¥{{ fee(call.chargedUpperMicroCny) }} ·
                {{ feeSource(call.feeSource) }}
              </dd>
              <dt>预留上限</dt>
              <dd>¥{{ fee(call.reservedMicroCny) }}</dd>
              <dt>计费模式</dt>
              <dd>{{ call.testMode ? "累计测试预算" : "业务预算" }}</dd>
              <dt>错误代码</dt>
              <dd class="operation-code">{{ call.errorCode || "无" }}</dd>
              <dt>诊断阶段</dt>
              <dd>{{ call.diagnostic.stageLabel || "未记录" }}</dd>
              <dt>校验规则</dt>
              <dd class="operation-code">
                {{ call.diagnostic.rule || "未记录" }}
              </dd>
              <dt>具体原因</dt>
              <dd>{{ call.diagnostic.reason }}</dd>
              <dt>待校验缓存</dt>
              <dd>
                {{
                  call.candidateAvailable
                    ? "已保留，用户重试时可先离线复核"
                    : "未保留或不适用"
                }}
              </dd>
            </dl>
            <ul v-if="call.diagnostic.issues.length" class="diagnostic-issues">
              <li v-for="(issue, index) in call.diagnostic.issues" :key="index">
                <code>{{ issue.path }}</code
                >：{{ issue.reason }}（{{ issue.type }}）
              </li>
            </ul>
            <h4>后端原始诊断 JSON</h4>
            <pre v-if="call.diagnostic.raw" class="diagnostic-json">{{
              json(call.diagnostic.raw)
            }}</pre>
            <p v-else class="detail-note">
              {{
                call.errorCode
                  ? "该次调用未保存诊断 JSON，无法补造具体失败项。"
                  : "该次调用没有记录校验失败诊断。"
              }}
            </p>
          </details>
        </section>
        <details class="metadata-detail">
          <summary>完整后端元数据 JSON</summary>
          <pre class="diagnostic-json">{{ json(detail) }}</pre>
        </details>
      </div>
      <template #footer
        ><button
          class="ui-button"
          :disabled="detailLoading"
          @click="loadDetail"
        >
          {{ detailLoading ? "更新中…" : "刷新详情" }}</button
        ><button class="ui-button primary" @click="closeDetail">
          关闭
        </button></template
      >
    </UiModal>
  </div>
</template>
<style scoped>
.operations {
  padding: 22px 28px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
h3 {
  font-size: 1em;
  color: #526784;
}
.operations-columns {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 36px;
  flex: 1;
  min-height: 0;
}
.operations-columns > section {
  min-width: 0;
}
.usage-summary {
  min-height: 0;
  min-width: 0;
  overflow: auto;
}
.usage-records {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.usage-table {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.usage-rows {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.usage-table > .data-head {
  flex: none;
}
.operations-columns aside {
  padding-right: 24px;
  border-right: 1px solid #e4eaf4;
  min-height: 0;
  overflow: auto;
}
.overview-records {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.task-rows {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.operations-columns .section-heading {
  flex: none;
}
.service-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 18px 0;
  color: #667895;
}
.success-rate {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 20px;
  color: #8292ad;
}
.success-rate strong {
  font-size: 30px;
  color: #526784;
}
.operation-row {
  display: flex;
  gap: 24px;
  align-items: center;
  padding: 18px 0;
  border-bottom: 1px solid #edf1f7;
  font-size: 0.85em;
  color: #667895;
}
.operation-row > div {
  flex: 1;
}
small {
  display: block;
  font-size: 0.85em;
  color: #95a1b4;
  margin-top: 6px;
}
.budget-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  margin-top: 16px;
}
.budget-summary article {
  padding: 12px;
  border: 1px solid #e4eaf4;
  border-radius: 12px;
}
.budget-summary span {
  display: block;
  font-size: 0.8em;
  color: #8292ad;
}
.budget-summary strong {
  display: block;
  margin-top: 10px;
  font-size: 1.2em;
  color: #526784;
}
.budget-note {
  color: #8292ad;
  font-size: 0.8em;
  line-height: 1.8;
  margin: 16px 0;
}
.allocation-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
  color: #667895;
  font-size: 0.85em;
}
.usage-grid {
  display: grid;
  grid-template-columns: 1.3fr 1.3fr 1fr 1fr 1fr 50px;
  gap: 14px;
  align-items: center;
  font-size: 0.85em;
}
.usage-grid .ui-badge {
  justify-self: start;
}
.list-footer {
  margin-top: 16px;
  flex: none;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  margin: 8px 0 16px;
  gap: 16px;
}
.section-heading select + select {
  margin-left: 12px;
}
.operation-detail {
  display: grid;
  grid-template-columns: minmax(96px, 24%) minmax(0, 1fr);
  gap: 10px 14px;
  font-size: 0.9em;
  margin: 16px 0;
}
.operation-detail dt {
  color: #95a1b4;
}
.operation-detail dd {
  margin: 0;
  color: #526784;
  word-break: break-all;
}
.operation-detail-content {
  min-width: 0;
}
.operation-detail-content > section + section {
  border-top: 1px solid #dce3ee;
  padding-top: 20px;
  margin-top: 20px;
}
.operation-code,
.diagnostic-json {
  font-family: Consolas, "Cascadia Code", monospace;
}
.detail-note,
.diagnostic-panel p {
  color: #7586a0;
  font-size: 0.88em;
  line-height: 1.7;
}
.attempt-detail {
  margin: 14px 0;
  padding: 12px 14px;
  border: 1px solid #dce3ee;
  border-radius: 12px;
  min-width: 0;
}
.attempt-detail > summary {
  cursor: pointer;
  color: #526784;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.attempt-detail > summary > span + span {
  float: right;
  margin-left: 12px;
}
.diagnostic-json {
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 12px;
  border: 1px solid #dce3ee;
  border-radius: 8px;
  color: #3c526f;
  background: #f2f6fcaa;
  font-size: 12px;
  line-height: 1.6;
}
.diagnostic-panel,
.diagnostic-issues,
.attempt-detail h4 {
  font-size: 0.9em;
  color: #526784;
}
.diagnostic-issues {
  overflow-wrap: anywhere;
  padding-left: 20px;
  line-height: 1.7;
}
.metadata-detail {
  margin-top: 20px;
}
.metadata-detail > summary {
  cursor: pointer;
  color: #6385ce;
}
</style>
