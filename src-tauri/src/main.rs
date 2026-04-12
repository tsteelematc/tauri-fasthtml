use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use tauri::Manager;

// Global PID for atexit/signal cleanup
static PYTHON_PID: AtomicU32 = AtomicU32::new(0);

#[cfg(not(target_os = "windows"))]
extern "C" fn cleanup_on_exit() {
    let pid = PYTHON_PID.load(Ordering::SeqCst);
    if pid != 0 {
        unsafe { libc::kill(pid as i32, libc::SIGKILL); }
    }
}

fn kill_python(pid: u32) {
    if pid == 0 { return; }
    eprintln!("Killing Python process {}", pid);
    #[cfg(target_os = "windows")]
    { let _ = std::process::Command::new("taskkill").args(["/PID", &pid.to_string(), "/F"]).output(); }
    #[cfg(not(target_os = "windows"))]
    {
        unsafe { libc::kill(pid as i32, libc::SIGKILL); }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Register atexit handler to kill Python when this process exits for any reason
    #[cfg(not(target_os = "windows"))]
    unsafe { libc::atexit(cleanup_on_exit); }

    let python_pid = Arc::new(AtomicU32::new(0));
    let python_pid_clone = python_pid.clone();
    let python_pid_cleanup = python_pid.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let pid_store = python_pid_clone.clone();
            let resource_dir = app.path().resource_dir().ok();

            std::thread::spawn(move || {
                // Write debug log for diagnosing launch issues
                let log_path = std::env::temp_dir().join("tauri-fasthtml-debug.log");
                let log_path_str = log_path.to_string_lossy().to_string();
                let mut log = std::fs::File::create(&log_path).ok();
                let write_log = |log: &mut Option<std::fs::File>, msg: &str| {
                    if let Some(ref mut f) = log {
                        use std::io::Write;
                        let _ = writeln!(f, "{}", msg);
                    }
                    eprintln!("{}", msg);
                };

                write_log(&mut log, &format!("debug log: {}", log_path_str));
                write_log(&mut log, &format!("resource_dir: {:?}", resource_dir));
                let child = start_python_server(resource_dir.as_deref(), &mut log);
                if let Some(mut child) = child {
                    let child_pid = child.id();
                    pid_store.store(child_pid, Ordering::SeqCst);
                    PYTHON_PID.store(child_pid, Ordering::SeqCst);

                    // Capture Python stderr in a separate thread
                    if let Some(stderr) = child.stderr.take() {
                        let mut log_clone = std::fs::OpenOptions::new()
                            .append(true)
                            .open(&log_path_str)
                            .ok();
                        std::thread::spawn(move || {
                            use std::io::{BufRead, BufReader, Write};
                            let reader = BufReader::new(stderr);
                            for line in reader.lines() {
                                if let Ok(line) = line {
                                    if let Some(ref mut f) = log_clone {
                                        let _ = writeln!(f, "[python stderr] {}", line);
                                    }
                                }
                            }
                        });
                    }

                    // Wait for server to be ready (up to 120s — model load can be slow)
                    let mut server_ready = false;
                    for i in 0..600 {
                        std::thread::sleep(std::time::Duration::from_millis(100));
                        if let Ok(resp) = reqwest::blocking::get("http://127.0.0.1:5001/health") {
                            if resp.status().is_success() {
                                write_log(&mut log, &format!("Health check passed on attempt {}", i));
                                // Navigate the webview to FastHTML
                                if let Some(window) = app_handle.get_webview_window("main") {
                                    let _ = window.navigate("http://127.0.0.1:5001".parse().unwrap());
                                }
                                server_ready = true;
                                break;
                            }
                        }
                    }
                    if !server_ready {
                        write_log(&mut log, "Health check FAILED after 50 attempts");
                    }

                    let _ = child.wait();
                }
            });
            Ok(())
        })
        .on_window_event(move |_window, event| {
            match event {
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed => {
                    kill_python(python_pid.load(Ordering::SeqCst));
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");

    // Final cleanup: kill Python when the Tauri event loop exits (Cmd+Q, etc.)
    kill_python(python_pid_cleanup.load(Ordering::SeqCst));
}

fn find_python_env(resource_dir: Option<&std::path::Path>) -> std::path::PathBuf {
    // Bundled mode: prefer Tauri's resource dir (works in .app bundles)
    if let Some(res_dir) = resource_dir {
        let bundled = res_dir.join("python-env");
        if bundled.exists() {
            eprintln!("Using bundled python-env at {:?}", bundled);
            return bundled;
        }
    }
    // Dev mode: python-env next to Cargo.toml
    let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python-env");
    if dev_path.exists() {
        eprintln!("Using dev python-env at {:?}", dev_path);
        return dev_path;
    }
    // Fallback: next to the executable
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    let fallback = exe_dir.join("python-env");
    eprintln!("Using fallback python-env at {:?}", fallback);
    fallback
}

fn start_python_server(resource_dir: Option<&std::path::Path>, log: &mut Option<std::fs::File>) -> Option<std::process::Child> {
    let python_env = find_python_env(resource_dir);

    let write_log = |log: &mut Option<std::fs::File>, msg: &str| {
        if let Some(ref mut f) = log {
            use std::io::Write;
            let _ = writeln!(f, "{}", msg);
        }
        eprintln!("{}", msg);
    };

    write_log(log, &format!("Python env dir: {:?} (exists: {})", python_env, python_env.exists()));

    // Use the venv Python so .pth files (needed by pywin32) are processed
    let python_exe = if cfg!(target_os = "windows") {
        python_env.join("venv").join("Scripts").join("python.exe")
    } else {
        python_env.join("venv").join("bin").join("python3")
    };
    write_log(log, &format!("Python exe: {:?} (exists: {})", python_exe, python_exe.exists()));

    let server_script = python_env.join("app").join("server.py");
    write_log(log, &format!("Server script: {:?} (exists: {})", server_script, server_script.exists()));

    match std::process::Command::new(&python_exe)
        .arg(&server_script)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .current_dir(std::env::temp_dir())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
    {
        Ok(child) => {
            write_log(log, &format!("Python server started with PID: {}", child.id()));
            Some(child)
        }
        Err(e) => {
            write_log(log, &format!("Failed to start Python server: {}", e));
            None
        }
    }
}

fn main() {
    run();
}
