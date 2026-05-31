use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

const LOOPBACK_HOST: &str = "127.0.0.1";
const VAULT_MARKER_DIR: &str = ".knowlet";
const EMPTY_DIR_IGNORED_ENTRIES: &[&str] = &[".DS_Store", ".localized", "Icon\r"];
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const BACKEND_BIN_NAME: &str = "knowlet-backend";
const FRONTEND_DIST_RESOURCE: &str = "frontend-dist";
pub const BACKEND_BIN_ENV: &str = "KNOWLET_BACKEND_BIN";
pub const VAULT_ENV: &str = "KNOWLET_VAULT";
pub const DESKTOP_PARENT_PID_ENV: &str = "KNOWLET_DESKTOP_PARENT_PID";
const DESKTOP_BACKEND_STDIO_LOG: &str = "desktop-backend.log";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendProgram {
    pub executable: PathBuf,
    pub prefix_args: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NewVaultPreviewStatus {
    Ready,
    ExistingEmpty,
    ExistingNonEmpty,
    ExistingVault,
    Invalid,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct NewVaultPreview {
    pub status: NewVaultPreviewStatus,
    pub name: String,
    pub parent: String,
    pub target: String,
    pub can_create: bool,
    pub requires_empty_dir_confirmation: bool,
    pub message: String,
    pub suggested_name: Option<String>,
}

pub fn validate_vault_dir(path: &Path) -> Result<PathBuf, String> {
    if !path.exists() {
        return Err(format!("vault path does not exist: {}", path.display()));
    }
    if !path.is_dir() {
        return Err(format!(
            "vault path must be a directory: {}",
            path.display()
        ));
    }
    let resolved = path
        .canonicalize()
        .map_err(|err| format!("failed to resolve vault path: {err}"))?;
    let marker = resolved.join(VAULT_MARKER_DIR);
    if !marker.is_dir() {
        return Err(format!(
            "selected directory is not a knowlet vault: missing {}",
            VAULT_MARKER_DIR
        ));
    }
    if let Some(ancestor) = find_vault_ancestor(&resolved) {
        return Err(format!(
            "nested vaults are not supported: {} is inside {}",
            resolved.display(),
            ancestor.display()
        ));
    }
    Ok(resolved)
}

pub fn preview_new_vault(parent: &Path, name: &str) -> NewVaultPreview {
    match new_vault_target_state(parent, name) {
        Ok(state) => state.into_preview(),
        Err(message) => NewVaultPreview {
            status: NewVaultPreviewStatus::Invalid,
            name: name.trim().to_string(),
            parent: parent.display().to_string(),
            target: String::new(),
            can_create: false,
            requires_empty_dir_confirmation: false,
            message,
            suggested_name: None,
        },
    }
}

pub fn create_vault_dir(
    parent: &Path,
    name: &str,
    allow_existing_empty: bool,
) -> Result<PathBuf, String> {
    create_vault_dir_with_initializer(parent, name, allow_existing_empty, initialize_vault_layout)
}

pub fn delete_vault_local_files(path: &Path) -> Result<PathBuf, String> {
    delete_vault_local_files_with_remover(path, |vault| {
        trash::delete(vault).map_err(|err| {
            format!(
                "failed to move vault to the system trash {}: {err}",
                vault.display()
            )
        })
    })
}

pub fn delete_vault_local_files_with_remover(
    path: &Path,
    mut remover: impl FnMut(&Path) -> Result<(), String>,
) -> Result<PathBuf, String> {
    let vault = validate_vault_dir(path)?;
    remover(&vault)?;
    Ok(vault)
}

pub fn create_vault_dir_with_initializer(
    parent: &Path,
    name: &str,
    allow_existing_empty: bool,
    initializer: impl FnOnce(&Path) -> Result<(), String>,
) -> Result<PathBuf, String> {
    let state = new_vault_target_state(parent, name)?;
    match state.kind {
        NewVaultTargetKind::Ready => {
            fs::create_dir(&state.target).map_err(|err| {
                format!(
                    "failed to create vault folder {}: {err}",
                    state.target.display()
                )
            })?;
        }
        NewVaultTargetKind::ExistingEmpty => {
            if !allow_existing_empty {
                return Err(format!(
                    "target folder already exists and is empty: {}",
                    state.target.display()
                ));
            }
        }
        NewVaultTargetKind::ExistingNonEmpty => {
            return Err(format!(
                "target folder already exists and contains files: {}",
                state.target.display()
            ));
        }
        NewVaultTargetKind::ExistingVault => {
            return Err(format!(
                "target folder is already a Knowlet vault: {}",
                state.target.display()
            ));
        }
    }

    initializer(&state.target)?;
    validate_vault_dir(&state.target)
}

pub fn initialize_vault_layout(vault: &Path) -> Result<(), String> {
    let repo_root = repo_root_from_manifest()?;
    let current_exe = std::env::current_exe()
        .map_err(|err| format!("failed to resolve current executable: {err}"))?;
    let backend_program =
        resolve_backend_program(std::env::var_os(BACKEND_BIN_ENV), &current_exe, &repo_root)?;
    run_vault_init(&backend_program, vault)
}

pub fn run_vault_init(program: &BackendProgram, vault: &Path) -> Result<(), String> {
    let output = Command::new(&program.executable)
        .args(&program.prefix_args)
        .args(["vault", "init"])
        .arg(vault)
        .stdin(Stdio::null())
        .output()
        .map_err(|err| format!("failed to initialize Knowlet vault: {err}"))?;

    if output.status.success() {
        return Ok(());
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!(
        "Knowlet vault initialization failed with status {}{}\n{}",
        output.status,
        if stdout.trim().is_empty() {
            String::new()
        } else {
            format!("\nstdout:\n{}", stdout.trim())
        },
        if stderr.trim().is_empty() {
            "stderr: <empty>".to_string()
        } else {
            format!("stderr:\n{}", stderr.trim())
        }
    ))
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum NewVaultTargetKind {
    Ready,
    ExistingEmpty,
    ExistingNonEmpty,
    ExistingVault,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct NewVaultTargetState {
    kind: NewVaultTargetKind,
    name: String,
    parent: PathBuf,
    target: PathBuf,
    suggested_name: Option<String>,
}

impl NewVaultTargetState {
    fn into_preview(self) -> NewVaultPreview {
        let (status, can_create, requires_empty_dir_confirmation, message) = match self.kind {
            NewVaultTargetKind::Ready => (
                NewVaultPreviewStatus::Ready,
                true,
                false,
                format!("Create a new vault folder at {}", self.target.display()),
            ),
            NewVaultTargetKind::ExistingEmpty => (
                NewVaultPreviewStatus::ExistingEmpty,
                true,
                true,
                format!(
                    "The folder {} already exists and is empty. Knowlet can initialize it as a vault.",
                    self.target.display()
                ),
            ),
            NewVaultTargetKind::ExistingNonEmpty => (
                NewVaultPreviewStatus::ExistingNonEmpty,
                false,
                false,
                format!(
                    "The folder {} already exists and contains files. Choose another name or import it later.",
                    self.target.display()
                ),
            ),
            NewVaultTargetKind::ExistingVault => (
                NewVaultPreviewStatus::ExistingVault,
                false,
                false,
                format!(
                    "The folder {} is already a Knowlet vault. Open it instead.",
                    self.target.display()
                ),
            ),
        };

        NewVaultPreview {
            status,
            name: self.name,
            parent: self.parent.display().to_string(),
            target: self.target.display().to_string(),
            can_create,
            requires_empty_dir_confirmation,
            message,
            suggested_name: self.suggested_name,
        }
    }
}

fn new_vault_target_state(parent: &Path, name: &str) -> Result<NewVaultTargetState, String> {
    let name = normalize_vault_name(name)?;
    if !parent.exists() {
        return Err(format!(
            "vault parent folder does not exist: {}",
            parent.display()
        ));
    }
    if !parent.is_dir() {
        return Err(format!(
            "vault parent must be a directory: {}",
            parent.display()
        ));
    }
    let parent = parent
        .canonicalize()
        .map_err(|err| format!("failed to resolve vault parent folder: {err}"))?;
    if let Some(ancestor) = vault_dir_at_or_above(&parent) {
        return Err(format!(
            "nested vaults are not supported: {} is inside {}",
            parent.display(),
            ancestor.display()
        ));
    }

    let target = parent.join(&name);
    if !target.exists() {
        return Ok(NewVaultTargetState {
            kind: NewVaultTargetKind::Ready,
            name,
            parent,
            target,
            suggested_name: None,
        });
    }
    if !target.is_dir() {
        return Err(format!(
            "target vault path already exists and is not a directory: {}",
            target.display()
        ));
    }

    let target = target
        .canonicalize()
        .map_err(|err| format!("failed to resolve target vault folder: {err}"))?;
    if target.join(VAULT_MARKER_DIR).is_dir() {
        let suggested_name = suggest_available_vault_name(&parent, name.as_str());
        return Ok(NewVaultTargetState {
            kind: NewVaultTargetKind::ExistingVault,
            name,
            parent,
            target,
            suggested_name,
        });
    }
    if !directory_is_empty_for_vault(&target)? {
        let suggested_name = suggest_available_vault_name(&parent, name.as_str());
        return Ok(NewVaultTargetState {
            kind: NewVaultTargetKind::ExistingNonEmpty,
            name,
            parent,
            target,
            suggested_name,
        });
    }

    Ok(NewVaultTargetState {
        kind: NewVaultTargetKind::ExistingEmpty,
        name,
        parent,
        target,
        suggested_name: None,
    })
}

fn normalize_vault_name(name: &str) -> Result<String, String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err("vault name is required".to_string());
    }
    if trimmed == "." || trimmed == ".." {
        return Err("vault name cannot be . or ..".to_string());
    }
    if trimmed == VAULT_MARKER_DIR {
        return Err(format!("vault name cannot be {VAULT_MARKER_DIR}"));
    }
    if trimmed.contains('/') || trimmed.contains('\\') || trimmed.contains('\0') {
        return Err("vault name cannot contain path separators".to_string());
    }
    Ok(trimmed.to_string())
}

fn directory_is_empty_for_vault(path: &Path) -> Result<bool, String> {
    for entry in fs::read_dir(path)
        .map_err(|err| format!("failed to inspect folder {}: {err}", path.display()))?
    {
        let entry =
            entry.map_err(|err| format!("failed to inspect folder {}: {err}", path.display()))?;
        let name = entry.file_name();
        if EMPTY_DIR_IGNORED_ENTRIES
            .iter()
            .any(|ignored| name.to_string_lossy() == *ignored)
        {
            continue;
        }
        return Ok(false);
    }
    Ok(true)
}

fn suggest_available_vault_name(parent: &Path, base_name: &str) -> Option<String> {
    for index in 2..100 {
        let candidate = format!("{base_name} {index}");
        if !parent.join(&candidate).exists() {
            return Some(candidate);
        }
    }
    None
}

fn vault_dir_at_or_above(path: &Path) -> Option<PathBuf> {
    let mut current = Some(path);
    while let Some(candidate) = current {
        if candidate.join(VAULT_MARKER_DIR).is_dir() {
            return Some(candidate.to_path_buf());
        }
        current = candidate.parent();
    }
    None
}

fn find_vault_ancestor(path: &Path) -> Option<PathBuf> {
    let mut current = path.parent();
    while let Some(candidate) = current {
        if candidate.join(VAULT_MARKER_DIR).is_dir() {
            return Some(candidate.to_path_buf());
        }
        current = candidate.parent();
    }
    None
}

pub fn find_available_port() -> Result<u16, String> {
    let listener = TcpListener::bind((LOOPBACK_HOST, 0))
        .map_err(|err| format!("failed to bind loopback port: {err}"))?;
    let port = listener
        .local_addr()
        .map_err(|err| format!("failed to read loopback port: {err}"))?
        .port();
    drop(listener);
    Ok(port)
}

pub fn backend_url(port: u16) -> String {
    format!("http://{LOOPBACK_HOST}:{port}")
}

pub fn resolve_startup_vault(
    env_vault: Option<OsString>,
    pick_folder: impl FnOnce() -> Option<PathBuf>,
) -> Result<PathBuf, String> {
    if let Some(path) = env_vault {
        return validate_vault_dir(&PathBuf::from(path));
    }

    let Some(path) = pick_folder() else {
        return Err("no Knowlet vault selected".to_string());
    };
    validate_vault_dir(&path)
}

pub fn validate_frontend_dist(path: &Path) -> Result<PathBuf, String> {
    let index = path.join("index.html");
    if !index.is_file() {
        return Err(format!(
            "frontend dist is missing index.html: {}",
            path.display()
        ));
    }
    path.canonicalize()
        .map_err(|err| format!("failed to resolve frontend dist path: {err}"))
}

pub fn bundled_frontend_dist_from_exe(current_exe: &Path) -> Option<PathBuf> {
    current_exe
        .parent()
        .and_then(Path::parent)
        .map(|contents_dir| contents_dir.join("Resources").join(FRONTEND_DIST_RESOURCE))
}

pub fn resolve_frontend_dist(current_exe: &Path, dev_dist: &Path) -> Result<PathBuf, String> {
    if let Some(bundled) = bundled_frontend_dist_from_exe(current_exe) {
        if bundled.join("index.html").is_file() {
            return validate_frontend_dist(&bundled);
        }
    }
    validate_frontend_dist(dev_dist)
}

pub fn bundled_backend_path_from_exe(current_exe: &Path) -> Option<PathBuf> {
    current_exe
        .parent()
        .map(|macos_dir| macos_dir.join(BACKEND_BIN_NAME))
}

pub fn resolve_backend_program(
    override_bin: Option<OsString>,
    current_exe: &Path,
    repo_root: &Path,
) -> Result<BackendProgram, String> {
    if let Some(path) = override_bin {
        return Ok(BackendProgram {
            executable: PathBuf::from(path),
            prefix_args: Vec::new(),
        });
    }

    if let Some(bundled) = bundled_backend_path_from_exe(current_exe) {
        if bundled.is_file() {
            return Ok(BackendProgram {
                executable: bundled,
                prefix_args: Vec::new(),
            });
        }
    }

    Ok(BackendProgram {
        executable: PathBuf::from("uv"),
        prefix_args: vec![
            "run".to_string(),
            "--directory".to_string(),
            repo_root
                .to_str()
                .ok_or_else(|| "repository path is not valid UTF-8".to_string())?
                .to_string(),
            "knowlet".to_string(),
        ],
    })
}

pub fn repo_root_from_manifest() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| "failed to resolve repository root".to_string())
        .map(Path::to_path_buf)
}

