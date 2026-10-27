<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import AppShell from "../ui/AppShell.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import CollapseRegion from "../ui/CollapseRegion.vue";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import Pagination from "../ui/Pagination.vue";
import {
  clone,
  emptyFields,
  getFile,
  notify,
  removeFile,
  saveFile,
  state,
  timeLabel,
  uid,
} from "../core/state";
import type { Resume, ResumeFields } from "../core/state";
import { isPreviewMode } from "../core/runtime";
import { errorMessage } from "../core/api";
import {
  uploadResume,
  saveResume,
  renameResume,
  deleteResume,
  resumeFile,
  materialError,
  retryMaterial,
} from "../core/materials";
const uploadKey = ref(crypto.randomUUID());
const page = ref(1),
  openId = ref(""),
  tab = ref("basic"),
  project = ref(0),
  internship = ref(0),
  menu = ref(""),
  panel = ref<HTMLElement>();
const draft = ref<ResumeFields>(emptyFields());
const sourceUrl = ref("");
const visible = computed(() =>
  state.resumes.slice((page.value - 1) * 3, page.value * 3),
);
const modal = ref<"" | "upload" | "rename" | "delete">("");
const modalTitles: Record<string, string> = {
  upload: "上传简历",
  rename: "重命名简历",
  delete: "删除简历",
};
const target = ref<Resume>();
const rename = ref(""),
  error = ref(""),
  busy = ref(false),
  file = ref<File>();
