import { reactive, watch } from "vue";
import { api, ApiError } from "./api";
import { state } from "./state";
import { isPreviewMode } from "./runtime";
import { trainingLeaseHeaders } from "./trainingLease";

export interface JobState {
  id: string;
  kind: string;
  state: string;
  attempts: number;
  errorCode: string | null;
  errorMessage: string | null;
  retryAllowed: boolean;
}
export interface Evidence {
  answer_id: string;
  quote: string;
  comment: string;
}
export interface Feedback {
  strengths: Evidence[];
  missing: Evidence[];
  comparison?: string;
}
export interface Question {
  id: string;
  text: string;
  main: number;
  follow: number;
  topic: string;
  dimensionIds?: string[] | null;
  referencePoints?: string[] | null;
}
export interface ScoringDimension {
  id: string;
  name: string;
  weight: number;
  score: number | null;
  coverage: number;
  coveredGroups: number;
  plannedGroups: number;
  ratings: {
    questionId: string;
    dimension_id: string;
    level: number | null;
    reason: string;
    evidence: { answer_id: string; quote: string }[];
  }[];
}
export interface ScoringResult {
  version: string;
  state: string;
  score: number | null;
  evidenceCoverage: number;
  answeredGroups: number;
  scorableGroups: number;
  plannedGroups: number;
  completionPercent: number;
  dimensions: ScoringDimension[];
  reasons: string[];
}
export interface CurrentQuestion extends Question {
  draft: string;
  draftRevision: number;
  faultId: string | null;
  keyboardReason: string | null;
  transcriptId: string | null;
  transcriptText: string;
}
export interface AcceptedAnswer {
  id: string;
  question_id: string;
  text: string;
  skipped: boolean;
  method: string;
  rawTranscript: string | null;
  createdAt: string;
}
export interface Task {
  id: string;
  title: string;
  focus: string;
  quote: string;
  suggestion: string;
  sourceId: string;
  questionId: string;
  done: boolean;
}
export interface Training {
  id: string;
  mode: "interview" | "practice";
  status: string;
  phase: string;
  revision: number;
  count: number;
  resume: { id: string; title: string; version: number };
  job: {
    id: string;
    title: string;
    version: number;
    fields: { name: string; role: string; direction: string };
  };
  taskId: string | null;
  sourceId: string | null;
  sourceAnswer: string;
  currentQuestion: CurrentQuestion | null;
  questions: Question[];
  answers: AcceptedAnswer[];
  jobs: JobState[];
  feedback: Record<string, Feedback>;
  reportState: string;
  report: {
    summary: string;
    questions: (Feedback & { question_id: string })[];
    improvements: {
      question_id: string;
      answer_id: string;
      quote: string;
      focus: string;
      suggestion: string;
    }[];
  } | null;
  score: number | null;
  evidenceCoverage: number | null;
  scoreState: string;
  scoreVersion: string;
  scoring: ScoringResult | null;
  scoringRole: string | null;
  writeAccess?: boolean;
  answeredMain: number;
  startedAt: string;
  finishedAt: string | null;
  activeSeconds?: number;
}
interface Summary {
  active: Training | null;
  completedInterviews: number;
  practiceMinutes: number | null;
  minutesState: string;
  tasks: Task[];
}
export const trainingState = reactive<
  Summary & { error: string; loaded: boolean }
