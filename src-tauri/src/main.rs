use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let python_pid = Arc::new(AtomicU32::new(0));
    let python_pid_clone = python_pid.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let pid_store = python_pid_clone.clone();
            let resource_dir = app.path().resource_dir().ok();

            std::thread::spawn(move || {
                // Write debug log to /tmp for diagnosing launch issues
                let log_path = "/tmp/tauri-fasthtml-debug.log";
                let mut log = std::fs::File::create(log_path).ok();
                let write_log = |log: &mut Option<std::fs::File>, msg: &str| {
                    if let Some(ref mut f) = log {
                        use std::io::Write;
                        let _ = writeln!(f, "{}", msg);
                    }
                    eprintln!("{}", msg);
                };

                write_log(&mut log, &format!("resource_dir: {:?}", resource_dir));
                let child = start_python_server(resource_dir.as_deref(), &mut log);
                if let Some(mut child) = child {
                    pid_store.store(child.id(), Ordering::SeqCst);

                    // Capture Python stderr in a separate thread
                    if let Some(stderr) = child.stderr.take() {
                        let mut log_clone = std::fs::OpenOptions::new()
                            .append(true)
                            .open("/tmp/tauri-fasthtml-debug.log")
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

                    // Wait for server to be ready
                    let mut server_ready = false;
                    for i in 0..50 {
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
                    let pid = python_pid.load(Ordering::SeqCst);
                    if pid != 0 {
                        #[cfg(target_os = "windows")]
                        { let _ = std::process::Command::new("taskkill").args(["/PID", &pid.to_string(), "/F"]).output(); }
                        #[cfg(not(target_os = "windows"))]
                        { let _ = std::process::Command::new("kill").arg(pid.to_string()).output(); }
                    }
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
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

    let python_exe = if cfg!(target_os = "windows") {
        python_env.join("python").join("python.exe")
    } else {
        python_env.join("python").join("bin").join("python3")
    };
    write_log(log, &format!("Python exe: {:?} (exists: {})", python_exe, python_exe.exists()));

    let server_script = python_env.join("app").join("server.py");
    write_log(log, &format!("Server script: {:?} (exists: {})", server_script, server_script.exists()));

    let venv_site_packages = if cfg!(target_os = "windows") {
        python_env.join("venv").join("Lib").join("site-packages")
    } else {
        let lib_dir = python_env.join("venv").join("lib");
        std::fs::read_dir(&lib_dir).ok()
            .and_then(|entries| entries
                .filter_map(|e| e.ok())
                .find(|e| e.file_name().to_string_lossy().starts_with("python"))
                .map(|e| e.path().join("site-packages")))
            .unwrap_or(lib_dir.join("python3.12").join("site-packages"))
    };

    match std::process::Command::new(&python_exe)
        .arg(&server_script)
        .env("PYTHONPATH", &venv_site_packages)
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
