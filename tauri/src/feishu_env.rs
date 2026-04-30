//! Read-only view of Feishu / Lark app credentials in ``hermes-home/.env``.

use tauri::AppHandle;

/// Whether ``FEISHU_APP_ID`` + ``FEISHU_APP_SECRET`` are set (secret value is never returned).
#[tauri::command]
pub fn cmd_feishu_env_status(app: AppHandle) -> Result<crate::gateway_supervisor::FeishuEnvSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    Ok(crate::gateway_supervisor::read_feishu_env_snapshot(&hh))
}
