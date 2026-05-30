pub mod backend;
pub mod recent_vaults;

use std::path::PathBuf;
use std::sync::Mutex;

use backend::{resolve_frontend_dist, BackendProcess, VAULT_ENV};
use recent_vaults::resolve_startup_vault_with_recent;
use serde::Serialize;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct DesktopState {
    backend: Mutex<Option<BackendProcess>>,
}

#[derive(Serialize)]
struct DesktopStatus {
    backend_url: String,
    vault: String,
}

#[tauri::command]
fn desktop_status(state: tauri::State<'_, DesktopState>) -> Result<DesktopStatus, String> {
    let backend = state
        .backend
        .lock()
        .map_err(|_| "desktop backend state lock poisoned".to_string())?;
    let backend = backend
        .as_ref()
        .ok_or_else(|| "knowlet backend is not running".to_string())?;
    Ok(DesktopStatus {
        backend_url: backend.url.clone(),
        vault: backend.vault.display().to_string(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(DesktopState {
            backend: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![desktop_status])
        .setup(|app| {
            let recent_vaults_path = app
                .path()
                .app_config_dir()
                .map_err(|err| format!("failed to resolve desktop config directory: {err}"))?
                .join("recent-vaults.json");
            let vault = resolve_startup_vault_with_recent(
                std::env::var_os(VAULT_ENV),
                &recent_vaults_path,
                pick_vault_folder,
            )
            .map_err(|err| {
                show_startup_error(&err);
                err
            })?;
            let current_exe = std::env::current_exe()
                .map_err(|err| format!("failed to resolve current executable: {err}"))?;
            let dev_frontend_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../dist");
            let frontend_dist =
                resolve_frontend_dist(&current_exe, &dev_frontend_dist).map_err(|err| {
                    show_startup_error(&err);
                    err
                })?;
            let backend = BackendProcess::start(vault, frontend_dist).map_err(|err| {
                show_startup_error(&err);
                err
            })?;
            let url = backend.url.clone();
            *app.state::<DesktopState>()
                .backend
                .lock()
                .map_err(|_| "desktop backend state lock poisoned".to_string())? = Some(backend);

            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(url.parse().map_err(|err| format!("{err}"))?),
            )
            .title("Knowlet")
            .inner_size(1280.0, 860.0)
            .min_inner_size(980.0, 640.0)
            .resizable(true)
            .build()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Knowlet desktop");
}

fn pick_vault_folder() -> Option<PathBuf> {
    rfd::FileDialog::new()
        .set_title("Choose a Knowlet vault")
        .pick_folder()
}

fn show_startup_error(message: &str) {
    let _ = rfd::MessageDialog::new()
        .set_title("Knowlet could not start")
        .set_description(message)
        .set_level(rfd::MessageLevel::Error)
        .show();
}
