<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import Pagination from "../ui/Pagination.vue";
import { fixtures, notify, state } from "../core/state";
import { signOut } from "../core/auth";
import { api, errorMessage } from "../core/api";
import { isPreviewMode } from "../core/runtime";
import AdminOperations from "./AdminOperations.vue";
import { adminSnapshot, loadAdminSnapshot, fee } from "../core/admin";
if (!isPreviewMode) void loadAdminSnapshot().catch(() => {});
const router = useRouter();
const tab = ref("users"),
  query = ref(""),
  status = ref("all"),
  role = ref("all"),
  page = ref(1),
  taskStatus = ref("all"),
  usageKind = ref("all"),
  usagePage = ref(1);
const dialog = ref(""),
  userId = ref(""),
  callId = ref("");
const working = ref(false),
  actionError = ref("");
const loadError = ref("");
const serverTotal = ref(0),
  accountCount = ref<number | null>(null);
let loadGeneration = 0;
let loadTimer: ReturnType<typeof setTimeout>;
interface ServiceUser {
  id: string;
  name: string;
  email: string;
  role: string;
  enabled: boolean;
  closed: boolean;
  self: boolean;
  registeredAt: string;
  lastLoginAt: string | null;
  interviews: number | null;
  practices: number | null;
}
function displayTime(value: string | null, dayOnly = false) {
  if (!value) return "—";
  const d = new Date(value);
  return (
    `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}` +
    (dayOnly
      ? ""
      : ` ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`)
  );
}
async function loadUsers() {
  if (isPreviewMode) return;
  const generation = ++loadGeneration,
    owner = state.account.id;
  const params = new URLSearchParams({
    q: query.value,
    status: status.value,
    role:
      role.value === "管理员"
        ? "admin"
        : role.value === "普通用户"
          ? "user"
          : "all",
    offset: String((page.value - 1) * 4),
    limit: "4",
  });
  try {
    const result = await api<{
      items: ServiceUser[];
      total: number;
      accountCount: number;
    }>(`/admin/users?${params}`);
    if (generation !== loadGeneration || owner !== state.account.id) return;
    state.adminUsers = result.items.map((u) => ({
      ...u,
      role: u.role === "admin" ? "管理员" : "普通用户",
      registered: displayTime(u.registeredAt, true),
      lastSeen: displayTime(u.lastLoginAt),
    }));
    serverTotal.value = result.total;
    accountCount.value = result.accountCount;
    page.value = Math.min(page.value, Math.max(1, Math.ceil(result.total / 4)));
    loadError.value = "";
  } catch (failure) {
    if (generation === loadGeneration && owner === state.account.id) {
      state.adminUsers = [];
      serverTotal.value = 0;
      accountCount.value = null;
      loadError.value = errorMessage(failure);
    }
  }
}
watch(
  [query, status, role, page],
  () => {
    if (isPreviewMode) return;
    clearTimeout(loadTimer);
    loadTimer = setTimeout(() => void loadUsers(), 150);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  clearTimeout(loadTimer);
  loadGeneration++;
});
const users = computed(() =>
  isPreviewMode
    ? state.adminUsers.filter(
        (u) =>
          (u.name + " " + u.email)
            .toLowerCase()
            .includes(query.value.trim().toLowerCase()) &&
          (status.value === "all" ||
            (status.value === "enabled") === u.enabled) &&
          (role.value === "all" || u.role === role.value),
      )
    : state.adminUsers,
);
const visibleUsers = computed(() =>
  isPreviewMode
    ? users.value.slice((page.value - 1) * 4, page.value * 4)
    : users.value,
);
const usersTotal = computed(() =>
  isPreviewMode ? users.value.length : serverTotal.value,
);
const user = computed(() =>
  state.adminUsers.find((u) => u.id === userId.value),
);
const calls = isPreviewMode ? fixtures.admin.calls : [],
  totalCents = calls.reduce((n, c) => n + c.cents, 0),
  money = (cents: number) => (isPreviewMode ? (cents / 100).toFixed(2) : "—");
