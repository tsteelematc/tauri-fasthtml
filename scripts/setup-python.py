"""
Setup script: downloads python-build-standalone and creates a venv with FastHTML.
Run this before `cargo tauri build` or `cargo tauri dev`.

Usage: python scripts/setup-python.py
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# python-build-standalone release
PBS_VERSION = "20250317"
PY_VERSION = "3.12.9"
PBS_BASE_URL = f"https://github.com/indygreg/python-build-standalone/releases/download/{PBS_VERSION}"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_ENV_DIR = PROJECT_ROOT / "src-tauri" / "python-env"
PYTHON_DIR = PYTHON_ENV_DIR / "python"
VENV_DIR = PYTHON_ENV_DIR / "venv"
APP_DIR = PYTHON_ENV_DIR / "app"
MODELS_SRC_DIR = PROJECT_ROOT / "models"
MODELS_DST_DIR = PYTHON_ENV_DIR / "models"

LLAMA_CPP_VERSION = "0.3.19"
LLAMA_CPP_BASE_URL = "https://github.com/abetlen/llama-cpp-python/releases/download"


def get_download_url() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return f"{PBS_BASE_URL}/cpython-{PY_VERSION}+{PBS_VERSION}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
    elif system == "darwin":
        if machine == "arm64":
            return f"{PBS_BASE_URL}/cpython-{PY_VERSION}+{PBS_VERSION}-aarch64-apple-darwin-install_only_stripped.tar.gz"
        else:
            return f"{PBS_BASE_URL}/cpython-{PY_VERSION}+{PBS_VERSION}-x86_64-apple-darwin-install_only_stripped.tar.gz"
    else:
        raise RuntimeError(f"Unsupported platform: {system} {machine}")


def download_and_extract(url: str):
    archive_name = url.split("/")[-1]
    archive_path = PROJECT_ROOT / "scripts" / archive_name

    if PYTHON_DIR.exists():
        print(f"Python already exists at {PYTHON_DIR}, skipping download.")
        return

    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, archive_path)
    print(f"Downloaded to {archive_path}")

    PYTHON_ENV_DIR.mkdir(parents=True, exist_ok=True)

    print("Extracting...")
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(PYTHON_ENV_DIR)

    # python-build-standalone extracts to a 'python' directory
    print(f"Python extracted to {PYTHON_DIR}")

    # Clean up archive
    archive_path.unlink()


def get_python_exe() -> Path:
    if platform.system() == "Windows":
        return PYTHON_DIR / "python.exe"
    return PYTHON_DIR / "bin" / "python3"


def create_venv():
    if VENV_DIR.exists():
        print(f"Venv already exists at {VENV_DIR}, skipping.")
        return

    python_exe = get_python_exe()
    print(f"Creating venv with {python_exe}...")
    subprocess.run([str(python_exe), "-m", "venv", str(VENV_DIR)], check=True)
    print(f"Venv created at {VENV_DIR}")


def get_venv_pip() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def install_dependencies():
    pip = get_venv_pip()
    requirements = PROJECT_ROOT / "python" / "requirements.txt"
    print(f"Installing dependencies from {requirements}...")
    subprocess.run([str(pip), "install", "-r", str(requirements)], check=True)
    print("Dependencies installed.")


def get_llama_cpp_wheel_url() -> str | None:
    """Return a pre-built wheel URL, or None to fall back to source build."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin" and machine == "arm64":
        # cp312 ARM64 wheel (CPU + Metal via llama.cpp's built-in Metal support)
        return (
            f"{LLAMA_CPP_BASE_URL}/v{LLAMA_CPP_VERSION}/"
            f"llama_cpp_python-{LLAMA_CPP_VERSION}-cp312-cp312-macosx_11_0_arm64.whl"
        )
    if system == "windows" and machine in ("amd64", "x86_64"):
        return (
            f"{LLAMA_CPP_BASE_URL}/v{LLAMA_CPP_VERSION}/"
            f"llama_cpp_python-{LLAMA_CPP_VERSION}-cp312-cp312-win_amd64.whl"
        )
    # macOS x64 and Windows ARM64 have no pre-built wheel — source build
    return None


def install_llama_cpp():
    pip = get_venv_pip()
    wheel_url = get_llama_cpp_wheel_url()
    if wheel_url:
        print(f"Installing llama-cpp-python from pre-built wheel...")
        subprocess.run([str(pip), "install", wheel_url], check=True)
    else:
        system = platform.system()
        machine = platform.machine()
        print(f"No pre-built wheel for {system} {machine} — building llama-cpp-python from source.")
        print("  macOS x64: ensure Xcode Command Line Tools are installed (xcode-select --install)")
        print("  Windows ARM64: ensure MSVC Build Tools are installed")
        subprocess.run([str(pip), "install", "llama-cpp-python"], check=True)
    print("llama-cpp-python installed.")


def copy_models():
    if not MODELS_SRC_DIR.exists():
        print(f"No models/ directory found at {MODELS_SRC_DIR} — skipping. Run scripts/download-model.py first.")
        return
    if MODELS_DST_DIR.exists():
        shutil.rmtree(MODELS_DST_DIR)
    shutil.copytree(MODELS_SRC_DIR, MODELS_DST_DIR)
    print(f"Models copied to {MODELS_DST_DIR}")


def copy_app_code():
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    # Copy Python app files
    src = PROJECT_ROOT / "python"
    for f in src.glob("*.py"):
        shutil.copy2(f, APP_DIR / f.name)
    print(f"App code copied to {APP_DIR}")


def main():
    print("=== Tauri + FastHTML Python Environment Setup ===\n")

    url = get_download_url()
    download_and_extract(url)
    create_venv()
    install_dependencies()
    install_llama_cpp()
    copy_app_code()
    copy_models()

    print("\n=== Setup complete! ===")
    print(f"Python env: {PYTHON_ENV_DIR}")
    if not MODELS_DST_DIR.exists():
        print("NOTE: Run 'python scripts/download-model.py' to download the GGUF model before starting the app.")
    print("You can now run: npm run tauri dev")


if __name__ == "__main__":
    main()
