use std::ffi::OsString;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const LOOPBACK_HOST: &str = "127.0.0.1";
const VAULT_MARKER_DIR: &str = ".knowlet";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const BACKEND_BIN_NAME: &str = "knowlet-backend";
const FRONTEND_DIST_RESOURCE: &str = "frontend-dist";
pub const BACKEND_BIN_ENV: &str = "KNOWLET_BACKEND_BIN";
pub const VAULT_ENV: &str = "KNOWLET_VAULT";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendProgram {
    pub executable: PathBuf,
    pub prefix_args: Vec<String>,
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
    let marker = path.join(VAULT_MARKER_DIR);
    if !marker.is_dir() {
        return Err(format!(
            "selected directory is not a knowlet vault: missing {}",
            VAULT_MARKER_DIR
        ));
    }
    path.canonicalize()
        .map_err(|err| format!("failed to resolve vault path: {err}"))
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

        let mut cmd = Command::new(&backend_program.executable);
        cmd.args(&backend_program.prefix_args)
            .args(["web", "--host", LOOPBACK_HOST, "--port", &port.to_string()])
            .env("KNOWLET_VAULT", &vault)
            .env("KNOWLET_FRONTEND_DIST", &frontend_dist)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        let child = cmd
            .spawn()
            .map_err(|err| format!("failed to start knowlet backend: {err}"))?;
        let mut child = child;
        if let Err(err) = wait_for_health(port, HEALTH_TIMEOUT) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(err);
        }

        Ok(Self { child, url, vault })
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
    fn rejects_directory_without_knowlet_marker() {
        let dir = tempdir().unwrap();

        let err = super::validate_vault_dir(dir.path()).unwrap_err();

        assert!(err.contains(".knowlet"));
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
        let port = super::find_available_port().unwrap();
        let listener = TcpListener::bind(("127.0.0.1", port)).unwrap();

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
