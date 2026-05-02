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
    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("WECOM_BOT_ID=") || trimmed.starts_with("WECOM_BOT_ID ") {
            *line = format!("WECOM_BOT_ID={}", bid);
            found_id = true;
        } else if trimmed.starts_with("WECOM_SECRET=") || trimmed.starts_with("WECOM_SECRET ") {
            *line = format!("WECOM_SECRET={}", s);
            found_secret = true;
        }
    }
    if !found_id {
        lines.push(format!("WECOM_BOT_ID={}", bid));
    }
    if !found_secret {
        lines.push(format!("WECOM_SECRET={}", s));
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
