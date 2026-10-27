"""Synthetic local SAPI -> Whisper check; raw WAV always deleted, no cloud call."""
import json
import sys
from pathlib import Path
from time import perf_counter

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / '.deps')]

if __name__ == '__main__':
    from app.config import Settings
    from app.errors import ApiError
    from app.speech_service import LocalSpeech

    speech = LocalSpeech(Settings())
    phrase = '请介绍一下这个项目的背景，以及你负责的部分。'
    path = None
    outcome = {'source': 'synthetic SAPI audio, not a human microphone', 'modelCalls': 0, 'expectedText': phrase}
    try:
        started = perf_counter()
        path = speech.tts(phrase)
        outcome['ttsMs'] = round((perf_counter() - started) * 1000, 2)
        outcome['audioBytes'] = path.stat().st_size
        started = perf_counter()
        outcome['transcription'] = speech.transcribe(path)
        outcome['coldAsrMs'] = round((perf_counter() - started) * 1000, 2)
        outcome['passed'] = bool(outcome['transcription']['text'])
    except ApiError as error:
        outcome['passed'], outcome['error'] = False, error.code
    finally:
        if path:
            path.unlink(missing_ok=True)
        (BACKEND.parent / 'artifacts' / 'prd-release' / 'speech-loopback.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
    if not outcome['passed']:
        raise SystemExit(1)