const recent = computed(() =>
  calls
    .slice(0, 4)
    .filter(
      (c) =>
        taskStatus.value === "all" || c.ok === (taskStatus.value === "success"),
    ),
);
const usage = computed(() =>
  calls.filter((c) => usageKind.value === "all" || c.kind === usageKind.value),
);
const usageVisible = computed(() =>
  usage.value.slice((usagePage.value - 1) * 4, usagePage.value * 4),
);
const call = computed(() => calls.find((c) => c.id === callId.value));
const allocations = [
  {
    name: "材料解析",
    amount: calls
      .filter((c) => ["简历解析", "JD解析"].includes(c.kind))
      .reduce((n, c) => n + c.cents, 0),
  },
  {
    name: "面试与复练",
    amount: calls
      .filter((c) => ["面试提问", "复练反馈"].includes(c.kind))
      .reduce((n, c) => n + c.cents, 0),
  },
  {
    name: "报告生成",
    amount: calls
      .filter((c) => c.kind === "报告生成")
      .reduce((n, c) => n + c.cents, 0),
  },
];
watch([query, status, role], () => (page.value = 1));
watch(usageKind, () => (usagePage.value = 1));
function viewUser(id: string) {
  actionError.value = "";
  userId.value = id;
  dialog.value = "user";
}
function toggleUser(id: string) {
  actionError.value = "";
  const u = state.adminUsers.find((u) => u.id === id);
  if (!u || u.self || u.id === state.account.id) return;
  userId.value = id;
  dialog.value = "toggle";
}
async function confirm() {
  if (working.value) return;
  actionError.value = "";
  if (dialog.value === "logout") {
    working.value = true;
    try {
      await signOut();
      dialog.value = "";
      await router.push("/login?form=login");
    } catch (failure) {
      actionError.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  if (!isPreviewMode) {
    const u = user.value;
    if (!u || u.self) return;
    const owner = state.account.id;
    working.value = true;
    try {
      await api(`/admin/users/${u.id}/status`, {
        method: "PATCH",
        body: { enabled: !u.enabled },
      });
      if (owner !== state.account.id) return;
      await loadUsers();
      dialog.value = "";
      notify(u.enabled ? "账号已停用" : "账号已启用");
    } catch (failure) {
      actionError.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  const u = user.value;
  if (u && !u.self && u.id !== state.account.id) {
    u.enabled = !u.enabled;
    notify(u.enabled ? "账号已启用" : "账号已停用");
  }
  dialog.value = "";
  page.value = Math.min(
    page.value,
    Math.max(1, Math.ceil(users.value.length / 4)),
  );
}
function viewCall(id: string) {
  callId.value = id;
  dialog.value = "call";
}
</script>
<template>
  <AppShell title="管理中心"
    ><template #actions
      ><button class="ui-button admin-logout" @click="dialog = 'logout'">
        退出登录
      </button></template
    >
    <div class="admin-layout">
      <div class="admin-stats">
        <article>
          <span>用户总数</span
          ><strong
            >{{ isPreviewMode ? state.adminUsers.length : (accountCount ?? "—")
            }}<small>人</small></strong
          >
        </article>
        <article>
          <span>今日训练</span
          ><strong>{{ isPreviewMode ? 12 : adminSnapshot?.todayTraining ?? "—" }}<small>场</small></strong>
        </article>
        <article>
          <span>本月模型用量</span><strong>¥ {{ isPreviewMode ? money(totalCents) : fee(adminSnapshot?.budgets.month.chargedUpperMicroCny) }}</strong>
        </article>
        <article>
          <span>待处理任务</span
          ><strong class="amber"
            >{{ isPreviewMode ? 1 : adminSnapshot?.pendingJobs ?? "—" }}<small>项</small></strong
          >
        </article>
      </div>
      <section class="ui-panel admin-board">
        <div class="ui-tabs" role="tablist" aria-label="管理功能">
          <button
            v-for="item in [
              { id: 'users', name: '用户管理' },
              { id: 'overview', name: '运行概况' },
              { id: 'usage', name: '模型用量' },
            ]"
            :key="item.id"
            role="tab"
            :aria-selected="tab === item.id"
            :class="{ active: tab === item.id }"
            @click="tab = item.id"
          >
            {{ item.name }}
          </button>
        </div>
        <SlidingTabs :active="tab" :order="['users', 'overview', 'usage']">
          <template v-if="tab === 'users'"
            ><div class="admin-user-filters">
              <label class="admin-search"
                ><UiIcon name="search" :size="17" /><input
                  v-model="query"
                  type="search"
                  aria-label="搜索用户名或邮箱"
                  placeholder="搜索用户名或邮箱" /></label
              ><select v-model="status" class="ui-select" aria-label="账号状态">
                <option value="all">全部状态</option>
                <option value="enabled">已启用</option>
                <option value="disabled">已停用</option></select
              ><select v-model="role" class="ui-select" aria-label="账号角色">
                <option value="all">全部角色</option>
                <option>普通用户</option>
                <option>管理员</option>
              </select>
            </div>
            <div class="data-grid admin-user-grid data-head">
              <span>用户／邮箱</span><span>角色</span><span>状态</span
              ><span>注册时间</span><span>最近登录</span
              ><span class="align-right">操作</span>
            </div>
            <div class="admin-user-rows ui-scroll">
              <div
                v-for="u in visibleUsers"
                :key="u.id"
                class="data-grid admin-user-grid data-row"
              >
                <div class="admin-user-identity">
                  <span :class="{ administrator: u.self }">{{
                    u.self ? "管" : u.name.slice(0, 1)
                  }}</span>
                  <div>
                    <strong>{{ u.name }}</strong
                    ><small>{{ u.email }}</small>
                  </div>
                </div>
                <span>{{ u.role }}</span
                ><span
                  ><span
                    class="ui-badge"
                    :class="u.enabled ? 'green' : 'gray'"
                    >{{ u.closed ? "已注销" : u.enabled ? "已启用" : "已停用" }}</span
                  ></span
                ><span class="muted-copy">{{ u.registered }}</span
                ><span class="muted-copy">{{ u.lastSeen }}</span>
                <div class="row-actions">
                  <button class="text-button" @click="viewUser(u.id)">
                    查看</button
                  ><span v-if="u.self" class="muted-copy">当前账号</span
                  ><button
                    v-else-if="!u.closed"
                    class="text-button"
                    :class="{ 'muted-action': u.enabled }"
                    @click="toggleUser(u.id)"
                  >
                    {{ u.enabled ? "停用" : "启用" }}
                  </button>
                </div>
              </div>
              <div v-if="!users.length" class="empty-state">
                {{ loadError || "没有匹配的用户" }}
              </div>
            </div>
            <footer class="list-footer">
              <span>共 {{ usersTotal }} 个账号</span
              ><Pagination
                v-model="page"
                :total="usersTotal"
                :size="4"
              /></footer
          ></template>
          <AdminOperations v-else-if="!isPreviewMode" :tab="tab" />
          <div v-else-if="tab === 'overview'" class="admin-overview">
            <aside class="admin-service">
              <h3>服务状态</h3>
              <div>
                <span>数据库</span
                ><span class="ui-badge" :class="{ green: isPreviewMode }">{{
                  isPreviewMode ? "正常" : "待查询"
                }}</span>
              </div>
              <div>
                <span>邮件服务</span
                ><span class="ui-badge" :class="{ green: isPreviewMode }">{{
                  isPreviewMode ? "正常" : "待查询"
                }}</span>
              </div>
              <div>
                <span>模型调用</span
                ><span class="ui-badge">{{
                  isPreviewMode ? "1 次失败" : "待查询"
                }}</span>
              </div>
              <section>
                <span>本月调用成功率</span
                ><strong
                  >{{ isPreviewMode ? 97.5 : "—" }}<small>%</small></strong
                >
                <div class="budget-bar">
                  <i :style="{ width: isPreviewMode ? '97.5%' : '0%' }" />
                </div>
                <p>
                  {{
                    isPreviewMode
                      ? "成功 39 次 / 共 40 次"
                      : "运行概况服务尚未接入"
                  }}
                </p>
              </section>
            </aside>
            <section class="admin-tasks">
              <div class="section-heading">
                <h2>最近任务</h2>
                <select
                  v-model="taskStatus"
                  class="ui-select"
                  aria-label="任务状态"
                >
                  <option value="all">全部状态</option>
                  <option value="success">成功</option>
                  <option value="failed">失败</option>
                </select>
              </div>
              <div class="data-grid admin-task-grid data-head">
                <span>时间</span><span>任务</span><span>账号</span
                ><span>状态</span><span>耗时</span
                ><span class="align-right">操作</span>
              </div>
              <div class="ui-scroll admin-tasks-body">
                <div
                  v-for="c in recent"
                  :key="c.id"
                  class="data-grid admin-task-grid data-row"
                >
                  <span class="muted-copy">{{ c.date }} {{ c.time }}</span
                  ><strong>{{ c.kind }}</strong
                  ><span>{{ c.user.name }}</span
                  ><span
                    ><span class="ui-badge" :class="c.ok ? 'green' : 'red'">{{
                      c.ok ? "成功" : "失败"
                    }}</span></span
                  ><span class="muted-copy">{{ c.seconds.toFixed(1) }} 秒</span
                  ><button class="text-button" @click="viewCall(c.id)">
                    查看详情
                  </button>
                </div>
                <div v-if="!recent.length" class="empty-state">暂无任务</div>
              </div>
            </section>
          </div>
          <div v-else class="admin-usage">
            <aside class="admin-budget">
              <div class="section-heading">
                <h2>本月额度</h2>
                <span>{{
                  isPreviewMode
                    ? "2026.10"
                    : new Date().toLocaleDateString("zh-CN", {
                        year: "numeric",
                        month: "2-digit",
                      })
                }}</span>
              </div>
              <div class="budget-number">
                ¥ {{ money(totalCents) }}<small> / 50.00</small>
              </div>
              <div class="budget-bar">
                <i :style="{ width: `${(totalCents / 5000) * 100}%` }" />
              </div>
              <p class="budget-remaining">
                剩余额度<strong>¥ {{ money(5000 - totalCents) }}</strong>
              </p>
              <div class="cost-split">
                <div v-for="item in allocations" :key="item.name">
                  <span>{{ item.name }}</span
                  ><strong>¥ {{ money(item.amount) }}</strong>
                </div>
              </div>
            </aside>
            <section class="admin-call-details">
              <div class="section-heading">
                <h2>调用明细<small>DeepSeek</small></h2>
                <select
                  v-model="usageKind"
                  class="ui-select"
                  aria-label="模型调用用途"
                >
                  <option value="all">全部用途</option>
                  <option v-for="item in fixtures.admin.kinds" :key="item">
                    {{ item }}
                  </option>
                </select>
              </div>
              <div class="data-grid admin-usage-grid data-head">
                <span>时间</span><span>用途</span><span>输入／输出 Token</span
                ><span>费用</span><span>状态</span>
              </div>
              <div class="ui-scroll admin-usage-rows">
                <div
                  v-for="c in usageVisible"
                  :key="c.id"
                  class="data-grid admin-usage-grid data-row"
                >
                  <span class="muted-copy">{{ c.date }} {{ c.time }}</span
                  ><strong>{{ c.kind }}</strong
                  ><span class="muted-copy"
                    >{{ c.input.toLocaleString() }} /
                    {{ c.out.toLocaleString() }}</span
                  ><span>¥ {{ money(c.cents) }}</span
                  ><span
                    ><span class="ui-badge" :class="c.ok ? 'green' : 'red'">{{
                      c.ok ? "成功" : "失败"
                    }}</span></span
                  >
                </div>
              </div>
              <footer class="list-footer">
                <span>共 {{ usage.length }} 次调用</span
                ><Pagination
                  v-model="usagePage"
                  :total="usage.length"
                  :size="4"
                />
              </footer>
            </section>
          </div>
        </SlidingTabs>
      </section>
    </div>
    <UiModal
      :open="!!dialog"
      :busy="working"
      :title="
        dialog === 'logout'
          ? '退出登录'
          : dialog === 'user'
            ? '用户详情'
            : dialog === 'toggle'
              ? user?.enabled
                ? '停用账号'
                : '启用账号'
              : '任务详情'
      "
      @close="dialog = ''"
      ><template v-if="dialog === 'user' && user"
        ><dl class="admin-detail">
          <div>
            <dt>用户名</dt>
            <dd>{{ user.name }}</dd>
          </div>
          <div>
            <dt>邮箱</dt>
            <dd>{{ user.email }}</dd>
          </div>
          <div>
            <dt>角色</dt>
            <dd>{{ user.role }}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{{ user.enabled ? "已启用" : "已停用" }}</dd>
          </div>
          <div>
            <dt>注册时间</dt>
            <dd>{{ user.registered }}</dd>
          </div>
          <div>
            <dt>最近登录</dt>
            <dd>{{ user.lastSeen }}</dd>
          </div>
          <div>
            <dt>模拟面试</dt>
            <dd>{{ user.interviews ?? "—" }} 场</dd>
          </div>
          <div>
            <dt>薄弱项复练</dt>
            <dd>{{ user.practices ?? "—" }} 次</dd>
          </div>
        </dl></template
      >
      <p v-else-if="dialog === 'toggle'" class="confirm-copy">
        {{
          user?.enabled
            ? `确认停用 ${user.name}（${user.email}）？已有资料和训练记录将保留。`
            : `确认启用 ${user?.name}（${user?.email}）？`
        }}
      </p>
      <p v-else-if="dialog === 'logout'" class="confirm-copy">
        确认退出当前账号？
      </p>
      <dl v-else-if="call" class="admin-detail">
        <div>
          <dt>任务编号</dt>
          <dd>{{ call.id }}</dd>
        </div>
        <div>
          <dt>任务类型</dt>
          <dd>{{ call.kind }}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{{ call.ok ? "成功" : "失败" }}</dd>
        </div>
        <div>
          <dt>耗时</dt>
          <dd>{{ call.seconds }} 秒</dd>
        </div>
        <div>
          <dt>费用</dt>
          <dd>¥ {{ money(call.cents) }}</dd>
        </div>
        <div v-if="!call.ok">
          <dt>错误摘要</dt>
          <dd>返回字段不完整，等待处理。</dd>
        </div>
      </dl>
      <p v-if="actionError" class="inline-error" role="alert">
        {{ actionError }}
      </p>
      <template #footer
        ><button class="ui-button" :disabled="working" @click="dialog = ''">
          {{
            dialog === "toggle" || dialog === "logout" ? "取消" : "关闭"
          }}</button
        ><button
          v-if="dialog === 'toggle' || dialog === 'logout'"
          class="ui-button primary"
          :disabled="working"
          @click="confirm"
        >
          {{ working ? "处理中…" : "确认" }}
        </button></template
      ></UiModal
    ></AppShell
  >
</template>
<style scoped>
.admin-logout {
  /* Four text characters + the upload action's 18px icon, 8px gap and padding. */
  width: calc(4em + 68px);
}
.admin-layout {
  display: flex;
  flex-direction: column;
  gap: clamp(16px, 2.222222svh, 28px);
  height: 100%;
}
.admin-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  height: calc(var(--workspace-height) * 0.16911765);
  flex: none;
}
.admin-stats article {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 14px 22px;
  background: white;
  border: 1px solid var(--line);
  border-radius: 20px;
  gap: 8px;
}
.admin-stats article > span {
  font-size: 0.88em;
  color: #8b98ad;
}
.admin-stats strong {
  font-size: clamp(26px, min(2.083333vw, 3.333333svh), 42px);
  font-weight: 600;
  line-height: 1.2;
  color: #344764;
}
.admin-stats strong.amber {
  color: #b99664;
}
.admin-stats strong small {
  font-size: 12px;
  font-weight: 400;
  color: #91a1ba;
  margin-left: 8px;
}
.admin-board {
  flex: 1;
  min-height: 0;
  border-radius: 24px;
}
.admin-user-filters {
  display: flex;
  gap: 14px;
  padding: 14px 26px;
  flex: none;
  font-size: 0.9em;
}
.admin-search {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #dfe6f0;
  border-radius: 8px;
  padding: 0 12px;
  min-width: 260px;
  width: 32%;
  color: #8b9cb7;
}
.admin-search input {
  border: 0;
  background: transparent;
  min-width: 0;
  width: 100%;
  height: 34px;
  font: inherit;
}
.admin-user-grid {
  grid-template-columns: 2.3fr 0.9fr 0.9fr 1.05fr 1.35fr 1.3fr;
}
.admin-user-rows {
  flex: 1;
}
.admin-user-grid.data-row {
  height: 25%;
  min-height: 40px;
  font-size: 0.88em;
}
.admin-user-identity {
  display: flex;
  align-items: center;
  gap: 12px;
}
.admin-user-identity > span {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #f0f4fb;
  color: #91a4c3;
  display: grid;
  place-items: center;
  flex: none;
}
.admin-user-identity > span.administrator {
  background: #e8effe;
  color: #6b8acd;
}
.admin-user-identity > div {
  min-width: 0;
}
.admin-user-identity small {
  font-size: 0.82em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.muted-action {
  color: #9ba7b9;
}
.admin-board .list-footer {
  min-height: 48px;
  font-size: 0.8em;
}
.admin-overview,
.admin-usage {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2.7fr);
  gap: 24px;
  padding: 22px 26px;
  flex: 1;
  min-height: 0;
}
.admin-tasks {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.admin-tasks > .section-heading {
  margin-bottom: 16px;
}
.admin-task-grid {
  grid-template-columns: 1.3fr 1.2fr 1fr 0.85fr 0.85fr 1.1fr;
  padding: 0 14px;
  gap: 10px;
  font-size: 0.85em;
}
.admin-tasks-body {
  flex: 1;
}
.admin-task-grid.data-row {
  height: 25%;
  min-height: 40px;
}
.admin-service {
  border: 1px solid #e3e9f3;
  background: #f8faff;
  border-radius: 14px;
  padding: 18px 20px;
  overflow-y: auto;
}
.admin-service h3 {
  font-size: 1em;
  font-weight: 500;
  margin-bottom: 18px;
}
.admin-service > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 0.85em;
  margin-top: 12px;
  color: #8292ad;
}
.admin-service > section {
  margin-top: 18px;
  border-top: 1px solid #e2e8f2;
  padding-top: 18px;
  color: #8b98ad;
  font-size: 0.85em;
}
.admin-service strong {
  font-size: 30px;
  display: block;
  color: #607fbf;
  margin-top: 12px;
}
.admin-service strong small {
  font-size: 12px;
  font-weight: 400;
  margin-left: 4px;
}
.admin-service p {
  font-size: 0.88em;
  margin-top: 10px;
  color: #9ca9bd;
}
.admin-usage {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2.7fr);
}
.admin-budget {
  border: 1px solid #e3e9f3;
  border-radius: 14px;
  background: #f8faff;
  padding: 22px;
  overflow-y: auto;
}
.admin-budget .section-heading > span {
  color: #9aa8bc;
  font-size: 0.85em;
}
.admin-budget h2 {
  font-size: 1.1em;
}
.budget-number {
  font-size: clamp(27px, 2.1vw, 40px);
  font-weight: 600;
  color: #344764;
  margin-top: 24px;
  white-space: nowrap;
}
.budget-number small {
  font-size: 14px;
  color: #9aa8bc;
  font-weight: 400;
}
.budget-bar {
  height: 7px;
  background: #eaf0fa;
  border-radius: 5px;
  margin-top: 16px;
}
.budget-bar > i {
  display: block;
  height: 100%;
  background: #8eabea;
  border-radius: 5px;
}
.budget-remaining {
  color: #8b98ad;
  font-size: 0.88em;
  margin-top: 18px;
}
.budget-remaining strong {
  font-weight: 500;
  margin-left: 16px;
  color: #7185a2;
}
.cost-split {
  border-top: 1px solid #e2e8f2;
  margin-top: 24px;
  padding-top: 8px;
}
.cost-split > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 0.85em;
  color: #8292ad;
  margin-top: 16px;
}
.cost-split strong {
  font-weight: 400;
  color: #60779a;
}
.admin-call-details {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.admin-call-details > .section-heading {
  margin-bottom: 16px;
}
.admin-call-details h2 {
  font-size: 1.1em;
}
.admin-call-details h2 small {
  font-size: 11px;
  font-weight: 400;
  color: #9aa8bc;
  margin-left: 12px;
}
.admin-usage-grid {
  grid-template-columns: 1.25fr 1.2fr 1.7fr 0.9fr 0.8fr;
  padding: 0 14px;
  font-size: 0.85em;
  gap: 10px;
}
.admin-usage-rows {
  flex: 1;
}
.admin-usage-grid.data-row {
  height: 25%;
  min-height: 32px;
}
.admin-call-details .list-footer {
  padding: 0 14px;
  min-height: 42px;
  font-size: 0.8em;
}
.admin-detail > div {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  padding: 12px 0;
  border-bottom: 1px solid #edf0f6;
  line-height: 1.7;
}
.admin-detail dt {
  color: #8b98ad;
  flex: none;
}
.admin-detail dd {
  text-align: right;
  color: #596e8e;
  overflow-wrap: anywhere;
}
.admin-user-rows .empty-state {
  min-height: 110px;
}
@media (max-width: 1200px) {
  .admin-stats {
    gap: 16px;
  }
  .admin-stats article {
    padding: 12px 18px;
  }
  .admin-user-grid {
    grid-template-columns: 2fr 0.85fr 0.85fr 1fr 1.3fr 1.3fr;
    gap: 8px;
    padding: 0 22px;
  }
  .admin-user-filters {
    padding-left: 22px;
    padding-right: 22px;
  }
  .admin-overview,
  .admin-usage {
    padding: 18px 22px;
    gap: 18px;
  }
  .admin-service {
    padding: 16px;
  }
  .admin-task-grid {
    font-size: 12px;
    padding: 0 8px;
    gap: 8px;
  }
  .admin-usage-grid {
    font-size: 12px;
    padding: 0 8px;
    gap: 8px;
  }
  .admin-budget {
    padding: 18px;
  }
  .budget-number small {
    font-size: 11px;
  }
  .admin-user-identity {
    gap: 8px;
  }
  .admin-user-identity > span {
    width: 30px;
    height: 30px;
  }
  .row-actions {
    gap: 12px;
  }
}
</style>
