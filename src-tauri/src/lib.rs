// FinCoach - Tauri shell.

use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

use tauri::Manager;

struct BackendProcess(Mutex<Option<Child>>);

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.0.lock() {
            if let Some(mut child) = child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![greet])
        .setup(|app| {
            let log_dir = log_dir();
            let _ = fs::create_dir_all(&log_dir);
            log_message(&log_dir, "FinCoach starting");

            if let Some(child) = start_backend(app.handle(), &log_dir) {
                app.manage(BackendProcess(Mutex::new(Some(child))));
            } else {
                log_message(&log_dir, "No backend process was started by this app instance");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello {}, welcome to FinCoach!", name)
}

fn start_backend(app: &tauri::AppHandle, log_dir: &PathBuf) -> Option<Child> {
    if backend_is_ready() {
        log_message(log_dir, "Backend is already listening on 127.0.0.1:8765");
        return None;
    }

    let backend_dir = match find_backend_dir(app) {
        Some(path) => path,
        None => {
            log_message(log_dir, "FinCoach backend directory was not found");
            return None;
        }
    };
    log_message(log_dir, &format!("Backend directory: {}", backend_dir.display()));

    let python = backend_python(&backend_dir);
    if !python.exists() {
        log_message(
            log_dir,
            &format!("FinCoach backend Python was not found at {}", python.display()),
        );
        return None;
    }
    log_message(log_dir, &format!("Backend Python: {}", python.display()));

    let backend_log = match open_log_file(log_dir, "backend.log") {
        Some(file) => file,
        None => {
            log_message(log_dir, "Could not open backend.log");
            return None;
        }
    };
    let backend_err = backend_log.try_clone().unwrap_or_else(|_| {
        open_log_file(log_dir, "backend-stderr.log").expect("fallback backend log file")
    });

    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("8765")
        .current_dir(&backend_dir)
        .env("FINCOACH_PORT", "8765")
        .stdin(Stdio::null())
        .stdout(Stdio::from(backend_log))
        .stderr(Stdio::from(backend_err));

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    let child = match command.spawn() {
        Ok(child) => {
            log_message(log_dir, &format!("Backend process started with pid {}", child.id()));
            child
        }
        Err(err) => {
            log_message(log_dir, &format!("FinCoach backend failed to start: {err}"));
            return None;
        }
    };

    for _ in 0..80 {
        if backend_is_ready() {
            log_message(log_dir, "Backend became ready on 127.0.0.1:8765");
            return Some(child);
        }
        thread::sleep(Duration::from_millis(250));
    }

    log_message(log_dir, "Backend process started but did not become ready");
    Some(child)
}

fn backend_is_ready() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], 8765));
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

fn backend_python(backend_dir: &PathBuf) -> PathBuf {
    if cfg!(windows) {
        backend_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        backend_dir.join(".venv").join("bin").join("python")
    }
}

fn find_backend_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    if let Ok(path) = std::env::var("FINCOACH_BACKEND_DIR") {
        let path = PathBuf::from(path);
        if is_backend_dir(&path) {
            return Some(path);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let path = resource_dir.join("backend");
        if is_backend_dir(&path) {
            return Some(path);
        }

        if is_backend_dir(&resource_dir) {
            return Some(resource_dir);
        }
    }

    let mut starts = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        starts.push(exe);
    }
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    starts.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));

    for start in starts {
        for ancestor in start.ancestors() {
            let direct = ancestor.join("backend");
            if is_backend_dir(&direct) {
                return Some(direct);
            }

            let bundled = ancestor.join("_up_").join("backend");
            if is_backend_dir(&bundled) {
                return Some(bundled);
            }

            let repo_root = ancestor.parent().map(|parent| parent.join("backend"));
            if let Some(path) = repo_root {
                if is_backend_dir(&path) {
                    return Some(path);
                }
            }
        }
    }

    None
}

fn is_backend_dir(path: &PathBuf) -> bool {
    path.join("app").join("main.py").exists() && backend_python(path).exists()
}

fn log_dir() -> PathBuf {
    if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        return PathBuf::from(local_app_data).join("FinCoach").join("logs");
    }

    std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.join("logs")))
        .unwrap_or_else(|| PathBuf::from("logs"))
}

fn open_log_file(log_dir: &PathBuf, name: &str) -> Option<File> {
    fs::create_dir_all(log_dir).ok()?;
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join(name))
        .ok()
}

fn log_message(log_dir: &PathBuf, message: &str) {
    let Some(mut file) = open_log_file(log_dir, "app.log") else {
        return;
    };

    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs().to_string())
        .unwrap_or_else(|_| "unknown-time".to_string());
    let _ = writeln!(file, "[{timestamp}] {message}");
}
