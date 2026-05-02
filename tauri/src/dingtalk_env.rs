//! Read / write DingTalk app credentials in ``hermes-home/.env``.

use std::path::PathBuf;
use tauri::AppHandle;

#[tauri::command]
pub fn cmd_dingtalk_env_status(
    app: AppHandle,
) -> Result<crate::gateway_supervisor::DingTalkEnvSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    Ok(crate::gateway_supervisor::read_dingtalk_env_snapshot(&hh))
}

#[tauri::command]
pub fn cmd_dingtalk_env_remove(app: AppHandle) -> Result<(), String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let lines: Vec<String> = content
        .lines()
        .map(|l| l.to_string())
        .filter(|line| {
            let trimmed = line.trim();
            !trimmed.starts_with("DINGTALK_")
        })
        .collect();
    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_dingtalk_save_config(
    app: AppHandle,
    client_id: String,
    client_secret: String,
) -> Result<(), String> {
    let cid = client_id.trim();
    let csec = client_secret.trim();
    if cid.is_empty() {
        return Err("DINGTALK_CLIENT_ID must not be empty".into());
    }
    if csec.is_empty() {
        return Err("DINGTALK_CLIENT_SECRET must not be empty".into());
    }
    crate::validation::validate_env_value(cid)?;
    crate::validation::validate_env_value(csec)?;

    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    std::fs::create_dir_all(&hh).map_err(|e| e.to_string())?;

    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    let mut found_id = false;
    let mut found_secret = false;
    let mut found_allow_all = false;
    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("DINGTALK_CLIENT_ID=") || trimmed.starts_with("DINGTALK_CLIENT_ID ") {
            *line = format!("DINGTALK_CLIENT_ID={}", cid);
            found_id = true;
        } else if trimmed.starts_with("DINGTALK_CLIENT_SECRET=") || trimmed.starts_with("DINGTALK_CLIENT_SECRET ") {
            *line = format!("DINGTALK_CLIENT_SECRET={}", csec);
            found_secret = true;
        } else if trimmed.starts_with("DINGTALK_ALLOW_ALL_USERS=") || trimmed.starts_with("DINGTALK_ALLOW_ALL_USERS ") {
            *line = "DINGTALK_ALLOW_ALL_USERS=true".to_string();
            found_allow_all = true;
        }
    }
    if !found_id {
        lines.push(format!("DINGTALK_CLIENT_ID={}", cid));
    }
    if !found_secret {
        lines.push(format!("DINGTALK_CLIENT_SECRET={}", csec));
    }
    if !found_allow_all {
        lines.push("DINGTALK_ALLOW_ALL_USERS=true".to_string());
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
