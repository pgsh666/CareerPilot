import { computed, reactive, ref, watch } from "vue";
import fixtures from "../data/fixtures.json";
import { isPreviewMode } from "./runtime";

export { fixtures };
export type MaterialStatus = "pending" | "confirmed" | "failed";
export interface Project {
  name: string;
  responsibility: string;
  content: string;
  result: string;
}
export interface Internship {
  company: string;
  position: string;
  dates: string;
  responsibility: string;
  result: string;
}
export interface ResumeFields {
  name: string;
  stage: string;
  school: string;
  major: string;
  educationDates: string;
  educations?: { school: string; major: string; dates: string }[];
  skills: string;
  projects: Project[];
  internships: Internship[];
}
export interface Resume {
  id: string;
  title: string;
  file: string;
  type: string;
  time: string;
  status: MaterialStatus;
  projects: number;
  skills: string[];
  source: string;
  fields: ResumeFields;
  fileKey?: string;
  revision?: number;
  version?: number;
  errorMessage?: string;
  parserVersion?: string;
  parsingJob?: { id: string; state: string; errorMessage: string | null; retryAllowed: boolean } | null;
}
export interface Job {
  id: string;
  title: string;
  date: string;
  status: MaterialStatus;
  parsed: boolean;
  analyzedSource: string | null;
  role: string;
  direction: string;
  name: string;
  company: string;
  responsibilities: string;
  requirements: string;
  inference: string;
  source: string;
  useInference: boolean;
  version: number;
  revision?: number;
  parserVersion?: string;
  extractedFields?: Record<string, unknown>;
  parsingJob?: { id: string; state: string; errorMessage: string | null; retryAllowed: boolean } | null;
}
export interface Answer {
  question: string;
  text: string;
  main: number;
  follow: number;
  skipped: boolean;
}
export interface Session {
  id: string;
  mode: "interview" | "practice";
  job: Job;
  resume: Resume;
  count: number;
  main: number;
  follow: number;
  draft: string;
  answers: Answer[];
  stage: "original" | "variant";
  task: string;
  source: string;
  started: string;
  finished: boolean;
  originalText: string;
  variantText: string;
  feedback: boolean;
  minutes: number;
}
export interface SavedRun {
  id: string;
  kind: "interview" | "practice";
  date: string;
  time: string;
  role: string;
  target: string;
  version: string;
  number: number;
  title: string;
  status: string;
  score: number | null;
  coverage: number;
  comparable: boolean;
  technical: number | null;
  expression: number | null;
  original: boolean;
  variant: boolean;
  source: string;
  session: Session;
}
export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: string;
  enabled: boolean;
  closed?: boolean;
  self: boolean;
  registered: string;
  lastSeen: string;
  interviews: number | null;
  practices: number | null;
}
interface State {
  schema: number;
  account: {
    id: string;
    name: string;
    email: string;
    avatar: string;
    avatarUrl?: string | null;
    role: "user" | "admin";
  };
  signedIn: boolean;
  resumes: Resume[];
  jobs: Job[];
  jobDraft: Job | null;
  session: Session | null;
  runs: SavedRun[];
  completedTasks: string[];
  adminUsers: AdminUser[];
}
const key = isPreviewMode
  ? "careerpilot:frontend:v2"
  : "careerpilot:service:v1";
type AccountData = Pick<
  State,
  | "account"
  | "resumes"
  | "jobs"
  | "jobDraft"
  | "session"
  | "runs"
  | "completedTasks"
>;
// Keep the active-state key compatible with older previews; archive each identity
// in the same JSON write so a role switch cannot mix two accounts' materials.
let accounts: Record<string, AccountData> = Object.create(null);
const observed: Record<string, AccountData> = Object.create(null);
const accountKey = (account: State["account"]) =>
  isPreviewMode
    ? `${account.role}:${account.email.trim().toLowerCase()}`
    : account.id;
function accountData(value: State): AccountData {
  return clone({
    account: value.account,
    resumes: value.resumes,
    jobs: value.jobs,
    jobDraft: value.jobDraft,
    session: value.session,
    runs: value.runs,
    completedTasks: value.completedTasks,
  });
}
function validAccountData(
  value: Partial<AccountData> | null,
): value is AccountData {
  return !!(
    value?.account &&
    typeof value.account.email === "string" &&
    ["user", "admin"].includes(value.account.role) &&
    Array.isArray(value.resumes) &&
    Array.isArray(value.jobs) &&
    Array.isArray(value.runs)
  );
}
export const emptyProject = (): Project => ({
  name: "",
  responsibility: "",
  content: "",
  result: "",
});
export const emptyFields = (projects = 1): ResumeFields => ({
  name: "",
  stage: "",
  school: "",
  major: "",
  educationDates: "",
  skills: "",
  projects: Array.from({ length: projects }, emptyProject),
  internships: [
    { company: "", position: "", dates: "", responsibility: "", result: "" },
  ],
});
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
export const uid = (prefix: string) =>
  `${prefix}-${globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2)}`;
