"""Private short-lived offline transcription. Raw recordings are not retained."""
import json
import logging
import math
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND / ".speech-deps"), str(BACKEND), str(BACKEND / ".deps")]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
logging.disable(logging.CRITICAL)


def transcribe(path, model_dir, maximum, terms=None):
    import av
    import numpy as np
    from faster_whisper import WhisperModel

    from app.speech_text import decoder_options, normalize_transcript
    samples = []
    count = 0
    with av.open(path) as container:
        if not container.streams.audio:
            raise ValueError("AUDIO_INVALID")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                values = converted.to_ndarray().flatten()
                count += len(values)
                if count > maximum * 16000:
                    raise ValueError("AUDIO_TOO_LONG")
                samples.append(values)
    if count < 1600:
        raise ValueError("NO_SPEECH")
    audio = np.concatenate(samples).astype(np.float32) / 32768.0
    if float(np.max(np.abs(audio))) < 0.001:
        raise ValueError("NO_SPEECH")
    model = WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=4,
                         num_workers=1, local_files_only=True)
    segments, _ = model.transcribe(audio, **decoder_options(terms))
    text = normalize_transcript("".join(segment.text for segment in segments))
    if not text:
        raise ValueError("NO_SPEECH")
    if len(text) > 20_000:
        raise ValueError("AUDIO_TOO_LONG")
    return {"text": text, "seconds": math.ceil(count / 16000), "provider": "local-whisper-small-v2"}


if __name__ == "__main__":
    try:
        payload = sys.stdin.buffer.read(8193) if not sys.stdin.isatty() else b""
        if len(payload) > 8192:
            raise ValueError("ASR_UNAVAILABLE")
        terms = json.loads(payload).get("terms", []) if payload else []
        result = transcribe(sys.argv[1], sys.argv[2], int(sys.argv[3]), terms)
    except Exception as error:
        known = {"AUDIO_INVALID", "AUDIO_TOO_LONG", "NO_SPEECH"}
        result = {"error": str(error) if isinstance(error, ValueError) and str(error) in known else "ASR_UNAVAILABLE"}
    print(json.dumps(result, ensure_ascii=True))
