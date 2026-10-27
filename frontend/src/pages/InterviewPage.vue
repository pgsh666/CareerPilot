<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import CollapseRegion from "../ui/CollapseRegion.vue";
import JobEditor from "../ui/JobEditor.vue";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import Pagination from "../ui/Pagination.vue";
import {
  blankJob,
  clone,
  fixtures,
  notify,
  startSession,
  state,
  tasks,
  timeLabel,
} from "../core/state";
import type { Job } from "../core/state";
import { isPreviewMode } from "../core/runtime";
import { errorMessage } from "../core/api";
import { parseJob, saveJob, renameJob, materialError } from "../core/materials";
import { trainingState, startInterview, startPractice } from "../core/training";
const starting = ref(false);
let launchKey = crypto.randomUUID();
const jobBusy = ref(false);
const renameTarget = ref<Job | null>(null),
  renameTitle = ref(""),
  renameError = ref("");
const route = useRoute(),
  router = useRouter();
const tab = computed(() =>
  ["prepare", "tasks"].includes(String(route.query.tab))
    ? String(route.query.tab)
    : "jobs",
);
const history = ref(false),
  historyPage = ref(1),
  openJobId = ref(""),
  jobPanel = ref<HTMLElement>(),
  recordDrafts = ref<Record<string, Job>>({}),
  draft = ref<Job>(clone(state.jobDraft || blankJob())),
  jdError = ref("");
const selectedJob = ref(
    state.jobs.find((j) => j.status === "confirmed")?.id || "",
  ),
  selectedResume = ref(
    state.resumes.find((r) => r.status === "confirmed")?.id || "",
  ),
  count = ref(5),
  materials = ref(false),
  taskId = ref(String(route.query.task || "")),
  taskFilter = ref("pending");
const replacing = ref(false),
  pendingMode = ref<"interview" | "practice">("interview");
const job = computed(() => state.jobs.find((j) => j.id === selectedJob.value)),
  resume = computed(() =>
    state.resumes.find((r) => r.id === selectedResume.value),
  );
