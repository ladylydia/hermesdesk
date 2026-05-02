//! Read / write WeCom (企业微信) bot credentials in ``hermes-home/.env``.

use std::path::PathBuf;
use tauri::AppHandle;

#[tauri::command]
pub fn cmd_wecom_env_status(
    app: AppHandle,
) -> Result<crate::gateway_supervisor::WeComEnvSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    Ok(crate::gateway_supervisor::read_wecom_env_snapshot(&hh))
}

#[tauri::command]
pub fn cmd_wecom_env_remove(app: AppHandle) -> Result<(), String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let lines: Vec<String> = content
        .lines()
        .map(|l| l.to_string())
        .filter(|line| {
            let trimmed = line.trim();
            !trimmed.starts_with("WECOM_")
        })
        .collect();
    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_wecom_save_config(
    app: AppHandle,
    bot_id: String,
    secret: String,
    open_access: Option<bool>,
) -> Result<(), String> {
    let bid = bot_id.trim();
    let s = secret.trim();
    if bid.is_empty() {
        return Err("WECOM_BOT_ID must not be empty".into());
    }
    if s.is_empty() {
        return Err("WECOM_SECRET must not be empty".into());
    }

    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    std::fs::create_dir_all(&hh).map_err(|e| e.to_string())?;

    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    let mut found_id = false;
    let mut found_secret = false;
    let mut found_dm = false;
    let mut found_allow_all = false;
    let mut found_setup_method = false;
    let dm_value = if open_access.unwrap_or(true) { "open" } else { "pairing" };
    let allow_all_value = if open_access.unwrap_or(true) { "true" } else { "false" };
    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("WECOM_BOT_ID=") || trimmed.starts_with("WECOM_BOT_ID ") {
            *line = format!("WECOM_BOT_ID={}", bid);
            found_id = true;
        } else if trimmed.starts_with("WECOM_SECRET=") || trimmed.starts_with("WECOM_SECRET ") {
            *line = format!("WECOM_SECRET={}", s);
            found_secret = true;
        } else if trimmed.starts_with("WECOM_DM_POLICY=") || trimmed.starts_with("WECOM_DM_POLICY ") {
            *line = format!("WECOM_DM_POLICY={}", dm_value);
            found_dm = true;
        } else if trimmed.starts_with("WECOM_ALLOW_ALL_USERS=") || trimmed.starts_with("WECOM_ALLOW_ALL_USERS ") {
            *line = format!("WECOM_ALLOW_ALL_USERS={}", allow_all_value);
            found_allow_all = true;
        } else if trimmed.starts_with("WECOM_SETUP_METHOD=") || trimmed.starts_with("WECOM_SETUP_METHOD ") {
            *line = "WECOM_SETUP_METHOD=manual".to_string();
            found_setup_method = true;
        }
    }
    if !found_id {
        lines.push(format!("WECOM_BOT_ID={}", bid));
    }
    if !found_secret {
        lines.push(format!("WECOM_SECRET={}", s));
    }
    if !found_dm {
        lines.push(format!("WECOM_DM_POLICY={}", dm_value));
    }
    if !found_allow_all {
        lines.push(format!("WECOM_ALLOW_ALL_USERS={}", allow_all_value));
    }
    if !found_setup_method {
        lines.push("WECOM_SETUP_METHOD=manual".to_string());
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
