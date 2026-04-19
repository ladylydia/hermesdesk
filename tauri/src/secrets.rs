//! API key storage backed by Windows Credential Manager (DPAPI).
//!
//! We use the cross-platform `keyring` crate directly. On Windows this
//! resolves to the native Credential Manager (DPAPI-encrypted at rest,
//! per-user). The plaintext key never touches a file we write; it lives
//! only in the OS vault and (transiently) in process memory.
//!
//! This module:
//!
//!   - Names the entry consistently (service = "HermesDesk", account = provider)
//!   - Persists which provider+host the user has chosen in settings.json
//!     (no secrets — just provider id and host)
//!   - Exposes commands the onboarding wizard calls
//!   - Hands the secret to the loopback bridge on demand

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

const SERVICE: &str = "HermesDesk";

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct ProviderConfig {
    pub provider: String,   // "openrouter" | "openai" | ...
    pub host: String,       // e.g. "openrouter.ai"
    pub model: Option<String>,
}

fn settings_file(app: &AppHandle) -> Result<PathBuf> {
    let dir = app.path().app_local_data_dir().context("local data dir")?;
    std::fs::create_dir_all(&dir)?;
    Ok(dir.join("settings.json"))
}

fn read_provider_cfg(app: &AppHandle) -> Option<ProviderConfig> {
    let f = settings_file(app).ok()?;
    let raw = std::fs::read_to_string(f).ok()?;
    let v: serde_json::Value = serde_json::from_str(&raw).ok()?;
    let p = v.get("provider")?;
    serde_json::from_value(p.clone()).ok()
}

fn write_provider_cfg(app: &AppHandle, cfg: &ProviderConfig) -> Result<()> {
    let f = settings_file(app)?;
    let mut v: serde_json::Value = std::fs::read_to_string(&f)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(serde_json::json!({}));
    v["provider"] = serde_json::to_value(cfg)?;
    std::fs::write(&f, serde_json::to_vec_pretty(&v)?)?;
    Ok(())
}

pub fn current_provider(app: &AppHandle) -> Option<String> {
    read_provider_cfg(app).map(|c| c.provider)
}

pub fn current_host(app: &AppHandle) -> Option<String> {
    read_provider_cfg(app).map(|c| c.host)
}

fn entry_for(provider: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, provider).map_err(|e| e.to_string())
}

/// Synchronous helper used by the loopback bridge. Returns None if no
/// provider has been configured, or if the keyring lookup fails (e.g.
/// the user cleared the entry from Credential Manager manually).
pub fn read_current_secret(app: &AppHandle) -> Option<String> {
    let cfg = read_provider_cfg(app)?;
    entry_for(&cfg.provider).ok()?.get_password().ok()
}

// --- IPC commands --------------------------------------------------------

#[tauri::command]
pub async fn cmd_save_secret(
    app: AppHandle,
    cfg: ProviderConfig,
    secret: String,
) -> Result<(), String> {
    if cfg.provider.trim().is_empty() {
        return Err("provider must be set".into());
    }
    if secret.trim().is_empty() {
        return Err("secret must not be empty".into());
    }
    entry_for(&cfg.provider)?
        .set_password(&secret)
        .map_err(|e| e.to_string())?;
    write_provider_cfg(&app, &cfg).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn cmd_has_secret(app: AppHandle) -> Result<bool, String> {
    Ok(read_current_secret(&app).is_some())
}

#[tauri::command]
pub async fn cmd_clear_secret(app: AppHandle) -> Result<(), String> {
    if let Some(cfg) = read_provider_cfg(&app) {
        let _ = entry_for(&cfg.provider).and_then(|e| e.delete_credential().map_err(|e| e.to_string()));
    }
    Ok(())
}
