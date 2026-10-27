<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import UiIcon from "../ui/UiIcon.vue";
import UiModal from "../ui/UiModal.vue";
import SlidingTabs from "../ui/SlidingTabs.vue";
import { api, ApiError, errorMessage } from "../core/api";
import { forgetTrainingLease, rememberTrainingLease } from "../core/trainingLease";
import { state } from "../core/state";
import {
  answerTraining,
  endTraining,
  getTraining,
  nextPractice,
  questionAudio,
  resumeTraining,
  retryGeneration,
  saveTrainingDraft,
  speechFault,
  trainingState,
  transcribeAudio,
  type Training,
} from "../core/training";

const route = useRoute(),
  router = useRouter();
const row = ref<Training | null>(null),
  draft = ref(""),
  error = ref(""),
  voiceError = ref("");
const busy = ref(false),
  recording = ref(false),
  transcribing = ref(false),
  speaking = ref(false);
const seconds = ref(0),
  dialog = ref(""),
  loaded = ref(false),
  draftRevision = ref(1);
const writeAccess = ref(false), leaseChecked = ref(false);
const draftRecovery = ref("");
const retryAudio = ref<Blob | null>(null), audioAttempts = ref(0);
let retryReplace = false;
function clearRetryAudio() { retryAudio.value = null; audioAttempts.value = 0; }
const question = computed(() => row.value?.currentQuestion);
const practice = computed(() => row.value?.mode === "practice");
const editable = computed(
  () =>
    practice.value ||
    (!!question.value?.faultId && !question.value?.transcriptId),
);
const accepted = computed(() =>
  row.value?.answers.find((a) => a.question_id === question.value?.id),
);
const canAnswer = computed(
  () =>
    row.value?.status === "active" &&
    writeAccess.value &&
    row.value.phase === "answering" &&
    !accepted.value,
);
const feedback = computed(
  () => row.value?.feedback[String(question.value?.main || 1)],
);
const failed = computed(
  () =>
    row.value?.jobs.filter(
      (j) => j.state === "failed" && !["asr", "tts"].includes(j.kind),
    ) || [],
);
const owner = state.account.id;
let alive = true,
  contextVersion = 0,
  recorder: MediaRecorder | null = null,
  stream: MediaStream | null = null;
let audio: HTMLAudioElement | null = null,
  audioURL = "",
  audioVersion = 0;
let poll: ReturnType<typeof setInterval>, clock: ReturnType<typeof setInterval>;
let saving: Promise<void> | null = null,
  draftTimer: ReturnType<typeof setTimeout>;
let recordTimer: ReturnType<typeof setInterval>,
  startedRecording = 0,
  cancelledRecording = false;
let refreshing = false;
let changingDraft = false;
function setDraft(text: string) {
  changingDraft = true;
  draft.value = text;
  changingDraft = false;
}
const lease = crypto.randomUUID();
let sequence = 0,
  lastActivity = performance.now(),
  wasActive = false;
let activityChain: Promise<void> = Promise.resolve();
const valid = () => alive && state.signedIn && state.account.id === owner;
function draftKey() {
  return question.value && row.value
    ? `careerpilot:answer-draft:v1:${owner}:${row.value.id}:${question.value.id}`
    : "";
}
function backupDraft() {
  if (!valid() || !editable.value || !canAnswer.value || !draftKey()) return;
  try {
    localStorage.setItem(
      draftKey(),
      JSON.stringify({ text: draft.value, revision: draftRevision.value }),
    );
  } catch {
    /* Server autosave remains available. */
  }
}
function restoreLocalDraft() {
  if (!editable.value || !canAnswer.value || !draftKey()) return;
  try {
    const cache = JSON.parse(localStorage.getItem(draftKey()) || "null");
    if (!cache || typeof cache.text !== "string" || cache.text.length > 20000)
      return;
    if (cache.text === question.value?.draft) {
      localStorage.removeItem(draftKey());
      return;
    }
    if (cache.revision === draftRevision.value) draft.value = cache.text;
    else {
      draftRecovery.value = cache.text;
      error.value = "发现与云端版本不同的本机草稿，可核对后恢复。";
    }
  } catch {
    /* An invalid cache never replaces a server draft. */
  }
}
const isTiming = () =>
  valid() &&
  document.visibilityState === "visible" &&
  canAnswer.value &&
  !transcribing.value;