pub struct BackendProcess {
    child: Child,
    pub url: String,
    pub vault: PathBuf,
    pub log_path: PathBuf,
}

impl BackendProcess {
    pub fn start(vault: PathBuf, frontend_dist: PathBuf) -> Result<Self, String> {
        let vault = validate_vault_dir(&vault)?;
        let frontend_dist = validate_frontend_dist(&frontend_dist)?;
        let port = find_available_port()?;
        let url = backend_url(port);
        let repo_root = repo_root_from_manifest()?;
        let current_exe = std::env::current_exe()
            .map_err(|err| format!("failed to resolve current executable: {err}"))?;
        let backend_program =
            resolve_backend_program(std::env::var_os(BACKEND_BIN_ENV), &current_exe, &repo_root)?;
        let log_path = desktop_backend_log_path(&vault);
        reset_backend_stdio_log(&log_path)?;
        let stdout_log = open_backend_stdio_log(&log_path)?;
        let stderr_log = open_backend_stdio_log(&log_path)?;

        let mut cmd = Command::new(&backend_program.executable);
        cmd.args(&backend_program.prefix_args)
            .args(["web", "--host", LOOPBACK_HOST, "--port", &port.to_string()])
            .env("KNOWLET_VAULT", &vault)
            .env("KNOWLET_FRONTEND_DIST", &frontend_dist)
            .env(DESKTOP_PARENT_PID_ENV, std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout_log))
            .stderr(Stdio::from(stderr_log));

