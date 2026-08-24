# Tauri + FastHTML Desktop App

A cross-platform desktop application using **Tauri v2** as the native shell and **FastHTML** (Python) as the UI framework. Ships with a bundled Python runtime (python-build-standalone) so no Python installation is required.

## Prerequisites

- **Node.js** 18+
- **Rust** (via rustup)
- **Python 3.10+** (only needed for the setup script, not at runtime)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** (used by `scripts/setup-python.py` to create venvs and install dependencies)
- **Windows** or **macOS**

## Quick Start

```bash
# 1. Install npm dependencies
npm install

# 2. Download Python runtime & create venv with FastHTML
python scripts/setup-python.py

# 3. Run in dev mode
npm run tauri dev

# 4. Build for production
npm run tauri build
```

### Editor setup (avoiding import errors in `python/server.py`)

For IntelliSense/Pylance to resolve imports when editing `python/server.py`, create a local
editor-only virtual environment with `uv` (kept separate from the bundled runtime venv):

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r python/pyproject.toml
```

VS Code is already configured (see `.vscode/settings.json`) to use `.venv` as the default
interpreter. `.venv/` is gitignored — rerun the two commands above after pulling if
dependencies change.

## Architecture

```
Tauri (Rust) → spawns bundled Python → FastHTML serves UI on localhost:5001
             → Webview loads loading page → redirects to FastHTML when ready
```

## Project Structure

```
├── frontend/           # Loading page shown while Python starts
│   └── index.html
├── python/             # FastHTML application source
│   ├── server.py       # Counter app
│   ├── pyproject.toml  # Python deps, managed with uv
│   └── uv.lock
├── scripts/
│   └── setup-python.py # Downloads python-build-standalone + creates venv
├── src-tauri/
│   ├── src/main.rs     # Tauri app: spawns Python, manages lifecycle
│   ├── tauri.conf.json
│   ├── Cargo.toml
│   ├── capabilities/
│   └── python-env/     # (generated) bundled Python + venv + app code
└── package.json
```

## macOS Build Notes

The same `scripts/setup-python.py` works on macOS. It auto-detects the platform and downloads the correct python-build-standalone (x64 or ARM64).

```bash
# On macOS
python3 scripts/setup-python.py
npm run tauri dev
```
