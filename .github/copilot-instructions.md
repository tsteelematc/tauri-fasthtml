# Copilot Instructions

## Build and run commands

- Install Node dependencies: `npm install`
- Create or refresh the bundled Python runtime, venv, and install llama-cpp-python: `python scripts/setup-python.py`
  - On macOS, `python3 scripts/setup-python.py` is the safest form if `python` is not available.
  - macOS ARM64 and Windows x64: pre-built llama-cpp-python wheel is installed automatically (no compiler needed).
  - macOS x64: source build — requires Xcode Command Line Tools (`xcode-select --install`).
  - Windows ARM64: source build — requires MSVC Build Tools.
- Download the GGUF model (~400 MB) into `models/`: `python scripts/download-model.py`
- Run the desktop app in development: `npm run tauri:dev`
- Build the production app bundle: `npm run tauri:build`

## Test and lint commands

- There are currently no repository-level test scripts or lint scripts configured in `package.json`, and there are no committed test files to target with a single-test command.

## High-level architecture

- This repository is a three-part desktop app:
  - `src-tauri/` is the native Tauri v2 shell written in Rust.
  - `python/` contains the FastHTML application served by `uvicorn`.
  - `frontend/index.html` is a static loading page shown before the Python server is ready.
- App startup is coordinated across Rust, Python, and the loading page:
  - Tauri opens the bundled `frontend/index.html` first.
  - In `src-tauri/src/main.rs`, a background thread locates `src-tauri/python-env`, starts the bundled Python interpreter, and launches `python-env/app/server.py`.
  - Both the Rust side and the loading page poll `http://127.0.0.1:5001/health`.
  - Once the health check passes, the webview navigates to `http://127.0.0.1:5001`, where the FastHTML UI is served.
- `scripts/setup-python.py` is part of the runtime packaging flow, not just local setup:
  - It downloads `python-build-standalone`.
  - It creates `src-tauri/python-env/venv`.
  - It installs `python/requirements.txt` into that venv.
  - It copies `python/*.py` into `src-tauri/python-env/app/`, which is what the Tauri app actually runs.
- `src-tauri/tauri.conf.json` bundles `python-env/**/*` as app resources, so production builds run the packaged Python runtime instead of a system Python installation.

## Cross-platform compatibility

This app targets both **macOS** and **Windows**. Always account for both platforms when making changes:

- **Python dependencies**: Use pip environment markers for OS-specific packages (e.g., `pywin32; sys_platform == "win32"`, not a bare `pywin32`). Never add a Windows-only or macOS-only package without a marker.
- **File paths**: Use `pathlib.Path` — never hardcode `/` or `\` separators. Avoid `/tmp/` paths; use `tempfile` or a platform-neutral location.
- **Process/shell differences**: macOS uses `bin/python3` inside the venv; Windows uses `Scripts/python.exe`. `scripts/setup-python.py` already handles this — preserve that logic.
- **Debug log path**: `/tmp/tauri-fasthtml-debug.log` is macOS-only. Windows writes to a different path — check `src-tauri/src/main.rs` for the per-platform log location before referencing it.
- **Rust conditional compilation**: Use `#[cfg(target_os = "macos")]` / `#[cfg(windows)]` when platform behavior must diverge in Rust code.
- **Testing changes**: If you only have one OS available, note which platform was tested and flag any untested platform assumptions.



- Treat `src-tauri/python-env/` as generated application runtime state. Edit source files under `python/`, then rerun `python scripts/setup-python.py` to copy changes into `src-tauri/python-env/app/`.
- The `models/` directory at the project root is also generated (gitignored, ~400 MB). Populate it by running `python scripts/download-model.py`. `setup-python.py` copies it to `python-env/models/` so the running app can find it.
- `server.py` resolves the GGUF via `Path(__file__).parent.parent / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"`. In dev the file is at `python-env/app/server.py`, so the model is at `python-env/models/`. In production bundles the same relative path holds because both directories are bundled as Tauri resources.
- Keep the local server contract synchronized across files:
  - Port `5001`
  - Health route `/health`
  - Base URL `http://127.0.0.1:5001`
  These values are duplicated in `python/server.py`, `frontend/index.html`, and `src-tauri/src/main.rs`.
- The Rust shell resolves the Python runtime in this order: Tauri resource directory, `src-tauri/python-env` in dev, then `python-env` next to the executable. Preserve that lookup behavior when changing startup logic.
- Startup diagnostics are written to `/tmp/tauri-fasthtml-debug.log`, and Python stderr is appended there from the Rust process. Check that file first when the window stays on the loading screen.
- The app lifecycle is responsible for cleaning up the spawned Python process on close. If you change process startup or window lifecycle handling in `src-tauri/src/main.rs`, keep the cleanup path intact.
- Window persistence is handled by `tauri-plugin-window-state`, and shell permissions are declared in `src-tauri/capabilities/default.json`. If new shell interactions are added, update the capability file alongside the Rust code.
