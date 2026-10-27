import { ref } from "vue";
import { api, ApiError } from "./api";
import { isPreviewMode } from "./runtime";
import { retryGeneration, type JobState } from "./training";
import {
  clone,
  state,
  type Resume,
  type ResumeFields,
  type Job,
} from "./state";

type ServiceResume = Resume & { updatedAt: string };
type ServiceJob = Job & { updatedAt: string };
export const materialError = ref("");
let epoch = 0;
let pending: { owner: string; value: Promise<void> } | null = null;

function ownerCheck(owner: string) {
  if (!state.signedIn || state.account.id !== owner)
    throw new ApiError("账号已切换，请在原账号查看操作结果", "ACCOUNT_CHANGED");
}
function stamp(value: string) {
  const d = new Date(value);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
const resume = (item: ServiceResume): Resume => ({
  ...item,
  time: stamp(item.updatedAt),
});
const job = (item: ServiceJob): Job => ({
  ...item,
  date: stamp(item.updatedAt),
});

function preserveLocalMaterials(owner: string) {
  const resumes = state.resumes.filter((r) => !r.revision);
  const jobs = state.jobs.filter((j) => !j.revision);
  if (!resumes.length && !jobs.length) return;
  const key = "careerpilot:legacy-materials:v1";
  const saved = JSON.parse(localStorage.getItem(key) || "{}");
  saved[owner] ||= { resumes: clone(resumes), jobs: clone(jobs) };
  localStorage.setItem(key, JSON.stringify(saved));
}

async function all<T>(kind: "resumes" | "jobs") {
  const items: T[] = [];
  let total = 0;
  do {
    const result = await api<{ items: T[]; total: number }>(
      `/materials/${kind}?offset=${items.length}&limit=100`,
    );
    total = result.total;
    items.push(...result.items);
    if (!result.items.length) break;
  } while (items.length < total);
  return items;
}

export async function loadMaterials() {
  if (isPreviewMode || !state.signedIn) return;
  const owner = state.account.id;
  if (pending?.owner === owner) return pending.value;
  const generation = epoch;
  const value = (async () => {
    try {
      const [resumes, jobs] = await Promise.all([
        all<ServiceResume>("resumes"),
        all<ServiceJob>("jobs"),
      ]);
      ownerCheck(owner);
      if (generation !== epoch) return;
      preserveLocalMaterials(owner);
      state.resumes = resumes.map(resume);
      state.jobs = jobs.map(job);
      materialError.value = "";
    } catch (error) {
      if (state.account.id === owner)
        materialError.value =
          error instanceof Error ? error.message : "材料加载失败，请刷新重试";
    }
  })();
  pending = { owner, value };
  try {
    await value;
  } finally {
    if (pending?.value === value) pending = null;
  }
}

async function mutate<T>(action: () => Promise<T>, apply: (result: T) => void) {
  const owner = state.account.id;
  const generation = ++epoch;
  pending = null;
  const result = await action();
  ownerCheck(owner);
  if (generation !== epoch)
    throw new ApiError(
      "材料状态已改变，请刷新查看保存结果",
      "MATERIAL_CHANGED",
    );
  epoch++;
  apply(result);
  materialError.value = "";
  return result;
}
function putResume(item: ServiceResume) {
  const at = state.resumes.findIndex((r) => r.id === item.id);
  if (at >= 0) state.resumes.splice(at, 1, resume(item));
  else state.resumes.unshift(resume(item));
}
function putJob(item: ServiceJob) {
  const at = state.jobs.findIndex((j) => j.id === item.id);
  if (at >= 0) state.jobs.splice(at, 1, job(item));
  else state.jobs.unshift(job(item));
}
async function organize<T extends { id: string; revision?: number }>(
  kind: "resumes" | "jobs",
  material: T,
  retryId?: string,
): Promise<T> {
  const owner = state.account.id;
  if (retryId) await retryGeneration(retryId);
  const result = retryId
    ? { job: { id: retryId } }
    : await api<{ job: JobState }>(
        `/materials/${kind}/${material.id}/model-parse`,
        {
          method: "POST",
          body: { revision: material.revision },
        },
      );
  const deadline = Date.now() + 70_000;
  while (Date.now() < deadline) {
    ownerCheck(owner);
    const job = await api<{ job: JobState }>(`/training/jobs/${result.job.id}`);
    ownerCheck(owner);
    if (["succeeded", "stale", "failed", "paused"].includes(job.job.state))
      break;
    await new Promise((resolve) => setTimeout(resolve, 650));
  }
  const refreshed = await api<{ material: T }>(
    `/materials/${kind}/${material.id}`,
  );
  ownerCheck(owner);
  return refreshed.material;
}
export async function uploadResume(file: File, key: string, target?: Resume) {
  const params = new URLSearchParams({ filename: file.name });
  if (target) {
    params.set("replace_id", target.id);
    params.set("revision", String(target.revision));
  }
  const result = await mutate(
    async () => {
      const result = await api<{ material: ServiceResume }>(
          `/materials/resumes?${params}`,
          {
            method: "POST",
            file,
            headers: { "Idempotency-Key": key },
          },
        ),
        material = result.material;
      if (material.status === "failed" || material.status === "confirmed")
        return result;
      return { material: await organize("resumes", material) };
    },
    (r) => putResume(r.material),
  );
  return state.resumes.find((r) => r.id === result.material.id)!;
}
export async function saveResume(item: Resume, fields: ResumeFields) {
  await mutate(
    () =>
      api<{ material: ServiceResume }>(`/materials/resumes/${item.id}`, {
        method: "PUT",
        body: { revision: item.revision, fields },
      }),
    (r) => putResume(r.material),
  );
}
export async function renameResume(item: Resume, title: string) {
  await mutate(
    () =>
      api<{ material: ServiceResume }>(`/materials/resumes/${item.id}`, {
        method: "PATCH",
        body: { revision: item.revision, title },
      }),
    (r) => putResume(r.material),
  );
}
export async function deleteResume(item: Resume) {
  await mutate(
    () =>
      api(`/materials/resumes/${item.id}`, {
        method: "DELETE",
        body: { revision: item.revision },
      }),
    () => {
      state.resumes = state.resumes.filter((r) => r.id !== item.id);
    },
  );
}
export async function parseJob(item: Job, key: string) {
  const existing = !!item.revision;
  const result = await mutate(
    async () => {
      const result = await api<{ material: ServiceJob }>(
        existing ? `/materials/jobs/${item.id}/parse` : "/materials/jobs",
        {
          method: "POST",
          body: {
            source: item.source,
            ...(existing ? { revision: item.revision } : {}),
          },
          headers: existing ? {} : { "Idempotency-Key": key },
        },
      );
      return { material: await organize("jobs", result.material) };
    },
    (r) => putJob(r.material),
  );
  return job(result.material);
}
export async function retryMaterial(item: Resume) {
  if (!item.parsingJob?.retryAllowed) return;
  await mutate(
    () => organize("resumes", item as ServiceResume, item.parsingJob!.id),
    putResume,
  );
  return state.resumes.find((r) => r.id === item.id);
}
export async function saveJob(item: Job) {
  const fields = Object.fromEntries(
    [
      "name",
      "company",
      "role",
      "direction",
      "responsibilities",
      "requirements",
      "inference",
      "useInference",
    ].map((k) => [k, item[k as keyof Job]]),
  );
  const result = await mutate(
    () =>
      api<{ material: ServiceJob }>(`/materials/jobs/${item.id}`, {
        method: "PUT",
        body: { revision: item.revision, source: item.source, fields },
      }),
    (r) => putJob(r.material),
  );
  return job(result.material);
}
export async function renameJob(item: Job, title: string) {
  const result = await mutate(
    () =>
      api<{ material: ServiceJob }>(`/materials/jobs/${item.id}`, {
        method: "PATCH",
        body: { revision: item.revision, title },
      }),
    (r) => putJob(r.material),
  );
  return job(result.material);
}
export async function resumeFile(item: Resume) {
  const owner = state.account.id;
  const result = await api<Blob>(`/materials/resumes/${item.id}/file`, {
    responseType: "blob",
  });
  ownerCheck(owner);
  return result;
}
