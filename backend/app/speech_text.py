"""Local script normalization and bounded, source-derived ASR vocabulary."""
import re
from functools import lru_cache

from opencc import OpenCC

TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#._/-]*(?:[ \t]+[A-Za-z][A-Za-z0-9+#._/-]*){0,2}")
CONTACT = re.compile(r"https?://\S+|[\w.+-]+@[\w.-]+", re.I)
STOP = frozenset({"and", "the", "for", "to", "in", "or", "on", "as", "at", "is", "of", "with",
                  "this", "that", "from", "you", "your", "a", "an", "http", "https", "www", "com"})


def clean_terms(values):
    result, seen, size = [], set(), 0
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, str):
            continue
        value = " ".join(value.split()).strip("./")
        key = value.casefold()
        if (not value or len(value) > 40 or not TERM.fullmatch(value) or key in seen
                or key in STOP or re.fullmatch(r"[a-f0-9]{24,}", key)
                or (len(value) == 1 and value not in {"C", "R"})):
            continue
        if size + len(value) + 2 > 512 or len(result) >= 32:
            break
        seen.add(key)
        result.append(value)
        size += len(value) + 2
    return result


def hint_terms(question, resume, job):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    values = [question, *(job.get(key, "") for key in ("requirements", "responsibilities", "direction", "role")),
              *(resume.get(key, "") for key in ("skills", "projects", "internships"))]
    candidates = []
    for value in values:
        for text in strings(value):
            for match in TERM.finditer(CONTACT.sub(" ", text[:200_000])):
                candidates.append(match[0])
                candidates.extend(match[0].split())
                if len(candidates) >= 256:
                    return clean_terms(candidates)
    return clean_terms(candidates)


@lru_cache(maxsize=1)
def converter():
    return OpenCC("t2s")


def normalize_transcript(text):
    return converter().convert(text).strip()


def decoder_options(terms=None):
    return {"language": "zh", "task": "transcribe", "multilingual": True, "beam_size": 5,
            "temperature": 0.0, "vad_filter": True, "condition_on_previous_text": False,
            "no_speech_threshold": 0.6, "vad_parameters": {"min_silence_duration_ms": 500},
            "initial_prompt": "这是一段简体中文的面试回答，包含英文技术术语。",
            "hotwords": ", ".join(clean_terms(terms or [])) or None}
