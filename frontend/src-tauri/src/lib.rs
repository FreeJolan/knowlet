pub mod backend;
pub mod recent_vaults;

use std::path::PathBuf;
use std::sync::Mutex;

use backend::{resolve_frontend_dist, validate_vault_dir, BackendProcess, VAULT_ENV};
use recent_vaults::{
    load_valid_recent_vaults, record_recent_vault, resolve_startup_vault_with_recent,
};
use serde::Serialize;
use tauri::menu::{Menu, MenuItem, Submenu};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

const MENU_OPEN_VAULT: &str = "open-vault";
const MENU_OPEN_RECENT_VAULT: &str = "open-recent-vault";
const MENU_OPEN_RECENT_VAULT_EMPTY: &str = "open-recent-vault-empty";
const MENU_OPEN_RECENT_VAULT_PREFIX: &str = "open-recent-vault-";
const MENU_OPEN_DIGEST: &str = "open-digest";
const MENU_PULL_DIGEST: &str = "pull-digest";
const MENU_DIGEST_STATUS: &str = "digest-status";
const EVENT_OPEN_DIGEST: &str = "knowlet-open-digest";
const EVENT_PULL_DIGEST: &str = "knowlet-pull-digest";

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

#[tauri::command]
fn desktop_set_digest_status(app: tauri::AppHandle, status: String) -> Result<(), String> {
    update_digest_menu_status(&app, &status)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .menu(build_desktop_menu)
        .on_menu_event(|app, event| {
            if event.id() == MENU_OPEN_VAULT {
                if let Err(err) = open_vault_from_menu(app) {
                    show_desktop_error("Knowlet could not open that vault", &err);
                }
            } else if let Some(index) = parse_open_recent_vault_menu_id(event.id().as_ref()) {
                if let Err(err) = open_recent_vault_from_menu(app, index) {
                    show_desktop_error("Knowlet could not open that recent vault", &err);
                }
            } else if event.id() == MENU_OPEN_DIGEST {
                emit_to_main_window(app, EVENT_OPEN_DIGEST);
            } else if event.id() == MENU_PULL_DIGEST {
                emit_to_main_window(app, EVENT_PULL_DIGEST);
            }
        })
        .manage(DesktopState {
            backend: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            desktop_set_digest_status
        ])
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
            refresh_desktop_menu(app.handle()).map_err(|err| {
                show_startup_error(&err);
                err
            })?;

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
    show_desktop_error("Knowlet could not start", message);
}

fn show_desktop_error(title: &str, message: &str) {
    let _ = rfd::MessageDialog::new()
        .set_title(title)
        .set_description(message)
        .set_level(rfd::MessageLevel::Error)
        .show();
}

fn build_desktop_menu<R: tauri::Runtime>(handle: &tauri::AppHandle<R>) -> tauri::Result<Menu<R>> {
    let vault_menu = build_vault_menu(handle)?;
    let digest_menu = build_digest_menu(handle)?;
    let menu = Menu::default(handle)?;
    menu.insert(&vault_menu, 1)?;
    menu.insert(&digest_menu, 2)?;
    Ok(menu)
}

fn build_vault_menu<R: tauri::Runtime>(handle: &tauri::AppHandle<R>) -> tauri::Result<Submenu<R>> {
    let open_vault = MenuItem::with_id(
        handle,
        MENU_OPEN_VAULT,
        "Open Vault...",
        true,
        Some("CmdOrCtrl+O"),
    )?;
    let recent_vault = build_recent_vault_menu(handle)?;
    Submenu::with_id_and_items(
        handle,
        "vault",
        "Vault",
        true,
        &[&open_vault, &recent_vault],
    )
}

fn build_recent_vault_menu<R: tauri::Runtime>(
    handle: &tauri::AppHandle<R>,
) -> tauri::Result<Submenu<R>> {
    let recent_menu = Submenu::with_id(handle, MENU_OPEN_RECENT_VAULT, "Open Recent", true)?;
    let recent_vaults_path = recent_vaults_path(handle);
    let vaults = recent_vaults_path
        .as_ref()
        .map(|path| load_valid_recent_vaults(path))
        .unwrap_or_default();

    if vaults.is_empty() {
        let empty = MenuItem::with_id(
            handle,
            MENU_OPEN_RECENT_VAULT_EMPTY,
            "No Recent Vaults",
            false,
            None::<&str>,
        )?;
        recent_menu.append(&empty)?;
        return Ok(recent_menu);
    }

    for (index, vault) in vaults.iter().enumerate() {
        let item = MenuItem::with_id(
            handle,
            open_recent_vault_menu_id(index),
            recent_vault_menu_label(vault),
            true,
            None::<&str>,
        )?;
        recent_menu.append(&item)?;
    }
    Ok(recent_menu)
}

fn build_digest_menu<R: tauri::Runtime>(handle: &tauri::AppHandle<R>) -> tauri::Result<Submenu<R>> {
    let digest_status = MenuItem::with_id(
        handle,
        MENU_DIGEST_STATUS,
        digest_status_menu_label("idle"),
        false,
        None::<&str>,
    )?;
    let open_digest =
        MenuItem::with_id(handle, MENU_OPEN_DIGEST, "Open Digest", true, None::<&str>)?;
    let pull_digest = MenuItem::with_id(
        handle,
        MENU_PULL_DIGEST,
        "Pull Digest Now",
        true,
        None::<&str>,
    )?;
    Submenu::with_id_and_items(
        handle,
        "digest",
        "Digest",
        true,
        &[&digest_status, &open_digest, &pull_digest],
    )
}