>({
  active: null,
  completedInterviews: 0,
  practiceMinutes: 0,
  minutesState: "empty",
  tasks: [],
  error: "",
  loaded: false,
});
let generation = 0;
function actor() {
  return { owner: state.account.id, generation };
}
function guard(a: ReturnType<typeof actor>) {
  if (
    !state.signedIn ||
    state.account.id !== a.owner ||
    generation !== a.generation
  )
    throw new ApiError("账号已切换，旧请求未写入当前页面", "ACCOUNT_CHANGED");
}
watch(
  () => [state.account.id, state.signedIn],
  () => {
    generation++;
    Object.assign(trainingState, {
      active: null,
      completedInterviews: 0,
      practiceMinutes: 0,
      minutesState: "empty",
      tasks: [],
      error: "",
      loaded: false,
    });
  },
  { flush: "sync" },
);
export async function loadTrainingSummary() {
  if (isPreviewMode || !state.signedIn) return;
  const a = actor();
  try {
    const summary = await api<Summary>("/training/summary");
    guard(a);
    Object.assign(trainingState, summary, { error: "", loaded: true });
  } catch (error) {
    if (generation === a.generation)
      trainingState.error =
        error instanceof Error ? error.message : "训练加载失败";
  }
}
async function action(path: string, body: unknown, key?: string) {
  const a = actor();
  const result = await api<{ training: Training }>(path, {
    method: "POST",
    body,
    headers: key ? { "Idempotency-Key": key } : {},
  });
  guard(a);
  accept(result.training);
  return result.training;
}
function accept(row: Training) {
  if (trainingState.active?.id === row.id && trainingState.active.revision > row.revision) return;
  if (row.status === "active" || trainingState.active?.id === row.id)
    trainingState.active = ["completed", "early_ended"].includes(row.status)
      ? null
      : row;
}
export async function getTraining(id: string) {
  const a = actor();
  const result = await api<{ training: Training }>(`/training/sessions/${id}`);
  guard(a);
  accept(result.training);
  return result.training;
}
export const startInterview = (
  resume_id: string,
  job_id: string,
  count: number,
  key: string,
  replace_id?: string,
) =>
  action(
    "/training/interviews",
    {
      resume_id,
      job_id,
      count,
      confirmed: true,
      replace_id: replace_id || null,
    },
    key,
  );
export const startPractice = (
  task_id: string,
  key: string,
  replace_id?: string,
) =>
  action(
    "/training/practices",
    { task_id, replace_id: replace_id || null },
    key,
  );
export const resumeTraining = (id: string, replace_id?: string) =>
  action(`/training/sessions/${id}/resume`, { replace_id: replace_id || null });
export const endTraining = (id: string) =>
  action(`/training/sessions/${id}/end`, { confirmed: true });
export const nextPractice = (id: string) =>
  action(`/training/sessions/${id}/next-stage`, { confirmed: true });
export const answerTraining = (
  id: string,
  body: {
    question_id: string;
    method: "voice" | "keyboard" | "skip";
    text?: string;
    transcript_id?: string;
    fault_id?: string;
    confirmed?: boolean;
  },
  key: string,
) => action(`/training/sessions/${id}/answers`, body, key);
export async function saveTrainingDraft(
  id: string,
  question_id: string,
  revision: number,
  text: string,
) {
  const a = actor();
  const result = await api<{ revision: number; text: string }>(
    `/training/sessions/${id}/draft`,
    { method: "PUT", body: { question_id, revision, text } },
  );
  guard(a);
  return result;
}
export async function speechFault(
  id: string,
  question_id: string,
  reason: string,
) {
  const a = actor();
  const result = await api<{ faultId: string }>(
    `/training/sessions/${id}/speech-fault`,
    { method: "POST", body: { question_id, reason } },
  );
  guard(a);
  return result;
}
export async function transcribeAudio(
  id: string,
  question_id: string,
  audio: Blob,
  key: string,
  replace: boolean,
) {
  const a = actor();
  const params = new URLSearchParams({
    question_id,
    replace_confirmed: String(replace),
  });
  const result = await api<{
    transcript: { id: string; text: string; seconds: number };
  }>(`/training/sessions/${id}/transcripts?${params}`, {
    method: "POST",
    file: audio,
    timeoutMs: 150_000,
    headers: { "Idempotency-Key": key },
  });
  guard(a);
  return result.transcript;
}
export async function questionAudio(id: string) {
  const a = actor();
  const result = await api<Blob>(`/training/questions/${id}/audio`, {
    responseType: "blob",
    timeoutMs: 45_000,
  });
  guard(a);
  return result;
}
export async function retryGeneration(id: string, trainingId?: string) {
  const a = actor();
  const result = await api<{ job: JobState }>(`/training/jobs/${id}/retry`, {
    method: "POST",
    body: { confirmed: true },
    headers: trainingId ? trainingLeaseHeaders(`/training/sessions/${trainingId}`) : {},
  });
  guard(a);
  return result.job;
}
export const statusLabel = (status: string) =>
  ({
    active: "进行中",
    interrupted: "中途退出",
    completed: "已完成",
    early_ended: "提前结束",
  })[status] || status;