export function timestamp() {
  const d = new Date();
  return {
    date: [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
    ].join("."),
    time: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
  };
}
export const timeLabel = () => {
  const t = timestamp();
  return `${t.date} ${t.time}`;
};
export const blankJob = (): Job => ({
  id: uid("jd"),
  title: "新增岗位 JD",
  date: "",
  status: "pending",
  parsed: false,
  analyzedSource: null,
  role: "",
  direction: "",
  name: "",
  company: "",
  responsibilities: "",
  requirements: "",
  inference: "",
  source: "",
  useInference: false,
  version: 1,
});
function initial(): State {
  const resumes: Resume[] = [
    {
      id: "backend",
      title: "后端开发 · 校招版",
      file: "简历_后端校招.pdf",
      type: "PDF",
      time: "2026.10.22 18:40",
      status: "pending",
      projects: 2,
      skills: ["Python", "FastAPI", "MySQL", "Git"],
      source: "",
      fields: emptyFields(2),
    },
    {
      id: "ai",
      title: "AI 应用开发 · 项目强化版",
      file: "简历_AI应用开发.docx",
      type: "DOCX",
      time: "2026.10.21 15:20",
      status: "confirmed",
      projects: 3,
      skills: ["Python", "RAG", "LangChain", "向量检索"],
      source: "",
      fields: emptyFields(3),
    },
    {
      id: "failed",
      title: "简历 · 导出副本",
      file: "简历_导出副本.pdf",
      type: "PDF",
      time: "2026.10.20 20:10",
      status: "failed",
      projects: 0,
      skills: [],
      source: "",
      fields: emptyFields(),
    },
  ];
  return {
    schema: 2,
    account: isPreviewMode
      ? {
          id: "preview-user",
          name: "xxx",
          email: "user@example.com",
          avatar: "default",
          role: "user",
        }
      : { id: "", name: "", email: "", avatar: "default", role: "user" },
    signedIn: false,
    resumes: isPreviewMode ? resumes : [],
    jobs: isPreviewMode
      ? fixtures.interview.jobs.map((j) => ({
          ...j,
          status: j.status as MaterialStatus,
          analyzedSource: j.parsed ? j.source : null,
          useInference: false,
          version: 1,
        }))
      : [],
    jobDraft: null,
    session: null,
    runs: [],
    completedTasks: [],
    adminUsers: isPreviewMode ? clone(fixtures.admin.users) : [],
  };
}
function load(): State {
  const fallback = initial();
  try {
    const raw = JSON.parse(localStorage.getItem(key) || "null");
    if (!isPreviewMode) {
      // Cache only account-owned drafts. An HTTP session is verified before any restoration.
      for (const value of Object.values(raw?.accounts || {})) {
        if (validAccountData(value as AccountData)) {
          const data = value as AccountData;
          if (typeof data.account.id === "string" && data.account.id)
            accounts[data.account.id] = data;
        }
      }
      return fallback;
    }
    if (raw?.schema === 2 && validAccountData(raw as AccountData)) {
      if (raw.accounts && typeof raw.accounts === "object")
        for (const value of Object.values(raw.accounts)) {
          if (validAccountData(value as AccountData)) {
            const data = value as AccountData;
            accounts[accountKey(data.account)] = {
              ...accountData(fallback),
              ...data,
            };
          }
        }
      const { accounts: _archive, ...active } = raw;
      // Migrate the legacy shared preview into its last active account without
      // discarding profile edits, uploads, drafts or completed sessions.
      const restored = { ...fallback, ...active };
      accounts[accountKey(restored.account)] = accountData(restored);
      return restored;
    }
  } catch {
    /* Missing or malformed local preview state starts cleanly. */
  }
  return fallback;
}
export const state = reactive<State>(load());
export const storageError = ref("");
function mergeServiceArchives() {
  if (isPreviewMode) return;
  try {
    const latest = JSON.parse(localStorage.getItem(key) || "null");
    for (const value of Object.values(latest?.accounts || {}))
      if (validAccountData(value as AccountData)) {
        const data = value as AccountData;
        if (typeof data.account.id === "string" && data.account.id)
          accounts[data.account.id] = data;
      }
  } catch {
    /* Preserve the current in-memory drafts if storage is unavailable. */
  }
}
function persist() {
  if (!isPreviewMode && (!state.signedIn || !state.account.id)) return;
  const current = accountData(state);
  const identity = accountKey(state.account);
  if (!isPreviewMode) {
    mergeServiceArchives();
    const previous = observed[identity],
      latest = accounts[identity];
    // A stale tab must not overwrite fields it did not edit in another tab's newer archive.
    if (previous && latest)
      for (const field of [
        "resumes",
        "jobs",
        "jobDraft",
        "session",
        "runs",
        "completedTasks",
      ] as const)
        if (JSON.stringify(current[field]) === JSON.stringify(previous[field]))
          Object.assign(current, { [field]: clone(latest[field]) });
    observed[identity] = accountData(state);
  }
  accounts[identity] = current;
  try {
    localStorage.setItem(
      key,
      JSON.stringify(
        isPreviewMode ? { ...state, accounts } : { schema: 1, accounts },
      ),
    );
    storageError.value = "";
  } catch {
    storageError.value = "浏览器存储不可用，刷新后本次修改可能丢失。";
  }
}
watch(state, persist, { deep: true });
export function activatePreviewAccount(email: string) {
  if (!isPreviewMode) throw new Error("演示账号不能用于在线登录");
  persist();
  const address = email.trim().toLowerCase();
  const admin = address === "admin@example.com";
  const account: State["account"] = {
    id: admin ? "user-4" : "preview-user",
    name: admin ? "管理员" : "xxx",
    email: address,
    avatar: "default",
    role: admin ? "admin" : "user",
  };
  const saved = accounts[accountKey(account)];
  const next = saved ? clone(saved) : { ...accountData(initial()), account };
  Object.assign(state, next, { signedIn: true });
  persist();
}