function pulse(stop = false) {
  const id = row.value?.id;
  if (!id || !valid() || !writeAccess.value) return Promise.resolve();
  const now = performance.now(),
    active = !stop && isTiming();
  const elapsed_ms = wasActive
    ? Math.min(8000, Math.max(0, Math.round(now - lastActivity)))
    : 0;
  lastActivity = now;
  wasActive = active;
  const n = ++sequence;
  activityChain = activityChain
    .catch(() => {})
    .then(async () => {
      await api(`/training/sessions/${id}/activity`, {
        method: "POST",
        body: { lease, sequence: n, elapsed_ms, active },
      });
    })
    .catch((e) => {
      if (e instanceof ApiError && ["TRAINING_READ_ONLY", "SESSION_EXPIRED", "TRAINING_NOT_ACTIVE"].includes(e.code)) {
        writeAccess.value = false;
        shutdown();
        error.value = "作答授权已失效，请查看已保存进度后重新接管或登录。";
      }
    });
  return activityChain;
}
function stopSpeaking() {
  audioVersion++;
  audio?.pause();
  audio = null;
  speaking.value = false;
  if (audioURL) URL.revokeObjectURL(audioURL);
  audioURL = "";
}
async function speak() {
  if (recording.value || transcribing.value || !question.value) return;
  if (speaking.value) {
    stopSpeaking();
    return;
  }
  stopSpeaking();
  const version = audioVersion,
    id = question.value.id;
  try {
    const blob = await questionAudio(id);
    if (
      !valid() ||
      version !== audioVersion ||
      id !== question.value?.id ||
      recording.value
    )
      return;
    audioURL = URL.createObjectURL(blob);
    audio = new Audio(audioURL);
    audio.onended = () => stopSpeaking();
    await audio.play();
    speaking.value = true;
    voiceError.value = "";
  } catch {
    stopSpeaking();
    if (valid())
      voiceError.value = "问题播报未开始，可点击重播；题目文字仍可阅读。";
  }
}
function apply(value: Training) {
  if (!valid()) return;
  if (row.value?.id === value.id && row.value.revision > value.revision) return;
  if (value.writeAccess === false && writeAccess.value) {
    writeAccess.value = false;
    contextVersion++;
    cancelRecording();
    stopSpeaking();
    error.value = "本页当前只读，已保存内容保留；需要作答时请确认接管。";
  }
  const previous = question.value?.id;
  const previousKey = draftKey();
  if (previous && value.answers.some((a) => a.question_id === previous)) {
    try {
      localStorage.removeItem(previousKey);
    } catch {
      /* Optional recovery copy. */
    }
  }
  row.value = value;
  if (previous !== value.currentQuestion?.id) {
    clearRetryAudio();
    contextVersion++;
    stopSpeaking();
    setDraft(value.currentQuestion?.draft || "");
    draftRevision.value = value.currentQuestion?.draftRevision || 1;
    draftRecovery.value = "";
    error.value = "";
    restoreLocalDraft();
    voiceError.value = "";
    if (canAnswer.value && document.visibilityState === "visible") void speak();
  } else if (
    value.currentQuestion &&
    !saving &&
    !recording.value &&
    !transcribing.value &&
    !editable.value
  ) {
    setDraft(value.currentQuestion.transcriptText || "");
    draftRevision.value = value.currentQuestion.draftRevision;
  } else if (
    value.currentQuestion &&
    !saving &&
    !recording.value &&
    !transcribing.value &&
    editable.value &&
    value.currentQuestion.draftRevision > draftRevision.value
  ) {
    if (draft.value !== value.currentQuestion.draft && draft.value.trim()) {
      draftRecovery.value = draft.value;
      error.value = "草稿已在另一页面更新；本机文字已保留，可核对后恢复。";
    }
    setDraft(value.currentQuestion.draft);
    draftRevision.value = value.currentQuestion.draftRevision;
  }
  if (value.status === "completed" || value.status === "early_ended")
    void router.replace(
      value.mode === "practice"
        ? `/practice/${value.id}`
        : `/reports/${value.id}`,
    );
}
async function refresh() {
  if (refreshing || !valid() || !row.value) return;
  refreshing = true;
  try {
    const value = await getTraining(row.value.id);
    apply(value);
    // A final receipt survives refresh/network loss and is submitted using one stable key.
    if (
      !practice.value &&
      canAnswer.value &&
      question.value?.transcriptId &&
      !busy.value &&
      !transcribing.value
    )
      await submitVoice();
  } catch (e) {
    if (valid()) error.value = errorMessage(e);
  } finally {
    refreshing = false;
  }
}
async function saveDraft() {
  clearTimeout(draftTimer);
  if (saving) {
    await saving;
    return saveDraft();
  }
  if (
    !valid() ||
    !row.value ||
    !question.value ||
    !editable.value ||
    !canAnswer.value ||
    question.value.draft === draft.value
  )
    return;
  const id = row.value.id,
    q = question.value.id,
    text = draft.value,
    revision = draftRevision.value;
  const pending = (async () => {
    try {
      const result = await saveTrainingDraft(id, q, revision, text);
      if (valid() && question.value?.id === q) {
        draftRevision.value = result.revision;
        question.value.draft = result.text;
        if (draft.value !== result.text) backupDraft();
        else
          try {
            localStorage.removeItem(draftKey());
          } catch {
            /* Optional recovery copy. */
          }
      }
    } catch (e) {
      if (valid() && question.value?.id === q) error.value = errorMessage(e);
      throw e;
    }
  })();
  saving = pending;
  try {
    await pending;
  } finally {
    if (saving === pending) saving = null;
  }
}
watch(
  draft,
  () => {
    if (changingDraft || !editable.value || !canAnswer.value) return;
    backupDraft();
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => void saveDraft().catch(() => {}), 500);
  },
  { flush: "sync" },
);
async function doAction(action: () => Promise<Training>) {
  if (busy.value || !valid()) return;
  busy.value = true;
  error.value = "";
  stopSpeaking();
  try {
    await pulse(true);
    apply(await action());
  } catch (e) {
    if (valid()) error.value = errorMessage(e);
  } finally {
    busy.value = false;
    void pulse();
  }
}
async function acquireWrite(takeover = false) {
  if (!row.value || !valid()) return;
  rememberTrainingLease(row.value.id, lease);
  const result = await api<{ writable: boolean }>(`/training/sessions/${row.value.id}/lease`, {
    method: "POST", body: { lease, takeover },
  });
  writeAccess.value = result.writable;
  leaseChecked.value = true;
  // The last answer can finish the session before the next heartbeat returns.
  // Read that terminal state even when there is no longer a writable lease.
  await refresh();
  if (result.writable) {
    error.value = "";
    restoreLocalDraft();
    void pulse();
  }
}
async function releaseWrite() {
  const id = row.value?.id;
  if (!id || !leaseChecked.value) return;
  try {
    await api(`/training/sessions/${id}/lease`, {
      method: "POST", body: { lease, release: true }, keepalive: true,
    });
  } catch { /* Expiry still prevents a second writer after disconnection. */ }
  forgetTrainingLease(id, lease);
  writeAccess.value = false;
}
async function submitVoice() {
  const s = row.value,
    q = question.value;
  if (!s || !q?.transcriptId || !canAnswer.value) return;
  await doAction(() =>
    answerTraining(
      s.id,
      { question_id: q.id, method: "voice", transcript_id: q.transcriptId! },
      `answer-${q.id}`,
    ),
  );
}
async function submit() {
  const s = row.value,
    q = question.value;
  if (
    !s ||
    !q ||
    !draft.value.trim() ||
    !editable.value ||
    recording.value ||
    transcribing.value
  )
    return;
  try {
    await saveDraft();
  } catch {
    return;
  }
  await doAction(() =>
    answerTraining(
      s.id,
      {
        question_id: q.id,
        method: practice.value && q.transcriptId ? "voice" : "keyboard",
        text: draft.value,
        ...(q.transcriptId ? { transcript_id: q.transcriptId } : {}),
        ...(q.faultId ? { fault_id: q.faultId } : {}),
      },
      `answer-${q.id}`,
    ),
  );
}
async function markFault(reason: string, message: string) {
  if (!valid() || !canAnswer.value || !row.value || !question.value) return;
  error.value = message;
  try {
    const q = question.value,
      result = await speechFault(row.value.id, q.id, reason);
    if (valid() && q.id === question.value?.id) q.faultId = result.faultId;
  } catch (e) {
    if (valid()) error.value = errorMessage(e);
  }
}
function releaseMedia() {
  clearInterval(recordTimer);
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  recorder = null;
  recording.value = false;
}
function cancelRecording() {
  cancelledRecording = true;
  if (recorder?.state === "recording") recorder.stop();
  releaseMedia();
}
async function runTranscription(blob: Blob, replace: boolean, retry = false) {
  if (!row.value || !question.value || !canAnswer.value || transcribing.value) return;
  const id = row.value.id, qid = question.value.id, version = contextVersion;
  const previousDraft = draft.value;
  await pulse(true);
  transcribing.value = true;
  error.value = "";
  try {
    // Resolve an uncertain previous request before sending the audio again.
    if (retry) {
      const current = await getTraining(id);
      apply(current);
      if (current.currentQuestion?.id !== qid || !canAnswer.value) return;
      if (current.currentQuestion.transcriptId) {
        clearRetryAudio();
        setDraft(current.currentQuestion.transcriptText);
        transcribing.value = false;
        if (!practice.value) await submitVoice();
        return;
      }
      if (current.jobs.some(j => j.kind === "asr" && j.state === "running"))
        throw new Error("上次转写仍在处理中，请稍后查询，不重复发送录音");
      if (audioAttempts.value >= 2) throw new Error("同一录音已重试一次，请重新录音或使用键盘备用");
    }
    audioAttempts.value++;
    const receipt = await transcribeAudio(id, qid, blob, crypto.randomUUID(), replace);
    if (!valid() || version !== contextVersion || qid !== question.value?.id) return;
    question.value!.transcriptId = receipt.id;
    question.value!.transcriptText = receipt.text;
    setDraft(receipt.text);
    clearRetryAudio();
    // A successful receipt is final even when the subsequent refresh loses the network.
    if (practice.value) {
      const current = await getTraining(id);
      apply(current);
      draftRevision.value = current.currentQuestion?.draftRevision || draftRevision.value;
      setDraft(receipt.text);
    } else {
      transcribing.value = false;
      await submitVoice();
    }
  } catch (e) {
    if (valid() && version === contextVersion) {
      if (question.value?.transcriptId) {
        clearRetryAudio();
        error.value = `${errorMessage(e)}。转写已成功，保留原文；正式面试可重试提交。`;
      } else {
        setDraft(previousDraft);
        const unusable = e instanceof ApiError && ["NO_SPEECH", "AUDIO_INVALID", "AUDIO_TOO_LONG", "AUDIO_TOO_LARGE"].includes(e.code);
        if (unusable) clearRetryAudio();
        await markFault("transcription_failed", `${errorMessage(e)}。可重新录音或使用键盘备用；可用录音最多手动重试一次。`);
      }
    }
  } finally {
    transcribing.value = false;
    void pulse();
  }
}
async function startRecording(replace = false) {
  if (
    !canAnswer.value ||
    !row.value ||
    !question.value ||
    transcribing.value ||
    busy.value
  )
    return;
  stopSpeaking();
  clearRetryAudio();
  if (
    !navigator.mediaDevices?.getUserMedia ||
    typeof MediaRecorder === "undefined"
  ) {
    await markFault(
      "browser_unsupported",
      "浏览器不支持录音，已开放键盘作答。",
    );
    return;
  }
  const qid = question.value.id,
    version = contextVersion;
  try {
    await saveDraft();
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!valid() || version !== contextVersion || !canAnswer.value) {
      releaseMedia();
      return;
    }
    const chunks: Blob[] = [];
    let bytes = 0;
    const mime = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ].find((t) => MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const media = recorder;
    cancelledRecording = false;
    media.ondataavailable = (e) => {
      if (e.data.size) {
        bytes += e.data.size;
        chunks.push(e.data);
      }
      if (bytes > 10 * 1024 * 1024 && media.state === "recording") media.stop();
    };
    media.onerror = () => {
      cancelRecording();
      void markFault(
        "recording_failed",
        "录音失败，原草稿已保留，可重录或使用键盘。",
      );
    };
    media.onstop = async () => {
      const cancelled = cancelledRecording;
      releaseMedia();
      if (
        cancelled ||
        !valid() ||
        version !== contextVersion ||
        qid !== question.value?.id
      )
        return;
      const blob = new Blob(chunks, { type: media.mimeType });
      if (!blob.size || blob.size > 10 * 1024 * 1024) {
        await markFault("recording_failed", "录音为空或超过10MB，请重录或使用键盘备用。");
        return;
      }
      retryAudio.value = blob;
      retryReplace = replace;
      await runTranscription(blob, replace);
    };
    recorder.start(1000);
    recording.value = true;
    startedRecording = performance.now();
    seconds.value = 0;
    recordTimer = setInterval(() => {
      seconds.value = Math.floor((performance.now() - startedRecording) / 1000);
      if (seconds.value >= 180 && media.state === "recording") media.stop();
    }, 250);
    error.value = "";
  } catch (e) {
    releaseMedia();
    await markFault(
      e instanceof DOMException &&
        ["NotAllowedError", "SecurityError"].includes(e.name)
        ? "permission_denied"
        : "device_unavailable",
      "无法开始录音，请检查麦克风权限和设备；也可使用键盘作答。",
    );
  }
}
function record() {
  if (recording.value) {
    recorder?.stop();
    return;
  }
  if (draft.value.trim()) dialog.value = "replace";
  else void startRecording();
}
async function confirm() {
  const kind = dialog.value;
  dialog.value = "";
  if (kind === "replace") {
    await startRecording(true);
    return;
  }
  if (kind === "draft") {
    draft.value = draftRecovery.value;
    draftRecovery.value = "";
    backupDraft();
    await saveDraft().catch(() => {});
    return;
  }
  if (!row.value) return;
  if (kind === "takeover") {
    await acquireWrite(true).catch((e) => { error.value = errorMessage(e); });
    return;
  }
  if (kind === "resume") {
    await doAction(() =>
      resumeTraining(row.value!.id, trainingState.active?.id),
    );
    await acquireWrite().catch((e) => { error.value = errorMessage(e); });
    return;
  }
  cancelRecording();
  if (kind === "skip" && question.value)
    await doAction(() =>
      answerTraining(
        row.value!.id,
        { question_id: question.value!.id, method: "skip", confirmed: true },
        `answer-${question.value!.id}`,
      ),
    );
  else if (kind === "end") await doAction(() => endTraining(row.value!.id));
}
async function visibility() {
  if (document.visibilityState !== "visible") {
    clearRetryAudio();
    cancelRecording();
    stopSpeaking();
  }
  await pulse(document.visibilityState !== "visible");
}
function shutdown() {
  contextVersion++;
  clearRetryAudio();
  cancelRecording();
  stopSpeaking();
}
function pageHidden() {
  backupDraft();
  shutdown();
  void releaseWrite();
}
onBeforeRouteLeave(async () => {
  shutdown();
  await pulse(true);
  try {
    await saveDraft();
  } catch {
    return false;
  }
  await releaseWrite();
});
onMounted(async () => {
  document.addEventListener("visibilitychange", visibility);
  window.addEventListener("pagehide", pageHidden);
  const id = String(route.query.id || trainingState.active?.id || "");
  if (!id) {
    loaded.value = true;
    error.value = trainingState.error || "没有可继续的训练，请先确认材料。";
    return;
  }
  try {
    const value = await getTraining(id);
    row.value = value;
    if (
      value.status === "interrupted" ||
      (value.mode === "practice" && value.status === "early_ended")
    ) {
      if (trainingState.active && trainingState.active.id !== id)
        dialog.value = "resume";
      else apply(await resumeTraining(id));
    }
    if (row.value?.status === "active") await acquireWrite();
    setDraft(row.value?.currentQuestion?.draft || "");
    draftRevision.value = row.value?.currentQuestion?.draftRevision || 1;
    restoreLocalDraft();
    apply(row.value!);
    await refresh();
    if (canAnswer.value) void speak();
  } catch (e) {
    error.value = errorMessage(e);
  }
  loaded.value = true;
  poll = setInterval(() => {
    if (
      document.visibilityState === "visible" &&
      !recording.value &&
      !transcribing.value &&
      !busy.value
    )
      void (row.value?.status === "active" && !writeAccess.value ? acquireWrite() : refresh());
  }, 1800);
  clock = setInterval(() => void pulse(), 5000);
  void pulse();
});
onBeforeUnmount(() => {
  void pulse(true);
  void releaseWrite();
  alive = false;
  shutdown();
  clearInterval(poll);
  clearInterval(clock);
  clearTimeout(draftTimer);
  document.removeEventListener("visibilitychange", visibility);
  window.removeEventListener("pagehide", pageHidden);
});
</script>
<template>
  <AppShell :title="practice ? '薄弱项复练' : '模拟面试'">
    <template #actions
      ><button
        v-if="row && ['active', 'interrupted'].includes(row.status)"
        class="ui-button"
        :disabled="busy || transcribing || !writeAccess"
        @click="dialog = 'end'"
      >
        {{ practice ? "结束复练" : "结束面试" }}
      </button></template
    >
    <section class="ui-panel room-panel">
      <div v-if="row?.status === 'active' && leaseChecked && !writeAccess" class="inline-error" role="status">
        另一端正在作答，本页只读。已保存的答案和进度可查看。
        <button class="text-button" @click="dialog = 'takeover'">接管作答</button>
      </div>
      <SlidingTabs
        :active="`${row?.currentQuestion?.id || 'preparing'}-${row?.phase}`"
        :order="[]"
      >
        <template v-if="row && question && row.status === 'active' && row.phase === 'answering' && !accepted">
          <div class="room-top">
            <span>{{
              practice
                ? question.main === 1
                  ? "原题复练"
                  : "变式练习"
                : `第 ${question.main} 题 / 共 ${row.count} 道主问题${question.follow ? " · 追问 " + question.follow + " / 2" : ""}`
            }}</span
            ><span>{{ row.job.fields.role }}</span>
          </div>
          <div class="room-question">
            <div>
              <span>面试官</span
              ><button
                class="text-button"
                :disabled="recording || transcribing"
                :aria-pressed="speaking"
                @click="speak"
              >
                <UiIcon name="speaker" :size="18" />{{
                  speaking ? "暂停播报" : "重播问题"
                }}
              </button>
            </div>
            <p>{{ question.text }}</p>
          </div>
          <div class="room-answer-heading">
            <label for="service-answer">你的回答</label
            ><span role="status">{{
              recording
                ? `● 录音中 ${seconds} / 180 秒${seconds >= 150 ? ' · 即将自动停止' : ''}`
                : transcribing
                  ? "转写中…"
                  : !editable
                    ? "语音转写成功后自动提交 · 不可修改"
                    : practice
                      ? "可编辑 · 手动提交"
                      : "语音故障 · 键盘作答"
            }}</span>
          </div>
          <p class="muted-copy">每次录音最长3分钟、10MB；到时自动停止并转写。原始录音仅临时处理。</p>
          <div class="room-answer-wrap">
            <textarea
              id="service-answer"
              v-model="draft"
              aria-label="回答文字"
              maxlength="20000"
              :readonly="!editable || !writeAccess"
              :disabled="recording || transcribing || busy"
            />
            <div v-if="recording || transcribing" class="room-transcribing">
              {{ recording ? "正在录音…" : "正在转写…" }}
            </div>
          </div>
          <div class="room-actions">
            <button
              class="text-button skip-button"
              :disabled="busy || recording || transcribing || !canAnswer"
              @click="dialog = 'skip'"
            >
              跳过本题</button
            ><button
              class="ui-button"
              :class="recording ? 'recording-button' : 'primary'"
              :disabled="
                busy || transcribing || !canAnswer || (!practice && !!question.transcriptId)
              "
              @click="record"
            >
              <UiIcon :name="recording ? 'stop' : 'mic'" :size="19" />{{
                recording ? "结束录音" : draft ? "重新录音" : "开始录音"
              }}</button
            ><button
              v-if="editable"
              class="ui-button primary"
              :disabled="!draft.trim() || busy || recording || transcribing || !canAnswer"
              @click="submit"
            >
              提交回答<UiIcon name="arrow" :size="18" /></button
            ><button
              v-else-if="question.transcriptId"
              class="ui-button primary"
              :disabled="busy || !canAnswer"
              @click="submitVoice"
            >
              重试提交转写
            </button>
          </div>
        </template>
        <div v-else-if="row?.phase === 'feedback'" class="room-feedback">
          <span class="ui-badge green">已提交</span>
          <h2>原题重答反馈</h2>
          <blockquote>{{ accepted?.text }}</blockquote>
          <div class="feedback-placeholders">
            <section
              v-for="group in ['strengths', 'missing'] as const"
              :key="group"
            >
              <h3>{{ group === "strengths" ? "已体现" : "仍需补充" }}</h3>
              <template v-if="feedback"
                ><p v-for="e in feedback[group]" :key="e.quote">
                  「{{ e.quote }}」 {{ e.comment }}
                </p>
                <p v-if="!feedback[group].length">
                  本次未指出该项内容。
                </p></template
              >
              <p v-else>反馈待生成</p>
            </section>
          </div>
          <p v-if="feedback?.comparison">{{ feedback.comparison }}</p>
          <button
            class="ui-button primary"
            :disabled="busy || !writeAccess"
            @click="doAction(() => nextPractice(row!.id))"
          >
            进入变式练习<UiIcon name="arrow" :size="18" />
          </button>
        </div>
        <div v-else class="empty-state">
          <span>{{
            !loaded
              ? "正在恢复训练…"
              : row?.status === "interrupted"
                ? "训练已中途退出，请确认继续。"
                : row?.phase === "advancing"
                  ? "回答已保存，正在生成下一问…"
                  : row
                    ? "正在准备题目…"
                    : "暂无可继续的训练"
          }}</span
          ><RouterLink
            v-if="!row && loaded"
            class="ui-button"
            to="/interview?tab=prepare"
            >前往面试准备</RouterLink
          >
        </div>
      </SlidingTabs>
      <div
        v-for="job in failed"
        :key="job.id"
        class="service-job-error"
        role="alert"
      >
        <span>{{ job.errorMessage || "生成任务未完成，已保存当前进度。" }}</span
        ><button
          v-if="job.retryAllowed"
          class="text-button"
          :disabled="busy"
          @click="
            doAction(async () => {
              await retryGeneration(job.id, row!.id);
              return getTraining(row!.id);
            })
          "
        >
          重试生成
        </button>
      </div>
      <p class="room-error inline-error" role="alert">
        {{ error || voiceError }}
        <button v-if="retryAudio && audioAttempts < 2 && canAnswer" class="text-button"
          :disabled="transcribing || busy" @click="runTranscription(retryAudio!, retryReplace, true)">重试转写一次</button>
        <button
          v-if="draftRecovery && editable"
          class="text-button"
          @click="dialog = 'draft'"
        >
          核对本机草稿
        </button>
      </p>
    </section>
    <UiModal
      :open="!!dialog"
      :busy="busy"
      :title="
        dialog === 'draft'
          ? '恢复本机草稿'
          : dialog === 'replace'
            ? '重新录音'
            : dialog === 'skip'
              ? '跳过本题'
              : dialog === 'resume'
                ? '继续这次训练'
                : dialog === 'takeover'
                  ? '接管作答'
                  : '结束练习'
      "
      @close="dialog = ''"
      ><p class="confirm-copy">
        {{
          dialog === "draft"
            ? "核对以下文字，确认后替换当前未提交草稿。"
            : dialog === "replace"
              ? "重新录音将替换未提交的回答文字，失败时保留原草稿，是否继续？"
              : dialog === "skip"
                ? "本题将不生成评价，是否跳过？"
                : dialog === "resume"
                  ? "当前另有未结束训练，确认替换并恢复这次训练？原进度会保留。"
                  : dialog === "takeover"
                    ? "确认由本页接管作答？另一端将转为只读，以服务端已保存的内容为准。"
                    : "确认结束本次练习？已提交的回答会保留。"
        }}
      </p>
      <blockquote
        v-if="dialog === 'draft'"
        style="white-space: pre-wrap; max-height: 35vh; overflow: auto"
      >
        {{ draftRecovery }}
      </blockquote>
      <template #footer
        ><button class="ui-button" @click="dialog = ''">取消</button
        ><button class="ui-button primary" @click="confirm">
          确认
        </button></template
      ></UiModal
    >
  </AppShell>
</template>
<style scoped src="./room.css"></style>
