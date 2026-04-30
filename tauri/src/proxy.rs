//! System proxy detection and user-managed proxy settings for the messaging gateway.
//!
//! Design principles:
//!   - Detect system proxy at startup but **do not auto-enable** it.
//!   - User must explicitly opt-in via a Toggle in Settings.
//!   - Custom proxy URL overrides system proxy when non-empty.
//!   - Loopback (127.0.0.1, localhost, ::1) is always exempt via NO_PROXY.

use serde::Serialize;
use std::path::Path;
use tauri::AppHandle;

/// Detected system proxy snapshot (read-only, for UI display).
#[derive(Serialize, Clone, Default)]
pub struct SystemProxySnapshot {
    pub url: Option<String>,
    pub enabled: bool,
}

/// User-managed proxy preference (persisted in `hermes-home/.env`).
#[derive(Serialize, Clone, Default)]
#[serde(rename_all = "camelCase")]
pub struct ProxySettings {
    pub use_system: bool,
    pub custom_url: Option<String>,
}

/// Combined view: what the UI shows and what the gateway should use.
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ProxyStatus {
    pub system: SystemProxySnapshot,
    pub settings: ProxySettings,
    pub effective_url: Option<String>,
}

/// Read Windows system proxy from the registry.
fn read_windows_system_proxy() -> SystemProxySnapshot {
    #[cfg(windows)]
    {
        use winreg::enums::HKEY_CURRENT_USER;
        use winreg::RegKey;

        let internet_settings = match RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey(r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        {
            Ok(k) => k,
            Err(_) => return SystemProxySnapshot::default(),
        };

        let proxy_enable: u32 = internet_settings.get_value("ProxyEnable").unwrap_or(0);
        if proxy_enable == 0 {
            return SystemProxySnapshot::default();
        }

        let proxy_server: String = match internet_settings.get_value("ProxyServer") {
            Ok(v) => v,
            Err(_) => return SystemProxySnapshot::default(),
        };

        // ProxyServer may be a list like "http=127.0.0.1:8668;https=127.0.0.1:8668".
        // We prefer the first non-empty token and prepend http:// if no scheme.
        let url = normalize_proxy_url(&proxy_server);
        SystemProxySnapshot {
            url: url.clone(),
            enabled: url.is_some(),
        }
    }
    #[cfg(not(windows))]
    {
        SystemProxySnapshot::default()
    }
}

/// Normalize a raw proxy server string into a full URL.
fn normalize_proxy_url(raw: &str) -> Option<String> {
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    // Take the first segment if it's a semicolon-separated list.
    let first = raw.split(';').next().unwrap_or(raw).trim();
    if first.is_empty() {
        return None;
    }
    // If it already has a scheme, use as-is.
    if first.contains("://") {
        return Some(first.to_string());
    }
    // If it looks like "socks5=host:port" or "http=host:port", parse it.
    if let Some((scheme, rest)) = first.split_once('=') {
        let scheme = scheme.trim().to_lowercase();
        let rest = rest.trim();
        if !rest.is_empty() && matches!(scheme.as_str(), "http" | "https" | "socks4" | "socks5" | "socks") {
            return Some(format!("{}://{}", scheme, rest));
        }
    }
    // Default to http:// if it's just host:port.
    Some(format!("http://{}", first))
}

/// Parse `hermes-home/.env` into key/value pairs (upper-case keys, non-empty values).
fn parse_dotenv_upper(hermes_home: &Path) -> std::collections::HashMap<String, String> {
    let mut keys = std::collections::HashMap::new();
    let dotenv = hermes_home.join(".env");
    let raw = match std::fs::read_to_string(&dotenv) {
        Ok(s) => s,
        Err(_) => return keys,
    };
    let raw = raw.trim_start_matches('\u{feff}');
    for line in raw.lines() {
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') {
            continue;
        }
        let Some((k, v)) = t.split_once('=') else {
            continue;
        };
        let key = k.trim().to_uppercase();
        let val = v.trim().trim_matches('"').trim_matches('\'');
        if !val.is_empty() {
            keys.insert(key, val.to_string());
        }
    }
    keys
}

/// Read user proxy preference from `.env`.
fn read_proxy_settings(hermes_home: &Path) -> ProxySettings {
    let keys = parse_dotenv_upper(hermes_home);
    let use_system = keys
        .get("HERMESDESK_USE_SYSTEM_PROXY")
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    let custom_url = keys
        .get("HERMESDESK_PROXY_URL")
        .cloned()
        .filter(|s| !s.is_empty());
    ProxySettings {
        use_system,
        custom_url,
    }
}

/// Compute the effective proxy URL based on system detection + user preference.
pub fn effective_proxy_url(system: &SystemProxySnapshot, settings: &ProxySettings) -> Option<String> {
    if let Some(ref custom) = settings.custom_url {
        return Some(custom.clone());
    }
    if settings.use_system {
        return system.url.clone();
    }
    None
}

/// Convenience: read system proxy + user settings from hermes-home and return the effective URL.
pub fn read_effective_proxy_for_hermes_home(hermes_home: &Path) -> Option<String> {
    let system = read_windows_system_proxy();
    let settings = read_proxy_settings(hermes_home);
    effective_proxy_url(&system, &settings)
}

// ------------------------------------------------------------------ Tauri commands

#[tauri::command]
pub fn cmd_proxy_status(app: AppHandle) -> Result<ProxyStatus, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hermes_home = crate::gateway_supervisor::hermes_home_path(&data_dir);

    let system = read_windows_system_proxy();
    let settings = read_proxy_settings(&hermes_home);
    let effective_url = effective_proxy_url(&system, &settings);

    Ok(ProxyStatus {
        system,
        settings,
        effective_url,
    })
}

#[tauri::command]
pub fn cmd_proxy_save(
    app: AppHandle,
    use_system: bool,
    custom_url: Option<String>,
) -> Result<(), String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hermes_home = crate::gateway_supervisor::hermes_home_path(&data_dir);
    std::fs::create_dir_all(&hermes_home).map_err(|e| e.to_string())?;

    let env_path = hermes_home.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    // Update HERMESDESK_USE_SYSTEM_PROXY
    let use_line = format!("HERMESDESK_USE_SYSTEM_PROXY={}", if use_system { "1" } else { "0" });
    let mut found_use = false;
    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.starts_with("HERMESDESK_USE_SYSTEM_PROXY=") || trimmed.starts_with("HERMESDESK_USE_SYSTEM_PROXY ") {
            *line = use_line.clone();
            found_use = true;
            break;
        }
    }
    if !found_use {
        lines.push(use_line);
    }

    // Update HERMESDESK_PROXY_URL
    let custom = custom_url.unwrap_or_default().trim().to_string();
    let mut found_custom = false;
    if custom.is_empty() {
        // Remove the line if clearing
        lines.retain(|l| {
            let trimmed = l.trim();
            !trimmed.starts_with("HERMESDESK_PROXY_URL=") && !trimmed.starts_with("HERMESDESK_PROXY_URL ")
        });
    } else {
        let proxy_line = format!("HERMESDESK_PROXY_URL={}", custom);
        for line in &mut lines {
            let trimmed = line.trim();
            if trimmed.starts_with("HERMESDESK_PROXY_URL=") || trimmed.starts_with("HERMESDESK_PROXY_URL ") {
                *line = proxy_line.clone();
                found_custom = true;
                break;
            }
        }
        if !found_custom {
            lines.push(proxy_line);
        }
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}
