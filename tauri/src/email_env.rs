//! Read / write EMAIL_* env vars in ``hermes-home/.env``.

use std::path::PathBuf;
use tauri::AppHandle;

const EMAIL_ENV_PREFIXES: &[&str] = &[
    "EMAIL_ADDRESS=",
    "EMAIL_ADDRESS ",
    "EMAIL_PASSWORD=",
    "EMAIL_PASSWORD ",
    "EMAIL_IMAP_HOST=",
    "EMAIL_IMAP_HOST ",
    "EMAIL_SMTP_HOST=",
    "EMAIL_SMTP_HOST ",
    "EMAIL_IMAP_PORT=",
    "EMAIL_IMAP_PORT ",
    "EMAIL_SMTP_PORT=",
    "EMAIL_SMTP_PORT ",
    "EMAIL_POLL_INTERVAL=",
    "EMAIL_ALLOWED_USERS=",
    "EMAIL_ALLOWED_USERS ",
    "EMAIL_ALLOW_ALL_USERS=",
    "EMAIL_ALLOW_ALL_USERS ",
    "EMAIL_HOME_ADDRESS=",
    "EMAIL_HOME_ADDRESS ",
    "EMAIL_HOME_ADDRESS_NAME=",
];

fn hh(app: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = crate::paths::ensure_data_dir(app).map_err(|e| e.to_string())?;
    Ok(crate::gateway_supervisor::hermes_home_path(&data_dir))
}

#[derive(serde::Serialize)]
pub struct EmailEnvSnapshot {
    pub configured: bool,
    pub has_address: bool,
    pub has_password: bool,
    pub has_imap_host: bool,
    pub has_smtp_host: bool,
    pub address_hint: Option<String>,
}

#[tauri::command]
pub fn cmd_email_env_status(app: AppHandle) -> Result<EmailEnvSnapshot, String> {
    let hh = hh(&app)?;
    let keys = crate::gateway_supervisor::parse_dotenv_upper(&hh);
    let nonempty = |k: &str| keys.get(k).map(|s| !s.is_empty()).unwrap_or(false);
    let address = keys.get("EMAIL_ADDRESS").cloned();
    let has_address = nonempty("EMAIL_ADDRESS");
    let has_password = nonempty("EMAIL_PASSWORD");
    let has_imap_host = nonempty("EMAIL_IMAP_HOST");
    let has_smtp_host = nonempty("EMAIL_SMTP_HOST");
    let configured = has_address && has_password && has_imap_host && has_smtp_host;
    let address_hint = address.map(|a| {
        let ch: Vec<char> = a.trim().chars().collect();
        if ch.len() <= 6 {
            return a;
        }
        format!(
            "{}…{}",
            ch[..3].iter().collect::<String>(),
            ch[ch.len() - 4..].iter().collect::<String>()
        )
    });
    Ok(EmailEnvSnapshot {
        configured,
        has_address,
        has_password,
        has_imap_host,
        has_smtp_host,
        address_hint,
    })
}

#[tauri::command]
pub fn cmd_email_save_config(
    app: AppHandle,
    address: String,
    password: String,
    imap_host: String,
    smtp_host: String,
) -> Result<(), String> {
    let address = address.trim().to_string();
    let password = password.trim().to_string();
    let imap_host = imap_host.trim().to_string();
    let smtp_host = smtp_host.trim().to_string();
    if address.is_empty() {
        return Err("EMAIL_ADDRESS must not be empty".into());
    }
    if password.is_empty() {
        return Err("EMAIL_PASSWORD must not be empty".into());
    }
    if imap_host.is_empty() {
        return Err("EMAIL_IMAP_HOST must not be empty".into());
    }
    if smtp_host.is_empty() {
        return Err("EMAIL_SMTP_HOST must not be empty".into());
    }
    crate::validation::validate_env_value(&address)?;
    crate::validation::validate_env_value(&password)?;
    crate::validation::validate_env_value(&imap_host)?;
    crate::validation::validate_env_value(&smtp_host)?;

    let hh = hh(&app)?;
    std::fs::create_dir_all(&hh).map_err(|e| e.to_string())?;
    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    let pairs = [
        ("EMAIL_ADDRESS", &address),
        ("EMAIL_PASSWORD", &password),
        ("EMAIL_IMAP_HOST", &imap_host),
        ("EMAIL_SMTP_HOST", &smtp_host),
    ];
    for (key, val) in &pairs {
        let mut found = false;
        for line in &mut lines {
            let trimmed = line.trim();
            if trimmed.starts_with(&format!("{}=", key))
                || trimmed.starts_with(&format!("{} ", key))
            {
                *line = format!("{}={}", key, val);
                found = true;
                break;
            }
        }
        if !found {
            lines.push(format!("{}={}", key, val));
        }
    }
    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}

#[tauri::command]
pub fn cmd_email_env_remove(app: AppHandle) -> Result<(), String> {
    let hh = hh(&app)?;
    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let lines: Vec<String> = content
        .lines()
        .map(|l| l.to_string())
        .filter(|line| {
            let trimmed = line.trim();
            !EMAIL_ENV_PREFIXES
                .iter()
                .any(|prefix| trimmed.starts_with(prefix))
        })
        .collect();
    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