const categories = [
  { id: "basic", title: "基本信息" },
  { id: "education", title: "教育经历" },
  { id: "internships", title: "实习经历" },
  { id: "projects", title: "项目经历" },
  { id: "skills", title: "个人技能" },
];
function menuTrigger() {
  return panel.value?.querySelector<HTMLElement>(
    `[data-record="${CSS.escape(menu.value)}"] .resume-more-trigger`,
  );
}
function closeMenu(restoreFocus = false) {
  const trigger = restoreFocus ? menuTrigger() : undefined;
  menu.value = "";
  if (trigger) nextTick(() => trigger.focus({ preventScroll: true }));
}
function outsideMenu(event: PointerEvent) {
  if (!menu.value || !(event.target instanceof Node)) return;
  const trigger = menuTrigger();
  const popup = trigger
    ?.closest(".resume-record-head")
    ?.querySelector(".resume-menu");
  if (!trigger?.contains(event.target) && !popup?.contains(event.target))
    closeMenu();
}
function escapeMenu(event: KeyboardEvent) {
  if (menu.value && event.key === "Escape") {
    event.preventDefault();
    closeMenu(true);
  }
}
function removeMenuListeners() {
  document.removeEventListener("pointerdown", outsideMenu);
  document.removeEventListener("keydown", escapeMenu);
}
watch(menu, (value) => {
  removeMenuListeners();
  if (value) {
    document.addEventListener("pointerdown", outsideMenu);
    document.addEventListener("keydown", escapeMenu);
  }
});
function clearSource() {
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value);
  sourceUrl.value = "";
}
async function toggle(record: Resume) {
  menu.value = "";
  if (openId.value === record.id) {
    openId.value = "";
    clearSource();
    return;
  }
  openId.value = record.id;
  draft.value = clone(record.fields);
  tab.value = "basic";
  project.value = internship.value = 0;
  clearSource();
  if (isPreviewMode && record.fileKey && record.type === "PDF") {
    try {
      const blob = await getFile(record.fileKey);
      if (blob && openId.value === record.id)
        sourceUrl.value = URL.createObjectURL(blob);
    } catch {
      notify("无法读取本地原文件，请重新上传。");
    }
  }
  await nextTick();
}
function scrollToEditor(id: string) {
  if (openId.value !== id) return;
  const row = panel.value?.querySelector<HTMLElement>(`[data-record="${id}"]`);
  if (row && panel.value)
    panel.value.scrollTo({
      top: row.offsetTop,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
}
function show(kind: "upload" | "rename" | "delete", record?: Resume) {
  if (busy.value) return;
  target.value = record;
  modal.value = kind;
  rename.value = record?.title || "";
  error.value = "";
  file.value = undefined;
  uploadKey.value = crypto.randomUUID();
  menu.value = "";
}
function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0];
  error.value = "";
  uploadKey.value = crypto.randomUUID();
}
async function upload() {
  if (busy.value) return;
  const f = file.value;
  if (!f) {
    error.value = "请选择简历文件";
    return;
  }
  const ext = f.name.split(".").at(-1)?.toUpperCase();
  if (!ext || !["PDF", "DOCX", "TXT"].includes(ext)) {
    error.value = "仅支持 PDF、DOCX、TXT 文件";
    return;
  }
  if (f.size > 10 * 1024 * 1024 || f.size === 0) {
    error.value = f.size === 0 ? "文件为空，请重新选择" : "文件不能超过 10 MB";
    return;
  }
  if (!isPreviewMode) {
    busy.value = true;
    try {
      const record = await uploadResume(f, uploadKey.value, target.value);
      page.value = 1;
      modal.value = "";
      if (record.status === "failed")
        notify(record.errorMessage || "原文提取失败，请重新上传");
      else {
        await toggle(record);
        notify(record.parsingJob?.state === 'succeeded' ? "已解析，请对照原文校对后确认保存"
          : record.parsingJob?.errorMessage || "原文已保留，智能解析尚未完成，可先人工校对");
      }
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      busy.value = false;
    }
    return;
  }
  busy.value = true;
  const owner = state.account.email;
  try {
    const id = target.value?.id || uid("resume");
    // A replacement gets its own blob key, including for shared fixture IDs.
    const fileKey = `${state.account.id}:${uid("file")}`;
    await saveFile(fileKey, f);
    const source = ext === "TXT" ? await f.text() : "";
    if (!state.signedIn || state.account.email !== owner) {
      await removeFile(fileKey);
      return;
    }
    const record: Resume = {
      id,
      title: f.name.replace(/\.[^.]+$/, ""),
      file: f.name,
      type: ext,
      time: timeLabel(),
      status: "pending",
      projects: 0,
      skills: [],
      source,
      fields: emptyFields(),
      fileKey,
    };
    const at = state.resumes.findIndex((r) => r.id === id);
    if (at >= 0) state.resumes.splice(at, 1, record);
    else state.resumes.unshift(record);
    page.value = 1;
    modal.value = "";
    await toggle(record);
    notify(
      ext === "TXT"
        ? "文件已保存，可对照原文填写并确认。"
        : "文件已保存。自动解析待后端接入，可先校对填写。",
    );
  } catch {
    error.value = "文件保存失败，请检查浏览器存储权限后重试。";
  } finally {
    busy.value = false;
  }
}
async function save(record: Resume) {
  if (busy.value) return;
  const { projects, internships, educations = [], ...basic } = draft.value;
  if (
    ![
      ...Object.values(basic),
      ...projects.flatMap(Object.values),
      ...internships.flatMap(Object.values),
      ...educations.flatMap(Object.values),
    ].some((value) => value.trim())
  ) {
    notify("请至少填写一项简历信息后再确认保存");
    return;
  }
  if (!isPreviewMode) {
    busy.value = true;
    try {
      await saveResume(record, clone(draft.value));
      openId.value = "";
      clearSource();
      notify("简历已确认并保存");
    } catch (failure) {
      notify(errorMessage(failure));
    } finally {
      busy.value = false;
    }
    return;
  }
  record.fields = clone(draft.value);
  record.status = "confirmed";
  record.time = timeLabel();
  // Blank reference fields stay blank; editing one material never edits historical sessions.
  record.projects = draft.value.projects.filter((p) => p.name.trim()).length;
  record.skills = draft.value.skills
    .split(/[、,，;；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 6);
  openId.value = "";
  clearSource();
  notify("简历已确认并保存");
}
async function retryParsing(record: Resume) {
  if (busy.value) return;
  busy.value = true;
  try {
    const result = await retryMaterial(record);
    if (result) { draft.value = clone(result.fields); tab.value = "basic"; notify(result.parsingJob?.errorMessage || '智能解析已完成，请对照原文校对'); }
  } catch (e) { notify(errorMessage(e)); }
  finally { busy.value = false; }
}
async function download(record: Resume) {
  try {
    const blob = !isPreviewMode
      ? await resumeFile(record)
      : record.fileKey
        ? await getFile(record.fileKey)
        : undefined;
    if (!blob) {
      notify("这份示例没有原文件，请上传自己的简历。");
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = record.file;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (failure) {
    notify(isPreviewMode ? "原文件读取失败，请重试。" : errorMessage(failure));
  }
  menu.value = "";
}
async function confirmModal() {
  if (modal.value === "upload") return upload();
  if (busy.value) return;
  if (!target.value) return;
  if (!isPreviewMode) {
    if (modal.value === "rename" && !rename.value.trim()) {
      error.value = "请输入简历名称";
      return;
    }
    busy.value = true;
    try {
      if (modal.value === "rename")
        await renameResume(target.value, rename.value.trim());
      if (modal.value === "delete") {
        await deleteResume(target.value);
        if (openId.value === target.value.id) {
          openId.value = "";
          clearSource();
        }
        page.value = Math.min(
          page.value,
          Math.max(1, Math.ceil(state.resumes.length / 3)),
        );
      }
      modal.value = "";
      notify("已保存");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      busy.value = false;
    }
    return;
  }
  if (modal.value === "rename") {
    if (!rename.value.trim()) {
      error.value = "请输入简历名称";
      return;
    }
    target.value.title = rename.value.trim();
    target.value.time = timeLabel();
  }
  if (modal.value === "delete") {
    try {
      if (target.value.fileKey) await removeFile(target.value.fileKey);
      state.resumes = state.resumes.filter((r) => r.id !== target.value?.id);
      if (openId.value === target.value.id) {
        openId.value = "";
        clearSource();
      }
      page.value = Math.min(
        page.value,
        Math.max(1, Math.ceil(state.resumes.length / 3)),
      );
    } catch {
      error.value = "删除失败，请重试";
      return;
    }
  }
  modal.value = "";
  notify("已保存");
}
onBeforeUnmount(() => {
  clearSource();
  removeMenuListeners();
});
</script>
<template>
  <AppShell title="我的简历">
    <template #actions
      ><button
        class="ui-button primary"
        :disabled="busy"
        @click="show('upload')"
      >
        <UiIcon name="upload" :size="18" />上传简历
      </button></template
    >
    <section class="ui-panel resumes-panel">
      <div class="panel-heading">
        <h2>全部简历</h2>
        <span v-if="materialError" class="inline-error" role="alert">{{
          materialError
        }}</span>
        <span v-else class="muted-copy">更新时间 ↓</span>
      </div>
      <div ref="panel" class="resume-list ui-scroll">
        <article
          v-for="record in visible"
          :key="record.id"
          class="resume-record"
          :class="{ expanded: openId === record.id }"
          :data-record="record.id"
        >
          <div class="resume-record-head">
            <span class="file-tile" data-record-part="layout"
              ><UiIcon
                name="file"
                data-record-part="icon"
                :size="30"
              /><small>{{ record.type }}</small></span
            >
            <div class="resume-record-copy" data-record-part="layout">
              <div class="resume-name">
                <h2>{{ record.title }}</h2>
                <span class="ui-badge" :class="record.status">{{
                  {
                    pending: "待校对",
                    confirmed: "已确认",
                    failed: "解析失败",
                  }[record.status]
                }}</span>
              </div>
              <p class="muted-copy">
                {{ record.file }}<span>更新于 {{ record.time }}</span>
              </p>
              <div
                class="record-summary"
                data-record-part="summary"
                :aria-hidden="openId === record.id"
              >
                <p v-if="record.status === 'failed'" class="resume-failure">
                  {{
                    record.errorMessage ||
                    "文件中没有可提取文字，请重新上传文字版文件。"
                  }}
                </p>
                <div v-else class="resume-summary">
                  <span>{{ record.projects }} 个项目</span><i /><span
                    v-for="skill in record.skills"
                    :key="skill"
                    class="resume-skill"
                    >{{ skill }}</span
                  >
                </div>
              </div>
            </div>
            <div class="resume-record-actions" data-record-part="layout">
              <button
                v-if="record.status === 'failed'"
                :disabled="busy"
                class="ui-button resume-toggle"
                @click="show('upload', record)"
              >
                重新上传</button
              ><button
                v-else
                :disabled="busy"
                class="ui-button resume-toggle"
                :class="{ primary: openId !== record.id }"
                :aria-expanded="openId === record.id"
                @click="toggle(record)"
              >
                {{
                  openId === record.id
                    ? record.status === "confirmed"
                      ? "收起编辑"
                      : "收起校对"
                    : record.status === "confirmed"
                      ? "编辑"
                      : "校对简历"
                }}<UiIcon
                  :name="openId === record.id ? 'up' : 'down'"
                  class="collapse-chevron"
                  :size="16"
                /></button
              ><button
                class="icon-button resume-more-trigger"
                :disabled="busy"
                :aria-label="`${record.title}的更多操作`"
                :aria-expanded="menu === record.id"
                @click="menu = menu === record.id ? '' : record.id"
              >
                <UiIcon :name="menu === record.id ? 'close' : 'more'" />
              </button>
            </div>
            <Transition
              name="menu-pop"
              @before-leave="
                (element) => {
                  element.setAttribute('inert', '');
                  element.setAttribute('aria-hidden', 'true');
                }
              "
            >
              <div v-if="menu === record.id" class="resume-menu">
                <button @click="download(record)">下载原文件</button
                ><button @click="show('rename', record)">重命名</button
                ><button class="danger" @click="show('delete', record)">
                  删除简历
                </button>
              </div>
            </Transition>
          </div>
          <CollapseRegion
            :open="openId === record.id"
            :available-height="() => panel?.clientHeight || 0"
            animate-header
            @expanded="scrollToEditor(record.id)"
            ><div class="resume-editor">
              <section class="resume-source">
                <header>简历原文 <button v-if="!isPreviewMode && record.parsingJob?.retryAllowed" class="text-button" :disabled="busy" @click="retryParsing(record)">重试智能解析</button></header>
                <iframe v-if="sourceUrl" :src="sourceUrl" title="简历原文" />
                <div v-else class="resume-paper ui-scroll">
                  {{ record.source }}
                  <p
                    v-if="record.type === 'DOCX' && record.fileKey"
                    class="muted-copy"
                  >
                    DOCX 原文提取待后端接入。
                  </p>
                </div>
              </section>
              <section class="resume-fields">
                <div
                  class="ui-tabs compact-tabs"
                  role="tablist"
                  aria-label="简历字段分类"
                >
                  <button
                    v-for="category in categories"
                    :key="category.id"
                    role="tab"
                    :aria-selected="tab === category.id"
                    :class="{ active: tab === category.id }"
                    @click="tab = category.id"
                  >
                    {{ category.title }}
                  </button>
                </div>
                <SlidingTabs
                  :active="tab"
                  :order="categories.map((category) => category.id)"
                >
                  <fieldset
                    class="resume-fields-scroll ui-scroll"
                    :class="{ 'personal-skills-pane': tab === 'skills' }"
                    :disabled="busy"
                  >
                    <template v-if="tab === 'basic'"
                      ><label class="ui-field"
                        ><span>姓名</span><input v-model="draft.name" /></label
                    ></template>
                    <template v-else-if="tab === 'education'"
                      ><label class="ui-field"
                        ><span>学校</span
                        ><input v-model="draft.school" /></label
                      ><label class="ui-field"
                        ><span>专业</span><input v-model="draft.major" /></label
                      ><label class="ui-field"
                        ><span>就读时间</span
                        ><input v-model="draft.educationDates" /></label
                    ><template v-for="(education, i) in draft.educations || []" :key="i"><h4>教育经历 {{ i + 2 }}</h4><label class="ui-field"><span>学校</span><input v-model="education.school" /></label><label class="ui-field"><span>专业</span><input v-model="education.major" /></label><label class="ui-field"><span>就读时间</span><input v-model="education.dates" /></label><button class="text-button danger" @click="draft.educations?.splice(i, 1)">移除这段教育经历</button></template><button v-if="!isPreviewMode" class="text-button" @click="(draft.educations ||= []).push({ school: '', major: '', dates: '' })">添加教育经历</button></template>
                    <template v-else-if="tab === 'internships'"
                      ><select
                        v-model="internship"
                        class="resume-item-select"
                        aria-label="选择实习经历"
                      >
                        <option
                          v-for="(item, i) in draft.internships"
                          :key="i"
                          :value="i"
                        >
                          实习 {{ i + 1
                          }}{{ item.company ? `：${item.company}` : "" }}
                        </option></select
                      ><template v-if="draft.internships[internship]"
                        ><div class="field-pair">
                          <label class="ui-field"
                            ><span>公司名称</span
                            ><input
                              v-model="
                                draft.internships[internship]!.company
                              " /></label
                          ><label class="ui-field"
                            ><span>实习岗位</span
                            ><input
                              v-model="draft.internships[internship]!.position"
                          /></label>
                        </div>
                        <label class="ui-field"
                          ><span>实习时间</span
                          ><input
                            v-model="
                              draft.internships[internship]!.dates
                            " /></label
                        ><label class="ui-field"
                          ><span>工作内容与个人职责</span
                          ><textarea
                            v-model="
                              draft.internships[internship]!.responsibility
                            "
                          /></label
                        ><label class="ui-field"
                          ><span>成果与依据</span
                          ><textarea
                            v-model="draft.internships[internship]!.result"
                          /></label></template
                    ></template>
                    <template v-else-if="tab === 'projects'"
                      ><select
                        v-model="project"
                        class="resume-item-select"
                        aria-label="选择项目"
                      >
                        <option
                          v-for="(item, i) in draft.projects"
                          :key="i"
                          :value="i"
                        >
                          项目 {{ i + 1
                          }}{{ item.name ? `：${item.name}` : "" }}
                        </option></select
                      ><template v-if="draft.projects[project]"
                        ><label class="ui-field"
                          ><span>项目名称</span
                          ><input
                            v-model="draft.projects[project]!.name" /></label
                        ><label class="ui-field"
                          ><span>个人职责</span
                          ><textarea
                            v-model="draft.projects[project]!.responsibility"
                          /></label
                        ><label class="ui-field"
                          ><span>项目内容与技术方案</span
                          ><textarea
                            v-model="draft.projects[project]!.content"
                          /></label
                        ><label class="ui-field"
                          ><span>结果与依据</span
                          ><textarea
                            v-model="draft.projects[project]!.result"
                          /></label></template
                    ></template>
                    <label v-else class="ui-field personal-skills-field"
                      ><span>个人技能</span><textarea v-model="draft.skills" rows="8" />
                    </label>
                  </fieldset>
                </SlidingTabs>
              </section>
            </div>
            <div class="resume-edit-footer">
              <button
                class="ui-button primary"
                :disabled="busy"
                @click="save(record)"
              >
                {{ busy ? "保存中…" : "确认并保存" }}
              </button>
            </div></CollapseRegion
          >
        </article>
        <div v-if="!visible.length" class="empty-state">暂无简历</div>
      </div>
      <footer v-if="!openId" class="list-footer">
        <span>共 {{ state.resumes.length }} 份简历</span
        ><Pagination v-model="page" :total="state.resumes.length" :size="3" />
      </footer>
    </section>
    <UiModal
      :open="!!modal"
      :title="modalTitles[modal] || ''"
      :busy="busy"
      @close="modal = ''"
      ><template v-if="modal === 'upload'"
        ><label class="resume-upload"
          ><UiIcon name="upload" :size="34" /><strong>{{
            file?.name || "选择简历文件"
          }}</strong
          ><span>PDF、DOCX、TXT · 最大 10 MB</span
          ><input
            type="file"
            accept=".pdf,.docx,.txt"
            :disabled="busy"
            aria-label="选择简历文件"
            @change="selectFile" /></label></template
      ><label v-else-if="modal === 'rename'" class="ui-field"
        ><span>简历名称</span
        ><input
          v-model="rename"
          :disabled="busy"
          maxlength="80"
          @keyup.enter="confirmModal"
      /></label>
      <p v-else class="confirm-copy">
        删除“{{ target?.title }}”？立即移除并停止原文件下载，源材料24小时内清理；已有训练仍保留必要快照、回答和报告，进行中的训练可以继续。
      </p>
      <p class="inline-error" role="alert">{{ error }}</p>
      <template #footer
        ><button class="ui-button" :disabled="busy" @click="modal = ''">
          取消</button
        ><button
          class="ui-button"
          :class="modal === 'delete' ? 'danger' : 'primary'"
          :disabled="busy"
          @click="confirmModal"
        >
          {{ busy ? "保存中…" : modal === "delete" ? "删除" : "确认" }}
        </button></template
      ></UiModal
    >
  </AppShell>
</template>
<style scoped>
.resume-list {
  flex: 1;
  position: relative;
  overflow-anchor: none;
  scrollbar-gutter: stable;
}
.resume-record {
  border-bottom: 1px solid #e9edf5;
  display: flex;
  flex-direction: column;
}
.resume-record.expanded {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.resume-record-head {
  position: relative;
  flex: none;
  display: flex;
  align-items: center;
  gap: 20px;
  min-height: calc((var(--workspace-height) - 116px) / 3);
  padding: 20px 28px;
}
.resume-record-copy {
  flex: 1;
  min-width: 0;
}
.resume-name {
  display: flex;
  align-items: center;
  gap: 14px;
}
.resume-name h2 {
  font-size: 1.2em;
  font-weight: 600;
  line-height: 1.5;
}
.resume-record-copy > .muted-copy {
  margin-top: 7px;
  font-size: 0.8em;
}
.resume-record-copy > .muted-copy > span {
  margin-left: 18px;
}
.resume-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 0.86em;
  color: #667895;
  flex-wrap: wrap;
}
.resume-summary i {
  height: 13px;
  width: 1px;
  background: #dfe5ef;
  margin: 0 4px;
}
.resume-skill {
  font-size: 0.92em;
  color: #7486a5;
  background: #f4f6fa;
  border-radius: 5px;
  padding: 3px 8px;
}
.resume-record-actions {
  display: flex;
  gap: 18px;
  flex: none;
  align-items: center;
}
.resume-toggle {
  min-width: 132px;
}
.resume-failure {
  color: #a77a7a;
  font-size: 0.86em;
  margin-top: 11px;
  line-height: 1.7;
}
.expanded .resume-record-head {
  flex: none;
  min-height: 88px;
  background: #fafbff;
  border-bottom: 1px solid #e9edf5;
  padding-top: 14px;
  padding-bottom: 14px;
}
.expanded .file-tile {
  width: 48px;
  height: 54px;
}
.expanded .file-tile svg {
  width: 24px;
  height: 24px;
}
.resume-editor {
  flex: 1;
  min-height: 160px;
  display: grid;
  grid-template-columns: minmax(0, 35.8fr) minmax(0, 63fr);
  gap: 20px;
  padding: 16px 24px 0;
}
.resume-source,
.resume-fields {
  min-height: 0;
  border: 1px solid #e2e8f2;
  border-radius: 12px;
  overflow: hidden;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.resume-source > header {
  height: 40px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid #edf0f6;
  flex: none;
  color: #344764;
  font-weight: 600;
}
.resume-paper {
  flex: 1;
  padding: 16px 18px;
  font-size: 0.88em;
  color: #6d7c94;
  white-space: pre-wrap;
  line-height: 1.8;
}
.resume-source iframe {
  flex: 1;
  width: 100%;
  border: 0;
  min-height: 0;
}
.resume-fields-scroll {
  flex: 1;
  padding: 12px 16px;
  font-size: 0.88em;
}
.compact-tabs {
  height: 40px;
  gap: 10px;
  padding: 0 12px;
  font-size: 0.88em;
}
.resume-fields .ui-field {
  margin-bottom: 12px;
  gap: 5px;
}
.resume-fields .ui-field input {
  min-height: 35px;
  padding: 7px 10px;
}
.resume-fields .ui-field textarea {
  min-height: 61px;
  padding: 8px 10px;
}
.personal-skills-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.resume-fields .personal-skills-field {
  flex: 1;
  min-height: 0;
  margin-bottom: 0;
}
.resume-fields .personal-skills-field textarea {
  flex: 1;
  min-height: 180px;
}
.resume-item-select {
  width: 100%;
  border: 0;
  background: #f5f7fc;
  border-radius: 6px;
  padding: 7px 10px;
  color: #61779a;
  margin-bottom: 12px;
  font: inherit;
}
.resume-edit-footer {
  flex: none;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  min-height: 56px;
  padding: 6px 24px;
}
.resume-edit-footer .ui-button {
  min-width: 144px;
}
.resume-menu {
  position: absolute;
  right: 24px;
  top: 70%;
  z-index: 5;
  min-width: 132px;
  border: 1px solid var(--line);
  background: white;
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 8px 24px #24344d12;
}
.resume-menu button {
  display: block;
  width: 100%;
  border: 0;
  background: white;
  padding: 8px 12px;
  text-align: left;
  color: #526786;
  font: inherit;
  font-size: 0.9em;
  border-radius: 5px;
}
.resume-menu button:hover {
  background: #f3f6fc;
}
.resume-menu button.danger {
  color: #b57575;
}
.resume-upload {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  min-height: 180px;
  border: 1px dashed #9fb5e9;
  border-radius: 14px;
  background: #f8faff;
  color: #6a83b5;
  cursor: pointer;
  text-align: center;
}
.resume-upload input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  cursor: pointer;
}
.resume-upload span {
  font-size: 12px;
  color: #8292ad;
}
.resume-upload strong {
  max-width: 90%;
  overflow-wrap: anywhere;
}
@media (max-width: 1200px) {
  .resume-record-head {
    gap: 14px;
    padding-left: 22px;
    padding-right: 22px;
  }
  .resume-record-actions {
    gap: 8px;
  }
  .resume-name {
    gap: 9px;
  }
  .resume-summary {
    gap: 6px;
  }
  .compact-tabs {
    gap: 4px;
    padding: 0 8px;
    font-size: 12px;
  }
  .resume-toggle {
    min-width: 116px;
    padding: 0 12px;
  }
  .resume-name h2 {
    font-size: 1.1em;
  }
}
</style>