        let child = cmd
            .spawn()
            .map_err(|err| format!("failed to start knowlet backend: {err}"))?;
        let mut child = child;
        if let Err(err) = wait_for_backend_health(&mut child, port, HEALTH_TIMEOUT, &log_path) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(err);
        }

        Ok(Self {
            child,
            url,
            vault,
            log_path,
        })
    }

    pub fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

pub fn desktop_backend_log_path(vault: &Path) -> PathBuf {
    vault.join(VAULT_MARKER_DIR).join(DESKTOP_BACKEND_STDIO_LOG)
}

fn reset_backend_stdio_log(path: &Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| {
            format!(
                "failed to create desktop backend log directory {}: {err}",
                parent.display()
            )
        })?;
    }
    OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map(|_| ())
        .map_err(|err| {
            format!(
                "failed to reset desktop backend log {}: {err}",
                path.display()
            )
        })
}

fn open_backend_stdio_log(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|err| {
            format!(
                "failed to open desktop backend log {}: {err}",
                path.display()
            )
        })
}

pub fn wait_for_backend_health(
    child: &mut Child,
    port: u16,
    timeout: Duration,
    log_path: &Path,
) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if health_check(port) {
            return Ok(());
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                return Err(format!(
                    "knowlet backend exited before health check passed ({status}){}",
                    backend_log_hint(log_path)
                ));
            }
            Ok(None) => {}
            Err(err) => {
                return Err(format!(
                    "failed to observe knowlet backend process: {err}{}",
                    backend_log_hint(log_path)
                ));
            }
        }
        thread::sleep(Duration::from_millis(150));
    }
    Err(format!(
        "knowlet backend health check did not pass at http://{LOOPBACK_HOST}:{port}/api/health within {}s{}",
        timeout.as_secs(),
        backend_log_hint(log_path)
    ))
}

