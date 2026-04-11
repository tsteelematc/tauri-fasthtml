"""
Downloads the Qwen2.5-0.5B-Instruct Q4_K_M GGUF model (~400 MB) into models/
at the project root. Skips download if the file already exists.

Usage: python scripts/download-model.py
"""

import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
MODEL_FILENAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / MODEL_FILENAME


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(downloaded / total_size * 100, 100)
        mb = downloaded / 1_048_576
        total_mb = total_size / 1_048_576
        print(f"\r  {pct:.1f}%  {mb:.0f} / {total_mb:.0f} MB", end="", flush=True)


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if MODEL_PATH.exists():
        print(f"Model already exists at {MODEL_PATH}, skipping download.")
        return

    print(f"Downloading {MODEL_FILENAME} (~400 MB) from Hugging Face...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, reporthook=_progress)
    print(f"\nModel saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
