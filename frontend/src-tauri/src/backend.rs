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
pub const VAULT_ENV: &str = "KNOWLET_VAULT";

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

pub struct BackendProcess {
    child: Child,
    pub url: String,
    pub vault: PathBuf,
}

impl BackendProcess {
    pub fn start(vault: PathBuf, frontend_dist: PathBuf) -> Result<Self, String> {
        let vault = validate_vault_dir(&vault)?;
        let port = find_available_port()?;
        let url = backend_url(port);
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .ok_or_else(|| "failed to resolve repository root".to_string())?
            .to_path_buf();

        let mut cmd = Command::new("uv");
        cmd.args([
            "run",
            "--directory",
            repo_root
                .to_str()
                .ok_or_else(|| "repository path is not valid UTF-8".to_string())?,
            "knowlet",
            "web",
            "--host",
            LOOPBACK_HOST,
            "--port",
            &port.to_string(),
        ])
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
}
