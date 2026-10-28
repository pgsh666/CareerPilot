import json
import subprocess
import sys
from threading import BoundedSemaphore

from app.config import BACKEND_DIR
from app.errors import ApiError
from app.models import new_id


class LocalSpeech:
    def __init__(self, settings):
        self.settings = settings
        self.capacity = BoundedSemaphore(1)

    def transcribe(self, path, *, terms=None):
        if not (self.settings.speech_model_directory / "model.bin").is_file():
            raise ApiError(503, "ASR_UNAVAILABLE", "本机离线转写模型尚未就绪，可使用键盘备用作答")
        if not self.capacity.acquire(blocking=False):
            raise ApiError(503, "ASR_BUSY", "语音服务正在处理其他录音，请稍后重试或使用键盘备用作答")
        try:
            try:
                from app.speech_text import clean_terms
                process = subprocess.run(
                    [sys.executable, "-I", str(BACKEND_DIR / "app" / "speech_worker.py"), str(path),
                     str(self.settings.speech_model_directory), str(self.settings.speech_max_seconds)],
                    input=json.dumps({"terms": clean_terms(terms or [])}, ensure_ascii=True).encode(),
                    capture_output=True, timeout=self.settings.speech_timeout_seconds,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
                )
                result = json.loads(process.stdout) if process.returncode == 0 and len(process.stdout) < 200_000 else {"error": "ASR_UNAVAILABLE"}
            except subprocess.TimeoutExpired:
                raise ApiError(504, "ASR_TIMEOUT", "语音转写超时，请重试或使用键盘备用作答") from None
            except (OSError, ValueError):
                raise ApiError(503, "ASR_UNAVAILABLE", "语音转写暂不可用，请重试或使用键盘备用作答") from None
            code = result.get("error")
            if code:
                messages = {"NO_SPEECH": "未识别到有效语音，请重试或使用键盘备用作答",
                            "AUDIO_TOO_LONG": "录音超过本次时长限制，请缩短后重试",
                            "AUDIO_INVALID": "录音格式无法读取，请重新录音"}
                raise ApiError(422 if code in messages else 503, code, messages.get(code, "语音转写暂不可用"))
            if not isinstance(result.get("text"), str) or not result["text"].strip():
                raise ApiError(422, "NO_SPEECH", "没有可提交的转写文字")
            return result
        finally:
            self.capacity.release()

    def tts(self, text):
        root = self.settings.speech_temporary_directory
        root.mkdir(parents=True, exist_ok=True)
        path = root / ("tts-" + new_id() + ".wav")
        try:
            result = subprocess.run(
                ["powershell.exe", "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(BACKEND_DIR / "app" / "tts_worker.ps1")],
                input=json.dumps({"text": text, "output": str(path), "root": str(root.resolve())}, ensure_ascii=True).encode(),
                capture_output=True, timeout=35, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
            )
            if result.returncode or not path.is_file() or path.stat().st_size < 44:
                raise ValueError("Local voice unavailable")
            return path
        except (OSError, ValueError, subprocess.TimeoutExpired):
            path.unlink(missing_ok=True)
            raise ApiError(503, "TTS_UNAVAILABLE", "本机问题播报暂不可用，请重试或阅读题目文字") from None
