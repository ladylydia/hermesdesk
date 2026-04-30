//! Path helpers + workspace setup.

use anyhow::{Context, Result};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

const SETTING_POWER_USER: &str = "hermesdesk.power_user";
const SETTING_WORKSPACE: &str = "hermesdesk.workspace";
const SETTING_SHOW_RECIPE_MARKET: &str = "hermesdesk.show_recipe_market";
const SETTING_AUTO_GATEWAY: &str = "hermesdesk.auto_start_gateway";

/// Resolve `%USERPROFILE%\Documents\HermesWork`, creating it if missing.
pub fn ensure_workspace(app: &AppHandle) -> Result<PathBuf> {
    let custom = read_setting(app, SETTING_WORKSPACE);
    let chosen = match custom {
        Some(p) if !p.is_empty() => PathBuf::from(p),
        _ => default_workspace(app)?,
    };
    std::fs::create_dir_all(&chosen)
        .with_context(|| format!("creating workspace {}", chosen.display()))?;
    Ok(chosen)
}

fn default_workspace(app: &AppHandle) -> Result<PathBuf> {
    let docs = app.path().document_dir().context("document dir")?;
    Ok(docs.join("HermesWork"))
}

/// `%LOCALAPPDATA%\HermesDesk` — writable per-user state.
pub fn ensure_data_dir(app: &AppHandle) -> Result<PathBuf> {
    let dir = app.path().app_local_data_dir().context("local data dir")?;
    std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;
    Ok(dir)
}

/// Find the bundled Python runtime. In dev: `python/dist/runtime` at the repo root
/// (see `../python/dist/runtime` in `tauri.conf.json` for release bundles).
/// In prod: `resources/runtime` next to the installed app.
///
/// Set `HERMESDESK_RUNTIME_DIR` to an absolute path to force the bundle (e.g. after
/// `build_bundle.ps1` when automatic discovery fails).
pub fn resolve_runtime_dir(app: &AppHandle) -> Result<PathBuf> {
    if let Ok(force) = std::env::var("HERMESDESK_RUNTIME_DIR") {
        let p = PathBuf::from(force.trim());
        if p.join("python").join("python.exe").exists() {
            return Ok(p);
        }
        anyhow::bail!(
            "HERMESDESK_RUNTIME_DIR is set but python.exe not found under {}",
            p.display()
        );
    }

    // `cargo run` / `cargo run --release` puts the binary at `repo/tauri/target/{debug,release}/`.
    // Tauri also copies `../python/dist/runtime` into `target/.../resources/runtime`, but that
    // copy is easy to get **stale** (missing new files like `tools/.../file_sync.py`) after
    // `build_bundle` without a full tauri rebuild. Prefer the repo's canonical runtime first.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(repo_root) = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
        {
            let from_repo = repo_root.join("python").join("dist").join("runtime");
            if from_repo.join("python").join("python.exe").exists() {
                return Ok(from_repo);
            }
        }
    }

    let res = app.path().resource_dir().context("resource dir")?;
    let candidate = res.join("runtime");
    if candidate.join("python").join("python.exe").exists() {
        return Ok(candidate);
    }
    anyhow::bail!(
        "Could not locate runtime/. Looked at {}",
        candidate.display()
    )
}

pub fn is_power_user(app: &AppHandle) -> bool {
    matches!(read_setting(app, SETTING_POWER_USER).as_deref(), Some("1" | "true"))
}

pub fn is_show_recipe_market(app: &AppHandle) -> bool {
    matches!(
        read_setting(app, SETTING_SHOW_RECIPE_MARKET).as_deref(),
        Some("1" | "true")
    )
}

/// When true (default), **first app launch** starts ``hermes gateway run`` if ``hermes-home/.env`` looks configured.
/// Restarting embedded Hermes (e.g. after Weixin login) always starts the gateway when configured, regardless of this flag.
pub fn is_auto_start_gateway(app: &AppHandle) -> bool {
    match read_setting(app, SETTING_AUTO_GATEWAY).as_deref() {
        Some("0" | "false" | "no") => false,
        _ => true,
    }
}