pub fn wait_for_health(port: u16, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if health_check(port) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(150));
    }
    Err(format!(
        "knowlet backend health check did not pass at http://{LOOPBACK_HOST}:{port}/api/health within {}s",
        timeout.as_secs()
    ))
}

fn backend_log_hint(log_path: &Path) -> String {
    let tail = read_log_tail(log_path, 20);
    if tail.is_empty() {
        format!("\nBackend log: {}", log_path.display())
    } else {
        format!(
            "\nBackend log: {}\nRecent backend log:\n{}",
            log_path.display(),
            tail
        )
    }
}

pub fn read_log_tail(path: &Path, max_lines: usize) -> String {
    let Ok(content) = fs::read_to_string(path) else {
        return String::new();
    };
    let mut lines = content.lines().rev().take(max_lines).collect::<Vec<_>>();
    lines.reverse();
    lines.join("\n")
}

fn health_check(port: u16) -> bool {
    let Ok(mut stream) = TcpStream::connect((LOOPBACK_HOST, port)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {LOOPBACK_HOST}:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = [0_u8; 256];
    let Ok(n) = stream.read(&mut response) else {
        return false;
    };
    let status = String::from_utf8_lossy(&response[..n]);
    status.starts_with("HTTP/1.1 200") || status.starts_with("HTTP/1.0 200")
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::net::TcpListener;
    use std::path::Path;
    use std::process::{Command, Stdio};
    use std::time::Duration;

    use tempfile::tempdir;

    #[test]
    fn accepts_directory_with_knowlet_marker() {
        let dir = tempdir().unwrap();
        fs::create_dir(dir.path().join(".knowlet")).unwrap();

        let vault = super::validate_vault_dir(dir.path()).unwrap();

        assert_eq!(vault, dir.path().canonicalize().unwrap());
    }

    #[test]
    fn rejects_nested_vault_when_opening_existing_vault() {
        let dir = tempdir().unwrap();
        let outer = dir.path().join("outer");
        let inner = outer.join("inner");
        fs::create_dir_all(outer.join(".knowlet")).unwrap();
        fs::create_dir_all(inner.join(".knowlet")).unwrap();

        let err = super::validate_vault_dir(&inner).unwrap_err();

        assert!(err.contains("nested"));
        assert!(err.contains("outer"));
    }

    #[test]
    fn rejects_directory_without_knowlet_marker() {
        let dir = tempdir().unwrap();

        let err = super::validate_vault_dir(dir.path()).unwrap_err();

        assert!(err.contains(".knowlet"));
    }

    #[test]
    fn desktop_backend_log_path_lives_under_vault_state() {
        let dir = tempdir().unwrap();

        assert_eq!(
            super::desktop_backend_log_path(dir.path()),
            dir.path().join(".knowlet").join("desktop-backend.log")
        );
    }

    #[test]
    fn read_log_tail_returns_recent_lines() {
        let dir = tempdir().unwrap();
        let log = dir.path().join("backend.log");
        fs::write(&log, "one\ntwo\nthree\nfour\n").unwrap();

        assert_eq!(super::read_log_tail(&log, 2), "three\nfour");
    }

    #[test]
    fn reset_backend_stdio_log_truncates_previous_launch() {
        let dir = tempdir().unwrap();
        let log = dir.path().join(".knowlet").join("desktop-backend.log");
        fs::create_dir_all(log.parent().unwrap()).unwrap();
        fs::write(&log, "old launch\n").unwrap();

        super::reset_backend_stdio_log(&log).unwrap();

        assert_eq!(fs::read_to_string(&log).unwrap(), "");
    }

    #[cfg(unix)]
    #[test]
    fn backend_health_reports_child_exit_with_log_tail() {
        let dir = tempdir().unwrap();
        let log = dir.path().join("backend.log");
        let stdout = super::open_backend_stdio_log(&log).unwrap();
        let stderr = super::open_backend_stdio_log(&log).unwrap();
        let mut child = Command::new("sh")
            .arg("-c")
            .arg("echo backend exploded; exit 42")
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr))
            .spawn()
            .unwrap();
        let port = super::find_available_port().unwrap();

        let err = super::wait_for_backend_health(&mut child, port, Duration::from_secs(1), &log)
            .unwrap_err();

        assert!(err.contains("exited before health check passed"));
        assert!(err.contains("backend exploded"));
        assert!(err.contains("backend.log"));
    }

    #[test]
    fn rejects_file_path_as_vault() {
        let dir = tempdir().unwrap();
        let file = dir.path().join("note.md");
        fs::write(&file, "# note").unwrap();

        let err = super::validate_vault_dir(&file).unwrap_err();

        assert!(err.contains("directory"));
    }

    #[test]
    fn finds_available_loopback_port() {
        let (port, listener) = (0..10)
            .find_map(|_| {
                let port = super::find_available_port().unwrap();
                TcpListener::bind(("127.0.0.1", port))
                    .ok()
                    .map(|listener| (port, listener))
            })
            .expect("find_available_port should return a bindable loopback port");

        assert_eq!(listener.local_addr().unwrap().port(), port);
    }

    #[test]
    fn builds_backend_url_from_port() {
        assert_eq!(
            super::backend_url(8765),
            "http://127.0.0.1:8765".to_string()
        );
    }

    #[test]
    fn wait_for_health_rejects_bound_port_without_http_200() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let _ = std::io::Write::write_all(
                    &mut stream,
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n",
                );
            }
        });

        let err = super::wait_for_health(port, Duration::from_millis(250)).unwrap_err();

        assert!(err.contains("health"));
    }

    #[test]
    fn wait_for_health_accepts_http_200() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let _ = std::io::Write::write_all(
                    &mut stream,
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}",
                );
            }
        });

        super::wait_for_health(port, Duration::from_secs(1)).unwrap();
    }

    #[test]
    fn startup_vault_prefers_environment_value() {
        let dir = tempdir().unwrap();
        fs::create_dir(dir.path().join(".knowlet")).unwrap();

        let vault = super::resolve_startup_vault(Some(dir.path().into()), || {
            panic!("folder picker should not run when KNOWLET_VAULT is present")
        })
        .unwrap();

        assert_eq!(vault, dir.path().canonicalize().unwrap());
    }

    #[test]
    fn startup_vault_uses_selected_folder_without_environment_value() {
        let dir = tempdir().unwrap();
        fs::create_dir(dir.path().join(".knowlet")).unwrap();

        let vault = super::resolve_startup_vault(None, || Some(dir.path().to_path_buf())).unwrap();

        assert_eq!(vault, dir.path().canonicalize().unwrap());
    }

    #[test]
    fn startup_vault_rejects_selected_non_vault_folder() {
        let dir = tempdir().unwrap();

        let err =
            super::resolve_startup_vault(None, || Some(dir.path().to_path_buf())).unwrap_err();

        assert!(err.contains(".knowlet"));
    }

    #[test]
    fn creates_new_vault_in_fresh_child_directory() {
        let dir = tempdir().unwrap();
        let mut initialized = false;

        let vault =
            super::create_vault_dir_with_initializer(dir.path(), "Research", false, |target| {
                initialized = true;
                assert_eq!(
                    target.file_name().and_then(|name| name.to_str()),
                    Some("Research")
                );
                fs::create_dir_all(target.join(".knowlet")).unwrap();
                Ok(())
            })
            .unwrap();

        assert!(initialized);
        assert_eq!(vault, dir.path().join("Research").canonicalize().unwrap());
        assert!(vault.join(".knowlet").is_dir());
    }

    #[test]
    fn reuses_existing_empty_directory_only_after_confirmation() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("B");
        fs::create_dir(&target).unwrap();

        let preview = super::preview_new_vault(dir.path(), "B");
        assert_eq!(preview.status, super::NewVaultPreviewStatus::ExistingEmpty);
        assert!(preview.can_create);
        assert!(preview.requires_empty_dir_confirmation);

        let err = super::create_vault_dir_with_initializer(dir.path(), "B", false, |_| Ok(()))
            .unwrap_err();
        assert!(err.contains("empty"));
        assert!(!target.join(".knowlet").exists());

        let vault = super::create_vault_dir_with_initializer(dir.path(), "B", true, |target| {
            fs::create_dir_all(target.join(".knowlet")).unwrap();
            Ok(())
        })
        .unwrap();

        assert_eq!(vault, target.canonicalize().unwrap());
        assert!(vault.join(".knowlet").is_dir());
    }

    #[test]
    fn rejects_existing_non_empty_directory_without_modifying_it() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("B");
        fs::create_dir(&target).unwrap();
        fs::write(target.join("existing.md"), "# keep me").unwrap();

        let preview = super::preview_new_vault(dir.path(), "B");
        assert_eq!(
            preview.status,
            super::NewVaultPreviewStatus::ExistingNonEmpty
        );
        assert!(!preview.can_create);
        assert_eq!(preview.suggested_name.as_deref(), Some("B 2"));

        let err = super::create_vault_dir_with_initializer(dir.path(), "B", true, |target| {
            fs::create_dir_all(target.join(".knowlet")).unwrap();
            Ok(())
        })
        .unwrap_err();

        assert!(err.contains("contains files"));
        assert!(!target.join(".knowlet").exists());
        assert_eq!(
            fs::read_to_string(target.join("existing.md")).unwrap(),
            "# keep me"
        );
    }

    #[test]
    fn ignores_macos_metadata_when_deciding_empty_directory() {
        let dir = tempdir().unwrap();
        let target = dir.path().join("B");
        fs::create_dir(&target).unwrap();
        fs::write(target.join(".DS_Store"), "").unwrap();

        let vault = super::create_vault_dir_with_initializer(dir.path(), "B", true, |target| {
            fs::create_dir_all(target.join(".knowlet")).unwrap();
            Ok(())
        })
        .unwrap();

        assert_eq!(vault, target.canonicalize().unwrap());
        assert!(vault.join(".knowlet").is_dir());
    }

    #[test]
    fn rejects_new_vault_inside_existing_vault() {
        let dir = tempdir().unwrap();
        let outer = dir.path().join("outer");
        fs::create_dir_all(outer.join(".knowlet")).unwrap();

        let err = super::create_vault_dir_with_initializer(&outer, "nested", false, |_| Ok(()))
            .unwrap_err();

        assert!(err.contains("nested"));
        assert!(!outer.join("nested").exists());
    }

    #[test]
    fn delete_vault_local_files_uses_supplied_trash_remover() {
        let dir = tempdir().unwrap();
        let vault = dir.path().join("delete-me");
        fs::create_dir_all(vault.join(".knowlet")).unwrap();
        fs::write(vault.join("note.md"), "# keep recoverable").unwrap();
        let mut removed = Vec::new();

        super::delete_vault_local_files_with_remover(&vault, |path| {
            removed.push(path.to_path_buf());
            Ok(())
        })
        .unwrap();

        assert_eq!(removed, vec![vault.canonicalize().unwrap()]);
    }

    #[test]
    fn delete_vault_local_files_rejects_non_vault_folder() {
        let dir = tempdir().unwrap();
        let mut removed = false;

        let err = super::delete_vault_local_files_with_remover(dir.path(), |_| {
            removed = true;
            Ok(())
        })
        .unwrap_err();

        assert!(err.contains(".knowlet"));
        assert!(!removed);
    }

    #[test]
    fn rejects_frontend_dist_without_index() {
        let dir = tempdir().unwrap();

        let err = super::validate_frontend_dist(dir.path()).unwrap_err();

        assert!(err.contains("index.html"));
    }

    #[test]
    fn resolves_bundled_frontend_dist_before_dev_dist() {
        let dir = tempdir().unwrap();
        let macos_dir = dir.path().join("Contents").join("MacOS");
        let resources_dist = dir
            .path()
            .join("Contents")
            .join("Resources")
            .join("frontend-dist");
        let dev_dist = dir.path().join("dev-dist");
        fs::create_dir_all(&macos_dir).unwrap();
        fs::create_dir_all(&resources_dist).unwrap();
        fs::create_dir_all(&dev_dist).unwrap();
        fs::write(resources_dist.join("index.html"), "").unwrap();
        fs::write(dev_dist.join("index.html"), "").unwrap();
        let current_exe = macos_dir.join("knowlet-desktop");

        let dist = super::resolve_frontend_dist(&current_exe, &dev_dist).unwrap();

        assert_eq!(dist, resources_dist.canonicalize().unwrap());
    }

    #[test]
    fn resolves_dev_frontend_dist_when_bundle_resource_is_absent() {
        let dir = tempdir().unwrap();
        let macos_dir = dir.path().join("Contents").join("MacOS");
        let dev_dist = dir.path().join("dev-dist");
        fs::create_dir_all(&macos_dir).unwrap();
        fs::create_dir_all(&dev_dist).unwrap();
        fs::write(dev_dist.join("index.html"), "").unwrap();
        let current_exe = macos_dir.join("knowlet-desktop");

        let dist = super::resolve_frontend_dist(&current_exe, &dev_dist).unwrap();

        assert_eq!(dist, dev_dist.canonicalize().unwrap());
    }

    #[test]
    fn backend_program_prefers_override_binary() {
        let program = super::resolve_backend_program(
            Some("/tmp/knowlet-test-backend".into()),
            Path::new("/tmp/Knowlet.app/Contents/MacOS/knowlet-desktop"),
            Path::new("/repo"),
        )
        .unwrap();

        assert_eq!(program.executable, Path::new("/tmp/knowlet-test-backend"));
        assert!(program.prefix_args.is_empty());
    }

    #[test]
    fn backend_program_prefers_bundled_sidecar() {
        let dir = tempdir().unwrap();
        let macos_dir = dir.path().join("Contents").join("MacOS");
        fs::create_dir_all(&macos_dir).unwrap();
        let sidecar = macos_dir.join("knowlet-backend");
        fs::write(&sidecar, "").unwrap();
        let current_exe = macos_dir.join("knowlet-desktop");

        let program =
            super::resolve_backend_program(None, &current_exe, Path::new("/repo")).unwrap();

        assert_eq!(program.executable, sidecar);
        assert!(program.prefix_args.is_empty());
    }

    #[test]
    fn backend_program_falls_back_to_uv_for_dev() {
        let program = super::resolve_backend_program(
            None,
            Path::new("/tmp/knowlet-desktop"),
            Path::new("/repo"),
        )
        .unwrap();

        assert_eq!(program.executable, Path::new("uv"));
        assert_eq!(
            program.prefix_args,
            vec!["run", "--directory", "/repo", "knowlet"]
        );
    }
}