fn refresh_desktop_menu(app: &tauri::AppHandle) -> Result<(), String> {
    let menu =
        build_desktop_menu(app).map_err(|err| format!("failed to rebuild desktop menu: {err}"))?;
    app.set_menu(menu)
        .map(|_| ())
        .map_err(|err| format!("failed to set desktop menu: {err}"))
}

fn recent_vaults_path<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|dir| dir.join("recent-vaults.json"))
        .map_err(|err| format!("failed to resolve desktop config directory: {err}"))
}

fn open_vault_from_menu(app: &tauri::AppHandle) -> Result<(), String> {
    let Some(path) = pick_vault_folder() else {
        return Ok(());
    };
    let vault = validate_vault_dir(&path)?;
    switch_to_vault(app, vault)
}

fn open_recent_vault_from_menu(app: &tauri::AppHandle, index: usize) -> Result<(), String> {
    let recent_vaults_path = recent_vaults_path(app)?;
    let vaults = load_valid_recent_vaults(&recent_vaults_path);
    let vault = vaults
        .get(index)
        .ok_or_else(|| "recent vault is no longer available".to_string())?
        .clone();
    switch_to_vault(app, vault)
}

fn switch_to_vault(app: &tauri::AppHandle, vault: PathBuf) -> Result<(), String> {
    let current_vault = app
        .state::<DesktopState>()
        .backend
        .lock()
        .map_err(|_| "desktop backend state lock poisoned".to_string())?
        .as_ref()
        .map(|backend| backend.vault.clone());
    if current_vault.as_ref() == Some(&vault) {
        record_vault_as_recent(app, &vault);
        return refresh_desktop_menu(app);
    }

    let current_exe = std::env::current_exe()
        .map_err(|err| format!("failed to resolve current executable: {err}"))?;
    let dev_frontend_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../dist");
    let frontend_dist = resolve_frontend_dist(&current_exe, &dev_frontend_dist)?;
    let backend = BackendProcess::start(vault.clone(), frontend_dist)?;
    let url = backend.url.clone();

    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "Knowlet main window is not available".to_string())?;
    window
        .navigate(url.parse().map_err(|err| format!("{err}"))?)
        .map_err(|err| format!("failed to navigate Knowlet window: {err}"))?;

    *app.state::<DesktopState>()
        .backend
        .lock()
        .map_err(|_| "desktop backend state lock poisoned".to_string())? = Some(backend);
    record_vault_as_recent(app, &vault);
    refresh_desktop_menu(app)
}

fn record_vault_as_recent(app: &tauri::AppHandle, vault: &std::path::Path) {
    if let Ok(recent_vaults_path) = recent_vaults_path(app) {
        let _ = record_recent_vault(&recent_vaults_path, vault);
    }
}

fn open_recent_vault_menu_id(index: usize) -> String {
    format!("{MENU_OPEN_RECENT_VAULT_PREFIX}{index}")
}

fn parse_open_recent_vault_menu_id(id: &str) -> Option<usize> {
    id.strip_prefix(MENU_OPEN_RECENT_VAULT_PREFIX)?.parse().ok()
}

fn recent_vault_menu_label(path: &std::path::Path) -> String {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_else(|| path.to_str().unwrap_or("Vault"));
    match path.parent().and_then(|parent| parent.to_str()) {
        Some(parent) if !parent.is_empty() => format!("{name} ({parent})"),
        _ => name.to_string(),
    }
}

fn emit_to_main_window(app: &tauri::AppHandle, event: &str) {
    let _ = app.emit_to("main", event, ());
}

fn update_digest_menu_status(app: &tauri::AppHandle, status: &str) -> Result<(), String> {
    let Some(menu) = app.menu() else {
        return Ok(());
    };
    let Some(item) = menu.get(MENU_DIGEST_STATUS) else {
        return Ok(());
    };
    let Some(item) = item.as_menuitem() else {
        return Ok(());
    };
    item.set_text(digest_status_menu_label(status))
        .map_err(|err| format!("failed to update Digest menu status: {err}"))?;
    item.set_enabled(false)
        .map_err(|err| format!("failed to disable Digest menu status: {err}"))
}

fn digest_status_menu_label(status: &str) -> &'static str {
    match status {
        "running" => "Status: Pulling...",
        "ok" => "Status: Updated",
        "error" => "Status: Needs Attention",
        "paused" => "Status: Paused",
        _ => "Status: Idle",
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn digest_status_menu_label_maps_known_states() {
        assert_eq!(
            super::digest_status_menu_label("running"),
            "Status: Pulling..."
        );
        assert_eq!(super::digest_status_menu_label("ok"), "Status: Updated");
        assert_eq!(
            super::digest_status_menu_label("error"),
            "Status: Needs Attention"
        );
        assert_eq!(super::digest_status_menu_label("paused"), "Status: Paused");
        assert_eq!(super::digest_status_menu_label("idle"), "Status: Idle");
        assert_eq!(super::digest_status_menu_label("unknown"), "Status: Idle");
    }

    #[test]
    fn open_recent_vault_menu_id_round_trips_index() {
        assert_eq!(
            super::parse_open_recent_vault_menu_id("open-recent-vault-3"),
            Some(3)
        );
        assert_eq!(
            super::parse_open_recent_vault_menu_id("open-recent-vault-not-a-number"),
            None
        );
        assert_eq!(super::parse_open_recent_vault_menu_id("open-vault"), None);
    }

    #[test]
    fn recent_vault_menu_label_includes_leaf_and_parent() {
        let path = std::path::Path::new("/tmp/knowlet-vaults/research");

        assert_eq!(
            super::recent_vault_menu_label(path),
            "research (/tmp/knowlet-vaults)"
        );
    }
}