pub fn set_auto_start_gateway_enabled(app: &AppHandle, enabled: bool) -> Result<(), String> {
    write_setting(
        app,
        SETTING_AUTO_GATEWAY,
        if enabled { "1" } else { "0" },
    )
    .map_err(|e| e.to_string())
}

/// Mirror the setting into the data dir so embedded Python can read `/api/status` without a process restart.
pub fn sync_show_recipe_market_flag(app: &AppHandle) -> Result<()> {
    let dir = ensure_data_dir(app)?;
    let path = dir.join("hermesdesk_show_recipe_market.txt");
    let bytes: &[u8] = if is_show_recipe_market(app) {
        b"1\n"
    } else {
        b"0\n"
    };
    std::fs::write(&path, bytes).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

fn read_setting(app: &AppHandle, _key: &str) -> Option<String> {
    // Tiny KV store backed by a JSON file under app_local_data_dir; we keep
    // the implementation here intentionally simple.
    let data_dir = app.path().app_local_data_dir().ok()?;
    let f = data_dir.join("settings.json");
    let raw = std::fs::read_to_string(f).ok()?;
    let v: serde_json::Value = serde_json::from_str(&raw).ok()?;
    v.get(_key).and_then(|x| x.as_str()).map(|s| s.to_string())
}

// ---- IPC commands ---------------------------------------------------------

#[tauri::command]
pub fn cmd_workspace_path(app: AppHandle) -> Result<String, String> {
    ensure_workspace(&app).map(|p| p.display().to_string()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_open_workspace(app: AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let p = ensure_workspace(&app).map_err(|e| e.to_string())?;
    app.opener()
        .open_path(p.to_string_lossy(), None::<&str>)
        .map_err(|e| e.to_string())
}

fn write_setting(app: &AppHandle, key: &str, value: &str) -> Result<()> {
    let dir = app.path().app_local_data_dir().context("local data dir")?;
    std::fs::create_dir_all(&dir)?;
    let f = dir.join("settings.json");
    let mut v: serde_json::Value = std::fs::read_to_string(&f)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(serde_json::json!({}));
    v[key] = serde_json::Value::String(value.to_string());
    std::fs::write(&f, serde_json::to_vec_pretty(&v)?)?;
    Ok(())
}

#[tauri::command]
pub fn cmd_get_power_user(app: AppHandle) -> Result<bool, String> {
    Ok(is_power_user(&app))
}

/// Persist the flag; callers that need new `HERMESDESK_POWER_USER` in the child
/// must restart embedded Python (see `lib::respawn_embedded_hermes_python`).
pub fn set_power_user_enabled(app: &AppHandle, enabled: bool) -> Result<(), String> {
    write_setting(app, SETTING_POWER_USER, if enabled { "1" } else { "0" })
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_get_show_recipe_market(app: AppHandle) -> Result<bool, String> {
    Ok(is_show_recipe_market(&app))
}

#[tauri::command]
pub fn cmd_set_show_recipe_market(app: AppHandle, enabled: bool) -> Result<(), String> {
    write_setting(
        &app,
        SETTING_SHOW_RECIPE_MARKET,
        if enabled { "1" } else { "0" },
    )
    .map_err(|e| e.to_string())?;
    sync_show_recipe_market_flag(&app).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_set_personality(app: AppHandle, name: String) -> Result<(), String> {
    write_setting(&app, "hermesdesk.personality", &name)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_get_auto_start_gateway(app: AppHandle) -> Result<bool, String> {
    Ok(is_auto_start_gateway(&app))
}

#[tauri::command]
pub fn cmd_set_auto_start_gateway(app: AppHandle, enabled: bool) -> Result<(), String> {
    set_auto_start_gateway_enabled(&app, enabled)
}
