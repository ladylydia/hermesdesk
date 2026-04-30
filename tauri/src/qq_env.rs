//! Read-only view of QQ Bot credentials in ``hermes-home/.env`` (no secrets in IPC payloads).

use tauri::AppHandle;

/// Whether ``QQ_APP_ID`` + ``QQ_CLIENT_SECRET`` are set (secret value is never returned).
#[tauri::command]
pub fn cmd_qq_env_status(app: AppHandle) -> Result<crate::gateway_supervisor::QqEnvSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    Ok(crate::gateway_supervisor::read_qq_env_snapshot(&hh))
}
