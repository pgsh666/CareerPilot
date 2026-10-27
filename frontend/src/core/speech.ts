import { onBeforeUnmount, ref } from "vue";
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: { length: number; [index: number]: RecognitionResult };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
export function useSpeech(
  getText: () => string,
  setText: (text: string) => void,
) {
  const recording = ref(false),
    transcribing = ref(false),
    speaking = ref(false),
    error = ref(""),
    seconds = ref(0);
  let recognition: Recognition | undefined,
    tick: ReturnType<typeof setInterval> | undefined,
    timeout: ReturnType<typeof setTimeout> | undefined,
    alive = true;
  function stopSpeaking() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    speaking.value = false;
  }
  function speak(text: string) {
    if (recording.value || transcribing.value) return;
    if (speaking.value) {
      stopSpeaking();
      return;
    }
    if (!("speechSynthesis" in window)) {
      error.value = "浏览器不支持问题播报，请阅读问题文字。";
      return;
    }
    error.value = "";
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1;
    utterance.onstart = () => {
      if (alive) speaking.value = true;
    };
    utterance.onend = () => {
      if (alive) speaking.value = false;
    };
    utterance.onerror = (e) => {
      if (alive) {
        speaking.value = false;
        if (e.error !== "canceled" && e.error !== "interrupted")
          error.value = "问题播报失败，可点击重播。";
      }
    };
    speaking.value = true;
    window.speechSynthesis.speak(utterance);
  }
  function start() {
    if (recording.value || transcribing.value) return;
    error.value = "";
    stopSpeaking();
    const Constructor =
      (window as SpeechWindow).SpeechRecognition ||
      (window as SpeechWindow).webkitSpeechRecognition;
    if (!Constructor) {
      error.value = "当前浏览器不支持语音转写，可先在回答区输入文字。";
      return;
    }
    recognition?.abort();
    recognition = new Constructor();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    const previous = getText();
    let received = false;
    let started = false;
    recognition.onstart = () => {
      if (!alive) return;
      started = true;
      recording.value = true;
      seconds.value = 0;
      setText("");
      tick = setInterval(() => seconds.value++, 1000);
    };
    recognition.onresult = (event) => {
      if (!alive) return;
      const parts: string[] = [];
      for (let i = 0; i < event.results.length; i++)
        parts.push(event.results[i][0].transcript);
      if (parts.join("").trim()) {
        received = true;
        setText(parts.join(""));
      }
    };
    recognition.onerror = (event) => {
      if (!alive) return;
      const messages: Record<string, string> = {
        "not-allowed": "未获得麦克风权限，请在浏览器设置中允许后重试。",
        "audio-capture": "未检测到可用麦克风，请检查设备后重试。",
        "no-speech": "未识别到声音，请重试或输入回答。",
        network: "语音转写连接失败，请重试或输入回答。",
        "service-not-allowed": "当前浏览器不允许语音服务，请输入回答。",
      };
      if (event.error !== "aborted")
        error.value =
          messages[event.error] || "语音转写失败，请重试或输入回答。";
    };
    recognition.onend = () => {
      clearInterval(tick);
      clearTimeout(timeout);
      if (!alive) return;
      recording.value = transcribing.value = false;
      if (!received) {
        setText(previous);
        if (started && !error.value) error.value = "未识别到文字，请重新录音。";
      }
    };
    try {
      recognition.start();
    } catch {
      error.value = "无法启动语音转写，请重试。";
    }
  }
  function stop() {
    if (!recording.value) return;
    recording.value = false;
    transcribing.value = true;
    clearInterval(tick);
    recognition?.stop();
    timeout = setTimeout(() => {
      recognition?.abort();
      transcribing.value = false;
      error.value = "转写等待超时，已保留识别到的文字。";
    }, 8000);
  }
  function cancel() {
    clearInterval(tick);
    clearTimeout(timeout);
    recognition?.abort();
    recording.value = transcribing.value = false;
    stopSpeaking();
  }
  onBeforeUnmount(() => {
    alive = false;
    cancel();
  });
  return {
    recording,
    transcribing,
    speaking,
    error,
    seconds,
    speak,
    start,
    stop,
    cancel,
    stopSpeaking,
  };
}
