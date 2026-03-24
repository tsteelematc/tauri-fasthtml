use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let python_pid = Arc::new(AtomicU32::new(0));
    let python_pid_clone = python_pid.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let pid_store = python_pid_clone.clone();

            std::thread::spawn(move || {
                let child = start_python_server();
                if let Some(mut child) = child {
                    pid_store.store(child.id(), Ordering::SeqCst);

                    // Wait for server to be ready
                    for _ in 0..50 {
                        std::thread::sleep(std::time::Duration::from_millis(100));
                        if let Ok(resp) = reqwest::blocking::get("http://127.0.0.1:5001/health") {
                            if resp.status().is_success() {
                                // Navigate the webview to FastHTML
                                if let Some(window) = app_handle.get_webview_window("main") {
                                    let _ = window.navigate("http://127.0.0.1:5001".parse().unwrap());
                                }
                                break;
                            }
                        }
                    }

                    let _ = child.wait();
                }
            });
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let pid = python_pid.load(Ordering::SeqCst);
                if pid != 0 {
                    #[cfg(target_os = "windows")]
                    { let _ = std::process::Command::new("taskkill").args(["/PID", &pid.to_string(), "/F"]).output(); }
                    #[cfg(not(target_os = "windows"))]
                    { let _ = std::process::Command::new("kill").arg(pid.to_string()).output(); }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn find_python_env() -> std::path::PathBuf {
    let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python-env");
    if dev_path.exists() {
        return dev_path;
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    exe_dir.join("python-env")
}

fn start_python_server() -> Option<std::process::Child> {
    let python_env = find_python_env();

    let python_exe = if cfg!(target_os = "windows") {
        python_env.join("python").join("python.exe")
    } else {
        python_env.join("python").join("bin").join("python3")
    };

    let server_script = python_env.join("app").join("server.py");

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
        .spawn()
    {
        Ok(child) => {
            println!("Python server started with PID: {}", child.id());
            Some(child)
        }
        Err(e) => {
            eprintln!("Failed to start Python server: {}", e);
            None
        }
    }
}

fn main() {
    run();
}
