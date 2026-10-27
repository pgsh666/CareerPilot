"""Download public offline ASR weights into this project; no paid API or user token."""
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND / ".speech-deps")]
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"

from huggingface_hub import HfApi, snapshot_download  # noqa: E402


def main():
    root = BACKEND / "data" / "models" / "whisper-small"
    revision = HfApi(token=False).model_info("Systran/faster-whisper-small").sha
    snapshot_download("Systran/faster-whisper-small", revision=revision, local_dir=root,
                      allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                      "tokenizer.json", "vocabulary.*"], token=False, max_workers=2)
    files = {}
    for path in root.iterdir():
        if not path.is_file() or path.name == "manifest.json":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files[path.name] = digest.hexdigest()
    (root / "manifest.json").write_text(json.dumps({"source": "Systran/faster-whisper-small",
                                                  "revision": revision, "sha256": files}, indent=2), encoding="utf-8")
    print("Offline ASR weights prepared; no paid API calls.")


if __name__ == "__main__":
    main()
