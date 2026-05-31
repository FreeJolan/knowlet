use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::backend::validate_vault_dir;

const RECENT_VAULTS_VERSION: u8 = 1;
const MAX_RECENT_VAULTS: usize = 8;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RecentVaultsFile {
    version: u8,
    vaults: Vec<PathBuf>,
}

impl Default for RecentVaultsFile {
    fn default() -> Self {
        Self {
            version: RECENT_VAULTS_VERSION,
            vaults: Vec::new(),
        }
    }
}

pub fn load_recent_vaults(path: &Path) -> Result<Vec<PathBuf>, String> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let content =
        fs::read_to_string(path).map_err(|err| format!("failed to read recent vaults: {err}"))?;
    let file: RecentVaultsFile = serde_json::from_str(&content)
        .map_err(|err| format!("failed to parse recent vaults: {err}"))?;
    Ok(dedupe_and_limit(file.vaults))
}

pub fn save_recent_vaults(path: &Path, vaults: &[PathBuf]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|err| format!("failed to create desktop config directory: {err}"))?;
    }

    let file = RecentVaultsFile {
        version: RECENT_VAULTS_VERSION,
        vaults: dedupe_and_limit(vaults.to_vec()),
    };
    let content = serde_json::to_string_pretty(&file)
        .map_err(|err| format!("failed to serialize recent vaults: {err}"))?;
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, content).map_err(|err| format!("failed to write recent vaults: {err}"))?;
    fs::rename(&tmp_path, path).map_err(|err| format!("failed to replace recent vaults: {err}"))
}

pub fn record_recent_vault(path: &Path, vault: &Path) -> Result<(), String> {
    let mut vaults = load_recent_vaults(path).unwrap_or_default();
    vaults.retain(|candidate| candidate != vault);
    vaults.insert(0, vault.to_path_buf());
    save_recent_vaults(path, &vaults)
}

pub fn forget_recent_vault(path: &Path, vault: &Path) -> Result<bool, String> {
    let mut vaults = load_recent_vaults(path).unwrap_or_default();
    let before = vaults.len();
    vaults.retain(|candidate| candidate != vault);
    if vaults.len() == before {
        return Ok(false);
    }
    save_recent_vaults(path, &vaults)?;
    Ok(true)
}

pub fn load_valid_recent_vaults(path: &Path) -> Vec<PathBuf> {
    let recent_vaults = load_recent_vaults(path).unwrap_or_default();
    let still_valid = recent_vaults
        .iter()
        .filter_map(|candidate| validate_vault_dir(candidate).ok())
        .collect::<Vec<_>>();
    if recent_vaults != still_valid {
        let _ = save_recent_vaults(path, &still_valid);
    }
    still_valid
}

pub fn resolve_startup_vault_with_recent(
    env_vault: Option<OsString>,
    recent_vaults_path: &Path,
    pick_folder: impl FnOnce() -> Option<PathBuf>,
) -> Result<PathBuf, String> {
    if let Some(path) = env_vault {
        let vault = validate_vault_dir(&PathBuf::from(path))?;
        let _ = record_recent_vault(recent_vaults_path, &vault);
        return Ok(vault);
    }

    let still_valid = load_valid_recent_vaults(recent_vaults_path);
    if let Some(vault) = still_valid.first() {
        return Ok(vault.clone());
    }

    let Some(path) = pick_folder() else {
        return Err("no Knowlet vault selected".to_string());
    };
    let vault = validate_vault_dir(&path)?;
    let _ = record_recent_vault(recent_vaults_path, &vault);
    Ok(vault)
}

