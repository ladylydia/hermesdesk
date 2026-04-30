//! Read / write Telegram bot env in ``hermes-home/.env`` (bot token never returned in full).

use std::path::PathBuf;
use tauri::AppHandle;

#[tauri::command]
pub fn cmd_telegram_env_status(app: AppHandle) -> Result<crate::gateway_supervisor::TelegramEnvSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    Ok(crate::gateway_supervisor::read_telegram_env_snapshot(&hh))
}

#[tauri::command]
pub fn cmd_telegram_save_token(app: AppHandle, token: String) -> Result<(), String> {
    let token = token.trim().to_string();
    if token.is_empty() {
        return Err("Bot token must not be empty".into());
    }

    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = crate::gateway_supervisor::hermes_home_path(&data_dir);
    std::fs::create_dir_all(&hh).map_err(|e| e.to_string())?;

    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();

    let mut found = false;
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("TELEGRAM_BOT_TOKEN=") || trimmed.starts_with("TELEGRAM_BOT_TOKEN ") {
            *line = format!("TELEGRAM_BOT_TOKEN={}", token);
            found = true;
            break;
        }
    }

    if !found {
        lines.push(format!("TELEGRAM_BOT_TOKEN={}", token));
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
