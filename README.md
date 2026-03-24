# Tauri + FastHTML Desktop App

A cross-platform desktop application using **Tauri v2** as the native shell and **FastHTML** (Python) as the UI framework. Ships with a bundled Python runtime (python-build-standalone) so no Python installation is required.

## Prerequisites

- **Node.js** 18+
- **Rust** (via rustup)
- **Python 3.10+** (only needed for the setup script, not at runtime)
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
│   └── requirements.txt
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