const ready = computed(
  () =>
    !!materials.value &&
    job.value?.status === "confirmed" &&
    resume.value?.status === "confirmed",
);
const taskList = computed(() =>
  (isPreviewMode
    ? tasks.value
    : trainingState.tasks.map((t) => ({
        ...t,
        dimension: t.focus,
        weakness: t.suggestion,
        source: "来源面试",
        date: "",
        question: t.title,
      }))
  ).filter((t) => taskFilter.value === "all" || !t.done),
);
const jobList = computed(() =>
  state.jobs.slice((historyPage.value - 1) * 3, historyPage.value * 3),
);
watch([selectedJob, selectedResume], () => (materials.value = false));
const draftOwner = state.account.id;
watch(
  draft,
  (value) => {
    if (state.account.id === draftOwner) state.jobDraft = clone(value);
  },
  { deep: true },
);
watch(
  () => route.query,
  (query) => {
    if (query.task) taskId.value = String(query.task);
    if (query.job) editJob(String(query.job));
  },
  { immediate: true },
);
function selectTab(value: string) {
  router.push({ path: "/interview", query: { tab: value } });
}
function editJob(id: string) {
  if (jobBusy.value) return;
  const found = state.jobs.find((j) => j.id === id);
  if (found) {
    draft.value = clone(found);
    recordDrafts.value[id] = draft.value;
    historyPage.value = Math.floor(state.jobs.indexOf(found) / 3) + 1;
    history.value = true;
    openJobId.value = id;
    jdError.value = "";
  }
}
function toggleJob(item: Job) {
  if (jobBusy.value) return;
  if (openJobId.value === item.id) openJobId.value = "";
  else editJob(item.id);
}
function showRename(item: Job) {
  if (jobBusy.value) return;
  renameTarget.value = clone(item);
  renameTitle.value = item.title;
  renameError.value = "";
}
async function saveRename() {
  const target = renameTarget.value,
    title = renameTitle.value.trim();
  if (!target || jobBusy.value) return;
  if (!title || Array.from(title).length > 180) {
    renameError.value = "请填写1—180个字符的 JD 名称";
    return;
  }
  if (title === target.title) {
    renameTarget.value = null;
    return;
  }
  jobBusy.value = true;
  renameError.value = "";
  try {
    let result: Job;
    if (isPreviewMode) {
      const saved = state.jobs.find((item) => item.id === target.id);
      if (!saved) throw new Error("JD 已不存在，请刷新后重试");
      saved.title = title;
      saved.date = timeLabel();
      result = saved;
    } else result = await renameJob(target, title);
    // Keep unsaved content edits and advance only the title's save revision.
    for (const local of [draft.value, recordDrafts.value[result.id]]) {
      if (local?.id === result.id) {
        local.title = result.title;
        local.revision = result.revision;
        local.date = result.date;
      }
    }
    renameTarget.value = null;
    notify("岗位 JD 已重命名");
  } catch (failure) {
    renameError.value = errorMessage(failure);
  } finally {
    jobBusy.value = false;
  }
}
function scrollToJob(id: string) {
  if (openJobId.value !== id || !jobPanel.value) return;
  const row = jobPanel.value.querySelector<HTMLElement>(
    `[data-record="${id}"]`,
  );
  if (row)
    jobPanel.value.scrollTo({
      top: row.offsetTop,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
}
function invalidate() {
  if (draft.value.source !== draft.value.analyzedSource) {
    draft.value.parsed = false;
    draft.value.status = "pending";
    draft.value.analyzedSource = null;
    draft.value.name =
      draft.value.company =
      draft.value.role =
      draft.value.direction =
      draft.value.responsibilities =
      draft.value.requirements =
      draft.value.inference =
        "";
    draft.value.useInference = false;
  }
  jdError.value = "";
}
async function parse() {
  if (jobBusy.value) return;
  const j = draft.value;
  if (!j.source.trim()) return;
  if (Array.from(j.source.replace(/\r\n?/g, "\n")).length > 20000) {
    jdError.value = "JD原文上限20,000字符，完整输入已保留，请调整后解析。";
    return;
  }
  if (!isPreviewMode) {
    jobBusy.value = true;
    jdError.value = "";
    try {
      const result = await parseJob(clone(j), j.id);
      if (draft.value !== j) return;
      draft.value = result;
      if (history.value) recordDrafts.value[result.id] = result;
      jdError.value =
        result.parsingJob?.state === "succeeded"
          ? "已解析，请对照原文校对后保存。"
          : result.parsingJob?.errorMessage ||
            "智能解析尚未完成，原文和可识别字段已保存，可先人工校对。";
    } catch (failure) {
      jdError.value = errorMessage(failure);
    } finally {
      jobBusy.value = false;
    }
    return;
  }
  const existing = state.jobs.find((item) => item.id === j.id);
  if (existing?.status === "confirmed" && existing.source !== j.source)
    j.version = existing.version + 1;
  j.parsed = true;
  j.analyzedSource = j.source;
  j.status = "pending";
  j.date = timeLabel();
  const at = state.jobs.findIndex((item) => item.id === j.id);
  if (at >= 0) state.jobs.splice(at, 1, clone(j));
  else state.jobs.unshift(clone(j));
  jdError.value = "自动解析待后端接入，请先对照原文填写结构化字段。";
}
async function save() {
  if (jobBusy.value) return;
  const j = draft.value;
  jdError.value = "";
  if (Array.from(j.source.replace(/\r\n?/g, "\n")).length > 20000) {
    jdError.value = "JD原文上限20,000字符，请调整后保存。";
    return;
  }
  if (!j.parsed || j.analyzedSource !== j.source) {
    jdError.value = "原文已修改，请重新解析";
    return;
  }
  if (
    !j.name.trim() ||
    !j.role ||
    !j.direction.trim() ||
    !j.requirements.trim()
  ) {
    jdError.value = "请填写岗位名称、岗位类别、岗位方向和明确要求";
    return;
  }
  if (!isPreviewMode) {
    jobBusy.value = true;
    try {
      const result = await saveJob(clone(j));
      if (draft.value !== j) return;
      draft.value = result;
      if (history.value) {
        recordDrafts.value[result.id] = result;
        openJobId.value = "";
      }
      selectedJob.value = result.id;
      notify("岗位 JD 已确认并保存");
    } catch (failure) {
      jdError.value = errorMessage(failure);
    } finally {
      jobBusy.value = false;
    }
    return;
  }
  const existing = state.jobs.find((r) => r.id === j.id);
  if (
    existing?.status === "confirmed" &&
    JSON.stringify(existing) !== JSON.stringify(j)
  )
    j.version = existing.version + 1;
  j.status = "confirmed";
  if (
    !existing ||
    existing.title === "新增岗位 JD" ||
    existing.title === Array.from(existing.name).slice(0, 180).join("")
  )
    j.title = Array.from(j.name.trim()).slice(0, 180).join("");
  j.date = timeLabel();
  const at = state.jobs.findIndex((r) => r.id === j.id);
  if (at >= 0) state.jobs.splice(at, 1, clone(j));
  else state.jobs.unshift(clone(j));
  selectedJob.value = j.id;
  if (history.value) openJobId.value = "";
  notify("岗位 JD 已确认并保存");
}
function begin(mode: "interview" | "practice") {
  pendingMode.value = mode;
  if (mode === "interview" && !ready.value) return;
  if (mode === "practice" && !taskList.value.some((t) => t.id === taskId.value))
    return;
  if (
    isPreviewMode
      ? state.session && !state.session.finished
      : trainingState.active
  ) {
    replacing.value = true;
    return;
  }
  launch();
}
async function launch() {
  if (starting.value) return;
  replacing.value = false;
  if (!isPreviewMode) {
    starting.value = true;
    try {
      const row =
        pendingMode.value === "practice"
          ? await startPractice(
              taskId.value,
              launchKey,
              trainingState.active?.id,
            )
          : await startInterview(
              selectedResume.value,
              selectedJob.value,
              count.value,
              launchKey,
              trainingState.active?.id,
            );
      launchKey = crypto.randomUUID();
      await router.push({ path: "/interview/room", query: { id: row.id } });
    } catch (failure) {
      notify(errorMessage(failure));
    } finally {
      starting.value = false;
    }
    return;
  }
  const j = job.value || state.jobs.find((j) => j.status === "confirmed"),
    r = resume.value || state.resumes.find((r) => r.status === "confirmed");
  if (!j || !r) {
    notify("请先确认岗位 JD 和简历");
    selectTab("prepare");
    return;
  }
  if (pendingMode.value === "practice") {
    const seed = Object.entries(fixtures.results.practices).find(
      ([, p]) => p.task === taskId.value,
    );
    const source = String(
      route.query.source || `interview-${seed?.[1].source || 6}`,
    );
    if (!startSession(j, r, 2, "practice", taskId.value, source)) return;
  } else if (!startSession(j, r, count.value)) return;
  router.push("/interview/room");
}
function newJD() {
  if (jobBusy.value) return;
  draft.value = blankJob();
  openJobId.value = "";
  history.value = false;
  jdError.value = "";
}
</script>
<template>
  <AppShell :title="'面试'"
    ><section class="ui-panel interview-panel">
      <div class="ui-tabs" role="tablist" aria-label="面试功能">
        <button
          v-for="item in [
            { id: 'jobs', name: '岗位 JD' },
            { id: 'prepare', name: '模拟面试' },
            { id: 'tasks', name: '薄弱项复练' },
          ]"
          :key="item.id"
          role="tab"
          :aria-selected="tab === item.id"
          :class="{ active: tab === item.id }"
          @click="selectTab(item.id)"
        >
          {{ item.name }}
        </button>
      </div>
      <SlidingTabs
        :active="
          tab === 'jobs' ? (history ? 'jobs-history' : 'jobs-editor') : tab
        "
        :order="['jobs-editor', 'jobs-history', 'prepare', 'tasks']"
      >
        <template v-if="tab === 'jobs' && history"
          ><div class="panel-heading">
            <h2>历史 JD</h2>
            <button
              class="ui-button primary"
              :disabled="jobBusy"
              @click="newJD"
            >
              <UiIcon name="plus" :size="17" />新增 JD
            </button>
          </div>
          <div ref="jobPanel" class="jd-history ui-scroll">
            <article
              v-for="item in jobList"
              :key="item.id"
              class="jd-history-row"
              :class="{ expanded: openJobId === item.id }"
              :data-record="item.id"
            >
              <div class="jd-history-head">
                <span class="file-tile" data-record-part="layout"
                  ><UiIcon
                    name="file"
                    data-record-part="icon"
                    :size="28"
                  /><small>JD</small></span
                >
                <div class="jd-history-copy" data-record-part="layout">
                  <div class="jd-history-name">
                    <h3 :title="item.title">{{ item.title }}</h3>
                    <span class="ui-badge" :class="item.status">{{
                      {
                        confirmed: "已确认",
                        pending: "待校对",
                        failed: "解析失败",
                      }[item.status]
                    }}</span>
                  </div>
                  <p class="muted-copy">
                    文本录入<span>保存于 {{ item.date }}</span>
                  </p>
                  <div
                    class="record-summary"
                    data-record-part="summary"
                    :aria-hidden="openJobId === item.id"
                  >
                    <small
                      :class="
                        item.status === 'failed' ? 'inline-error' : 'muted-copy'
                      "
                      >{{
                        item.status === "failed"
                          ? "解析失败，可修改原文后重试。"
                          : `${item.role || "岗位待确认"}${item.direction ? " · " + item.direction : ""}`
                      }}</small
                    >
                  </div>
                </div>
                <div class="jd-history-actions" data-record-part="layout">
                  <button
                    class="text-button"
                    :disabled="jobBusy"
                    @click="showRename(item)"
                  >
                    重命名
                  </button>
                  <button
                    class="ui-button"
                    :disabled="jobBusy"
                    :class="{
                      primary:
                        item.status !== 'failed' && openJobId !== item.id,
                    }"
                    :aria-expanded="openJobId === item.id"
                    @click="toggleJob(item)"
                  >
                    {{
                      openJobId === item.id
                        ? item.status === "confirmed"
                          ? "收起编辑"
                          : "收起校对"
                        : item.status === "failed"
                          ? "重新解析"
                          : item.status === "confirmed"
                            ? "编辑"
                            : "校对 JD"
                    }}<UiIcon
                      v-if="item.status !== 'failed'"
                      :name="openJobId === item.id ? 'up' : 'down'"
                      class="collapse-chevron"
                      :size="16"
                    />
                  </button>
                </div>
              </div>
              <CollapseRegion
                :open="openJobId === item.id"
                :available-height="() => jobPanel?.clientHeight || 0"
                animate-header
                @expanded="scrollToJob(item.id)"
              >
                <JobEditor
                  v-if="recordDrafts[item.id]"
                  v-model="recordDrafts[item.id]!"
                  :busy="jobBusy"
                  :error="openJobId === item.id ? jdError || materialError : ''"
                  @invalidate="invalidate"
                  @parse="parse"
                  @save="save"
                />
              </CollapseRegion>
            </article>
            <div v-if="!jobList.length" class="empty-state">暂无保存的 JD</div>
          </div>
          <footer v-if="!openJobId" class="list-footer">
            <span>共 {{ state.jobs.length }} 份 JD</span
            ><Pagination
              v-model="historyPage"
              :total="state.jobs.length"
              :size="3"
            /></footer
        ></template>
        <template v-else-if="tab === 'jobs'"
          ><div class="jd-editor-heading">
            <h2>{{ draft.title }}</h2>
            <span class="ui-badge" :class="draft.status">{{
              !draft.parsed
                ? "待解析"
                : draft.status === "confirmed"
                  ? "已确认"
                  : "待校对"
            }}</span
            ><button
              class="ui-button"
              :disabled="jobBusy"
              @click="history = true"
            >
              历史 JD（{{ state.jobs.length }}）
            </button>
          </div>
          <JobEditor
            v-model="draft"
            :busy="jobBusy"
            :error="jdError || materialError"
            @invalidate="invalidate"
            @parse="parse"
            @save="save"
        /></template>
        <section v-else-if="tab === 'prepare'" class="interview-prepare">
          <div class="interview-materials">
            <h2>确认面试材料</h2>
            <label class="ui-field material-choice"
              ><span>岗位 JD</span>
              <div>
                <select v-model="selectedJob" aria-label="本次岗位JD">
                  <option value="" disabled>选择岗位 JD</option>
                  <option
                    v-for="item in state.jobs.filter(
                      (j) => j.status !== 'failed',
                    )"
                    :key="item.id"
                    :value="item.id"
                  >
                    {{ item.title }} ·
                    {{ item.status === "confirmed" ? "已确认" : "待校对" }}
                  </option></select
                ><button
                  class="text-button"
                  @click="
                    selectTab('jobs');
                    editJob(selectedJob);
                  "
                >
                  {{ job?.status === "confirmed" ? "查看" : "去校对" }}
                </button>
              </div></label
            ><label class="ui-field material-choice"
              ><span>简历</span>
              <div>
                <select v-model="selectedResume" aria-label="本次使用的简历">
                  <option value="" disabled>选择已确认简历</option>
                  <option
                    v-for="item in state.resumes"
                    :key="item.id"
                    :value="item.id"
                    :disabled="item.status !== 'confirmed'"
                  >
                    {{ item.title }} ·
                    {{
                      {
                        confirmed: "已确认",
                        pending: "待校对",
                        failed: "解析失败",
                      }[item.status]
                    }}
                  </option></select
                ><RouterLink class="text-button" to="/resumes"
                  >管理简历</RouterLink
                >
              </div></label
            >
            <div class="count-heading">主问题数量</div>
            <div class="question-count">
              <button
                v-for="n in [3, 5, 8]"
                :key="n"
                :aria-pressed="count === n"
                :class="{ active: count === n }"
                @click="count = n"
              >
                <strong>{{ n }}</strong
                ><span>道</span><small v-if="n === 5">默认</small>
              </button>
            </div>
            <label class="checkbox material-confirm"
              ><input
                v-model="materials"
                type="checkbox"
              />确认使用以上岗位信息和简历</label
            >
            <p
              v-if="
                job?.status !== 'confirmed' || resume?.status !== 'confirmed'
              "
              class="inline-error"
            >
              请先完成所选材料的校对确认。
            </p>
          </div>
          <aside class="interview-plan">
            <h2>本次面试</h2>
            <dl>
              <div>
                <dt>岗位类别</dt>
                <dd>{{ job?.role || "—" }}</dd>
              </div>
              <div>
                <dt>岗位方向</dt>
                <dd>{{ job?.direction || "—" }}</dd>
              </div>
              <div>
                <dt>主问题</dt>
                <dd>{{ count }} 道</dd>
              </div>
              <div>
                <dt>回答方式</dt>
                <dd>语音转文字</dd>
              </div>
              <div>
                <dt>问题播报</dt>
                <dd>语音＋文字</dd>
              </div>
            </dl>
            <p>每题最多追问 2 次，结束后统一反馈。</p>
            <button
              class="ui-button primary"
              :disabled="!ready || starting"
              @click="begin('interview')"
            >
              <UiIcon name="play" :size="18" />进入面试
            </button>
          </aside>
        </section>
        <template v-else
          ><div class="panel-heading">
            <h2>选择复练问题</h2>
            <select
              v-model="taskFilter"
              class="ui-select"
              aria-label="复练状态"
            >
              <option value="pending">待复练</option>
              <option value="all">全部问题</option>
            </select>
          </div>
          <div class="practice-tasks ui-scroll">
            <label
              v-for="task in taskList"
              :key="task.id"
              class="practice-task"
              :class="{ selected: taskId === task.id }"
              ><input
                v-model="taskId"
                type="radio"
                name="practice-task"
                :value="task.id"
              />
              <div>
                <div class="practice-task-title">
                  <strong>{{ task.title }}</strong
                  ><span>{{ task.dimension }}</span>
                </div>
                <p>{{ task.weakness }}</p>
                <small>来自：{{ task.source }} · {{ task.date }}</small>
              </div>
              <span class="ui-badge" :class="{ green: task.done }">{{
                task.done ? "已完成" : "待复练"
              }}</span></label
            >
            <div v-if="!taskList.length" class="empty-state">
              暂无待复练问题
            </div>
          </div>
          <footer class="list-footer">
            <span>共 {{ taskList.length }} 个问题</span
            ><button
              class="ui-button primary"
              :disabled="!taskList.some((t) => t.id === taskId)"
              @click="begin('practice')"
            >
              开始复练<UiIcon name="arrow" :size="17" />
            </button></footer
        ></template>
      </SlidingTabs>
    </section>
    <UiModal
      :open="!!renameTarget"
      title="重命名岗位 JD"
      :busy="jobBusy"
      @close="renameTarget = null"
    >
      <form id="rename-job-form" @submit.prevent="saveRename">
        <label class="ui-field">
          <span>JD 名称</span>
          <input
            v-model="renameTitle"
            :disabled="jobBusy"
            maxlength="180"
            autocomplete="off"
          />
        </label>
        <p class="muted-copy rename-hint">
          仅修改列表名称，岗位内容和版本保持不变。
        </p>
        <p v-if="renameError" class="inline-error" role="alert">
          {{ renameError }}
        </p>
      </form>
      <template #footer>
        <button
          class="ui-button"
          :disabled="jobBusy"
          @click="renameTarget = null"
        >
          取消
        </button>
        <button
          class="ui-button primary"
          form="rename-job-form"
          type="submit"
          :disabled="jobBusy"
        >
          {{ jobBusy ? "保存中…" : "保存" }}
        </button>
      </template>
    </UiModal>
    <UiModal :open="replacing" title="开始新的练习" @close="replacing = false"
      ><p class="confirm-copy">
        当前还有未完成的练习。开始新练习将替换当前草稿，是否继续？
      </p>
      <template #footer
        ><button class="ui-button" @click="replacing = false">取消</button
        ><button class="ui-button primary" @click="launch">
          确认
        </button></template
      ></UiModal
    ></AppShell
  >