export type ServiceAccount = State["account"];
export function activateServiceAccount(account: ServiceAccount) {
  if (isPreviewMode) return;
  if (state.signedIn && state.account.id === account.id) {
    state.account = { ...account };
    return;
  }
  persist();
  mergeServiceArchives();
  const saved = accounts[account.id];
  Object.assign(state, saved ? clone(saved) : accountData(initial()), {
    account: { ...account },
    signedIn: true,
    adminUsers: [],
  });
  persist();
}

export function clearServiceAccount() {
  if (isPreviewMode) {
    signOut();
    return;
  }
  // Archive drafts before clearing visible data; keep server-ID identity across email changes.
  persist();
  Object.assign(state, initial());
}
export const toast = ref("");
let toastTimer: ReturnType<typeof setTimeout>;
export function notify(message: string) {
  toast.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = ""), 3000);
}
export const tasks = computed(() =>
  (isPreviewMode ? fixtures.interview.tasks : []).map((t) => ({
    ...t,
    done: state.completedTasks.includes(t.id),
  })),
);
export const roleIds: Record<string, string> = {
  后端开发: "backend",
  前端开发: "frontend",
  软件测试: "testing",
  "AI 产品经理": "product",
  "AI 应用开发": "application",
};
export function startSession(
  job: Job,
  resume: Resume,
  count: number,
  mode: "interview" | "practice" = "interview",
  task = "",
  source = "",
) {
  if (!isPreviewMode) {
    notify("面试服务尚未接入，请稍后重试");
    return null;
  }
  state.session = {
    id: uid(mode),
    mode,
    job: clone(job),
    resume: clone(resume),
    count,
    main: 1,
    follow: 0,
    draft: "",
    answers: [],
    stage: "original",
    task,
    source,
    started: new Date().toISOString(),
    finished: false,
    originalText: "",
    variantText: "",
    feedback: false,
    minutes: 0,
  };
  return state.session;
}
export function finishSession(early = false): string | undefined {
  const s = state.session;
  if (!s) return;
  const existing = state.runs.findIndex((r) => r.id === s.id);
  s.finished = true;
  s.minutes = Math.max(
    1,
    Math.ceil((Date.now() - Date.parse(s.started)) / 60000),
  );
  const t = timestamp();
  const answered = new Set(
    s.answers.filter((a) => !a.skipped && a.text.trim()).map((a) => a.main),
  ).size;
  const run: SavedRun = {
    id: s.id,
    kind: s.mode,
    ...t,
    role: roleIds[s.job.role] || "backend",
    target: `${s.job.id}-v${s.job.version}`,
    version: "pending",
    number:
      existing >= 0
        ? state.runs[existing]!.number
        : state.runs.filter((r) => r.kind === s.mode).length + 1,
    title:
      s.mode === "interview"
        ? `${s.job.role} · 模拟面试`
        : tasks.value.find((task) => task.id === s.task)?.title || "薄弱项复练",
    status:
      s.mode === "practice"
        ? s.variantText
          ? "completed"
          : "active"
        : early
          ? "ended"
          : "completed",
    score: null,
    coverage: Math.round((answered / s.count) * 100),
    comparable: false,
    technical: null,
    expression: null,
    original: !!s.originalText,
    variant: !!s.variantText,
    source: s.source,
    session: clone(s),
  };
  if (existing >= 0) state.runs.splice(existing, 1, run);
  else state.runs.unshift(run);
  if (
    s.mode === "practice" &&
    s.originalText &&
    s.variantText &&
    !state.completedTasks.includes(s.task)
  )
    state.completedTasks.push(s.task);
  return s.id;
}
export function signOut() {
  state.signedIn = false;
  state.session = null;
  persist();
}

// Local files are kept separately from JSON state so larger uploads do not exhaust localStorage.
async function fileDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const r = indexedDB.open("careerpilot-files-v2", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function saveFile(key: string, file: File) {
  const db = await fileDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      tx.objectStore("files").put(file, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
export async function getFile(key: string): Promise<Blob | undefined> {
  const db = await fileDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("files");
      const r = tx.objectStore("files").get(key);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  } finally {
    db.close();
  }
}
export async function removeFile(key: string) {
  const db = await fileDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      tx.objectStore("files").delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
