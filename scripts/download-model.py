"""
Downloads the Qwen2.5-3B-Instruct Q4_K_M GGUF model (~2 GB) into models/
at the project root. Resumes partial downloads automatically.

Tries curl first (best resume + SSL support), then falls back to Python
with chunked streaming and automatic retry on transient errors.

Usage: python scripts/download-model.py
"""

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
    "qwen2.5-3b-instruct-q4_k_m.gguf"
)
MODEL_FILENAME = "qwen2.5-3b-instruct-q4_k_m.gguf"
EXPECTED_SIZE_BYTES = 2_107_994_272  # ~2 GB; used only for completion check

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / MODEL_FILENAME

MAX_RETRIES = 5
CHUNK_SIZE = 1 << 20  # 1 MiB


def _is_complete() -> bool:
    return MODEL_PATH.exists() and MODEL_PATH.stat().st_size >= EXPECTED_SIZE_BYTES


def _download_with_curl() -> bool:
    """Use curl -C - to resume. Returns True on success."""
    cmd = [
        "curl",
        "-L",           # follow redirects
        "-C", "-",      # resume from partial file
        "--retry", "5",
        "--retry-delay", "3",
        "-o", str(MODEL_PATH),
        MODEL_URL,
    ]
    result = subprocess.run(cmd)
    return result.returncode == 0


def _download_with_python() -> None:
    """Chunked streaming download with resume and retry."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resume_pos = MODEL_PATH.stat().st_size if MODEL_PATH.exists() else 0
            headers = {"Range": f"bytes={resume_pos}-"} if resume_pos else {}
            req = urllib.request.Request(MODEL_URL, headers=headers)

            with urllib.request.urlopen(req) as resp:
                total = resume_pos + int(resp.headers.get("Content-Length", 0))
                mode = "ab" if resume_pos else "wb"
                downloaded = resume_pos
                with open(MODEL_PATH, mode) as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = min(downloaded / total * 100, 100)
                            mb = downloaded / 1_048_576
                            total_mb = total / 1_048_576
                            print(f"\r  {pct:.1f}%  {mb:.0f} / {total_mb:.0f} MB",
                                  end="", flush=True)
            print()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"\n  Attempt {attempt}/{MAX_RETRIES} failed: {exc}")
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print("  All retries exhausted.")
                sys.exit(1)


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if _is_complete():
        print(f"Model already exists at {MODEL_PATH}, skipping download.")
        return

    if MODEL_PATH.exists():
        print(f"Resuming partial download ({MODEL_PATH.stat().st_size / 1_048_576:.0f} MB already downloaded)...")
    else:
        print(f"Downloading {MODEL_FILENAME} (~2 GB) from Hugging Face...")

    if shutil.which("curl"):
        success = _download_with_curl()
        if not success:
            print("curl failed, falling back to Python downloader...")
            _download_with_python()
    else:
        _download_with_python()

    if _is_complete():
        print(f"Model saved to {MODEL_PATH}")
    else:
        print("Warning: download may be incomplete. Re-run the script to resume.")


if __name__ == "__main__":
    main()