fn dedupe_and_limit(vaults: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut unique = Vec::new();
    for vault in vaults {
        if !unique.contains(&vault) {
            unique.push(vault);
        }
        if unique.len() == MAX_RECENT_VAULTS {
            break;
        }
    }
    unique
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;
    use std::fs;
    use std::path::{Path, PathBuf};

    use tempfile::tempdir;

    fn make_vault(root: &Path, name: &str) -> PathBuf {
        let vault = root.join(name);
        fs::create_dir_all(vault.join(".knowlet")).unwrap();
        vault.canonicalize().unwrap()
    }

    #[test]
    fn records_recent_vaults_with_latest_first_and_no_duplicates() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let first = make_vault(dir.path(), "first");
        let second = make_vault(dir.path(), "second");

        super::record_recent_vault(&store, &first).unwrap();
        super::record_recent_vault(&store, &second).unwrap();
        super::record_recent_vault(&store, &first).unwrap();

        assert_eq!(
            super::load_recent_vaults(&store).unwrap(),
            vec![first, second]
        );
    }

    #[test]
    fn limits_recent_vault_list() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let vaults = (0..10)
            .map(|index| make_vault(dir.path(), &format!("vault-{index}")))
            .collect::<Vec<_>>();

        super::save_recent_vaults(&store, &vaults).unwrap();

        let saved = super::load_recent_vaults(&store).unwrap();
        assert_eq!(saved.len(), super::MAX_RECENT_VAULTS);
        assert_eq!(saved[0], vaults[0]);
        assert_eq!(saved[7], vaults[7]);
    }

    #[test]
    fn startup_prefers_environment_vault_and_records_it() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let vault = make_vault(dir.path(), "env-vault");

        let selected = super::resolve_startup_vault_with_recent(
            Some(vault.clone().into_os_string()),
            &store,
            || panic!("folder picker should not run when KNOWLET_VAULT is present"),
        )
        .unwrap();

        assert_eq!(selected, vault);
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![selected]);
    }

    #[test]
    fn startup_reopens_first_valid_recent_vault_without_picker() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let vault = make_vault(dir.path(), "recent-vault");
        super::save_recent_vaults(&store, &[vault.clone()]).unwrap();

        let selected = super::resolve_startup_vault_with_recent(None, &store, || {
            panic!("folder picker should not run when a recent vault is valid")
        })
        .unwrap();

        assert_eq!(selected, vault);
    }

    #[test]
    fn startup_ignores_invalid_recent_vaults_and_uses_picker() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let stale = dir.path().join("stale-vault");
        let picked = make_vault(dir.path(), "picked-vault");
        super::save_recent_vaults(&store, &[stale]).unwrap();
        let picker_calls = Cell::new(0);

        let selected = super::resolve_startup_vault_with_recent(None, &store, || {
            picker_calls.set(picker_calls.get() + 1);
            Some(picked.clone())
        })
        .unwrap();

        assert_eq!(selected, picked);
        assert_eq!(picker_calls.get(), 1);
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![picked]);
    }

    #[test]
    fn startup_uses_picker_when_recent_file_is_corrupt() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        fs::write(&store, "{not-json").unwrap();
        let picked = make_vault(dir.path(), "picked-vault");

        let selected =
            super::resolve_startup_vault_with_recent(None, &store, || Some(picked.clone()))
                .unwrap();

        assert_eq!(selected, picked);
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![picked]);
    }

    #[test]
    fn valid_recent_vaults_prunes_stale_entries() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let stale = dir.path().join("stale-vault");
        let valid = make_vault(dir.path(), "valid-vault");
        super::save_recent_vaults(&store, &[stale.clone(), valid.clone()]).unwrap();

        let valid_vaults = super::load_valid_recent_vaults(&store);

        assert_eq!(valid_vaults, vec![valid.clone()]);
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![valid]);
    }

    #[test]
    fn forget_recent_vault_removes_record_without_touching_folder() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let first = make_vault(dir.path(), "first");
        let second = make_vault(dir.path(), "second");
        super::save_recent_vaults(&store, &[first.clone(), second.clone()]).unwrap();

        let removed = super::forget_recent_vault(&store, &first).unwrap();

        assert!(removed);
        assert!(first.exists());
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![second]);
    }

    #[test]
    fn forget_recent_vault_reports_missing_without_rewriting() {
        let dir = tempdir().unwrap();
        let store = dir.path().join("recent-vaults.json");
        let first = make_vault(dir.path(), "first");
        super::save_recent_vaults(&store, std::slice::from_ref(&first)).unwrap();

        let removed = super::forget_recent_vault(&store, &dir.path().join("missing")).unwrap();

        assert!(!removed);
        assert_eq!(super::load_recent_vaults(&store).unwrap(), vec![first]);
    }
}