</template>
<style scoped>
.interview-panel {
  min-width: 0;
}
.jd-editor-heading {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 28px 14px;
  flex: none;
}
.jd-editor-heading h2 {
  font-size: 1.2em;
  font-weight: 600;
}
.jd-editor-heading .ui-button {
  margin-left: auto;
}
.jd-history {
  flex: 1;
  position: relative;
  overflow-anchor: none;
  scrollbar-gutter: stable;
}
.jd-history-row {
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid #edf0f6;
}
.jd-history-head {
  position: relative;
  flex: none;
  min-height: calc((var(--workspace-height) - 170px) / 3);
  display: flex;
  gap: 20px;
  align-items: center;
  padding: 20px 28px;
}
.jd-history-copy {
  flex: 1;
  min-width: 0;
}
.jd-history-row .ui-button {
  min-width: 132px;
}
.jd-history-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 18px;
}
.jd-history-row.expanded .jd-history-head {
  min-height: 88px;
  padding-top: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e9edf5;
}
.jd-history-row.expanded .file-tile {
  width: 48px;
  height: 54px;
}
.jd-history-row.expanded .file-tile svg {
  width: 24px;
  height: 24px;
}
.jd-history-row :deep(.jd-compare) {
  padding-top: 16px;
}
.jd-history-name {
  display: flex;
  align-items: center;
  gap: 14px;
}
.jd-history-name h3 {
  font-size: 1.2em;
  font-weight: 600;
  min-width: 0;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.jd-history-name .ui-badge {
  flex: none;
}
.rename-hint {
  margin-top: 12px;
  line-height: 1.6;
}
.jd-history-row p {
  margin: 8px 0;
}
.jd-history-row p span {
  margin-left: 20px;
}
.interview-prepare {
  display: grid;
  grid-template-columns: minmax(0, 64fr) minmax(0, 36fr);
  gap: 40px;
  padding: 30px 40px;
  flex: 1;
  min-height: 0;
}
.interview-materials h2,
.interview-plan h2 {
  font-size: var(--ui-title);
  margin-bottom: 22px;
}
.material-choice {
  margin-bottom: 22px;
}
.material-choice > div {
  display: flex;
  align-items: center;
  gap: 16px;
}
.material-choice select {
  flex: 1;
  min-width: 0;
}
.material-choice .text-button {
  width: 64px;
  flex: none;
  font-size: 0.9em;
}
.count-heading {
  color: #667895;
  margin-bottom: 12px;
  font-size: 0.95em;
}
.question-count {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.question-count button {
  position: relative;
  height: 70px;
  border: 1px solid #dee5f0;
  background: white;
  border-radius: 10px;
  color: #667895;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}
.question-count button.active {
  border-color: #9bb3ee;
  background: #f1f5ff;
  color: #5b80e5;
}
.question-count strong {
  font-size: 24px;
}
.question-count small {
  position: absolute;
  right: 8px;
  top: 7px;
  font-size: 10px;
}
.material-confirm {
  margin-top: 22px;
  font-size: 0.9em;
}
.interview-plan {
  padding: 24px;
  border: 1px solid #e4eaf4;
  border-radius: 16px;
  background: #f8faff;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.interview-plan dl > div {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 0;
  border-bottom: 1px solid #edf0f6;
  font-size: 0.92em;
}
.interview-plan dt {
  color: #8292ad;
}
.interview-plan dd {
  text-align: right;
}
.interview-plan p {
  color: #8b98ad;
  font-size: 0.85em;
  line-height: 1.8;
  margin: 18px 0;
}
.interview-plan > .ui-button {
  margin-top: auto;
  min-height: 44px;
}
.practice-tasks {
  flex: 1;
  padding: 8px 28px;
}
.practice-task {
  min-height: calc((var(--workspace-height) - 148px) / 3);
  display: flex;
  align-items: center;
  gap: 18px;
  border-bottom: 1px solid #edf0f6;
  padding: 18px;
  border-radius: 10px;
  cursor: pointer;
}
.practice-task.selected {
  background: #f6f8ff;
}
.practice-task > input {
  accent-color: #5b80e5;
  width: 16px;
  height: 16px;
}
.practice-task > div {
  flex: 1;
}
.practice-task-title {
  display: flex;
  gap: 14px;
  align-items: center;
}
.practice-task-title strong {
  font-size: 1.1em;
  font-weight: 600;
}
.practice-task-title span {
  background: #f3f5fa;
  color: #7b8ead;
  font-size: 0.8em;
  padding: 3px 8px;
  border-radius: 5px;
}
.practice-task p {
  margin: 8px 0;
  color: #71809a;
  line-height: 1.7;
  font-size: 0.92em;
}
.practice-task small {
  color: #9aa6b8;
  font-size: 0.8em;
}
@media (max-width: 1200px) {
  .interview-prepare {
    gap: 24px;
    padding: 24px 28px;
  }
  .interview-plan {
    padding: 20px;
  }
  .jd-history-head {
    gap: 16px;
  }
  .practice-task {
    padding: 14px;
  }
}
@media (max-height: 820px) {
  .interview-prepare {
    padding-top: 20px;
    padding-bottom: 20px;
  }
  .interview-materials h2,
  .interview-plan h2 {
    margin-bottom: 16px;
  }
  .material-choice {
    margin-bottom: 16px;
  }
  .question-count button {
    height: 54px;
  }
  .material-confirm {
    margin-top: 16px;
  }
  .interview-plan dl > div {
    padding: 9px 0;
  }
  .interview-plan p {
    margin: 12px 0;
  }
}
</style>
