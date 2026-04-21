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
    pub provider: String, // "openrouter" | "openai" | "custom" | ...
    pub host: String,     // LLM API hostname for the network allowlist
    pub model: Option<String>,
    /// OpenAI-compatible chat/completions base URL (e.g. https://api.example.com/v1).
    #[serde(default)]
    pub api_base_url: Option<String>,
}

const VENDOR_LLM_DISABLED: &str = "hermesdesk.vendor_llm_disabled";

/// Build-time optional defaults so a distributor can ship a working demo key.
/// Set at **compile time** only (not committed to git):
/// `set HERMESDESK_VENDOR_API_KEY=...&& set HERMESDESK_VENDOR_BASE_URL=https://.../v1&& cargo tauri build`
fn vendor_api_key_compile() -> Option<&'static str> {
    option_env!("HERMESDESK_VENDOR_API_KEY").filter(|s| !s.is_empty())
}

fn vendor_base_url_compile() -> Option<&'static str> {
    option_env!("HERMESDESK_VENDOR_BASE_URL").filter(|s| !s.is_empty())
}

fn vendor_model_compile() -> Option<&'static str> {
    option_env!("HERMESDESK_VENDOR_MODEL").filter(|s| !s.is_empty())
}

pub fn vendor_llm_available() -> bool {
    vendor_api_key_compile().is_some() && vendor_base_url_compile().is_some()
}

fn host_from_api_base(url: &str) -> String {
    let u = url.trim();
    let rest = u
        .strip_prefix("https://")
        .or_else(|| u.strip_prefix("http://"))
        .unwrap_or(u);
    rest.split('/').next().unwrap_or(rest).to_string()
}

fn read_bool_setting(app: &AppHandle, key: &str) -> bool {
    let Some(f) = settings_file(app).ok() else {
        return false;
    };
    let Ok(raw) = std::fs::read_to_string(f) else {
        return false;
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return false;
    };
    matches!(
        v.get(key).and_then(|x| x.as_str()),
        Some("1" | "true" | "yes")
    ) || v.get(key).and_then(|x| x.as_bool()) == Some(true)
}

fn write_bool_setting(app: &AppHandle, key: &str, value: bool) -> Result<()> {
    let f = settings_file(app)?;
    let mut v: serde_json::Value = std::fs::read_to_string(&f)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(serde_json::json!({}));
    v[key] = serde_json::Value::Bool(value);
    std::fs::write(&f, serde_json::to_vec_pretty(&v)?)?;
    Ok(())
}

pub fn is_vendor_llm_disabled(app: &AppHandle) -> bool {
    read_bool_setting(app, VENDOR_LLM_DISABLED)
}

/// Keyring entry only (bridge may still fall back to compile-time vendor key).
pub fn read_user_secret(app: &AppHandle) -> Option<String> {
    let cfg = read_provider_cfg(app)?;
    entry_for(&cfg.provider).ok()?.get_password().ok()
}

/// Resolved LLM parameters for the Python child (provider allowlist + Hermes env).
pub struct LlmSpawnParams {
    pub provider: String,
    pub llm_host: String,
    pub api_base_url: Option<String>,
    pub hermes_model: Option<String>,
    pub inference_provider: Option<String>,
}

pub fn resolve_llm_spawn_params(app: &AppHandle) -> LlmSpawnParams {
    let user_secret = read_user_secret(app);
    let cfg = read_provider_cfg(app);
    // Vendor defaults apply only on a pristine install (no saved provider row).
    // Once the user has gone through onboarding, an empty keyring means "signed out",
    // not "fall back to the vendor demo key".
    let vendor_ok = user_secret.is_none()
        && cfg.is_none()
        && vendor_llm_available()
        && !is_vendor_llm_disabled(app);

    if vendor_ok {
        let base = vendor_base_url_compile().unwrap();
        return LlmSpawnParams {
            provider: "custom".into(),
            llm_host: host_from_api_base(base),
            api_base_url: Some(base.to_string()),
            hermes_model: vendor_model_compile().map(|s| s.to_string()),
            inference_provider: Some("custom".into()),
        };
    }

    if let Some(c) = cfg {
        let prov = c.provider.clone();
        let mut host = c.host.clone();
        let api = c.api_base_url.clone().filter(|s| !s.trim().is_empty());
        if host.is_empty() {
            if let Some(ref u) = api {
                host = host_from_api_base(u);
            }
        }
        if host.is_empty() {
            host = "openrouter.ai".into();
        }
        let inf = if prov == "custom" {
            Some("custom".into())
        } else {
            None
        };
        return LlmSpawnParams {
            provider: prov,
            llm_host: host,
            api_base_url: api,
            hermes_model: c.model.clone().filter(|s| !s.trim().is_empty()),
            inference_provider: inf,
        };
    }

    LlmSpawnParams {
        provider: "openrouter".into(),
        llm_host: "openrouter.ai".into(),
        api_base_url: None,
        hermes_model: None,
        inference_provider: None,
    }
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

fn entry_for(provider: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, provider).map_err(|e| e.to_string())
}

fn vendor_secret_fallback_enabled(app: &AppHandle) -> bool {
    read_provider_cfg(app).is_none()
        && vendor_llm_available()
        && !is_vendor_llm_disabled(app)
}

/// Secret handed to the Python child via the loopback bridge: user keyring
/// first, then optional compile-time vendor fallback on a pristine install only.
pub fn read_current_secret(app: &AppHandle) -> Option<String> {
    if let Some(s) = read_user_secret(app) {
        return Some(s);
    }
    if vendor_secret_fallback_enabled(app) {
        return vendor_api_key_compile().map(|s| s.to_string());
    }
    None
}

// --- IPC commands --------------------------------------------------------

#[tauri::command]
pub async fn cmd_save_secret(
    app: AppHandle,
    mut cfg: ProviderConfig,
    secret: String,
) -> Result<(), String> {
    if cfg.provider.trim().is_empty() {
        return Err("provider must be set".into());
    }
    if secret.trim().is_empty() {
        return Err("secret must not be empty".into());
    }
    if cfg.provider == "custom" {
        let url = cfg.api_base_url.as_deref().unwrap_or("").trim();
        if url.is_empty() {
            return Err("api_base_url is required for custom OpenAI-compatible APIs".into());
        }
        if cfg.host.trim().is_empty() {
            cfg.host = host_from_api_base(url);
        }
    } else if cfg.host.trim().is_empty() {
        return Err("host must be set".into());
    }
    entry_for(&cfg.provider)?
        .set_password(&secret)
        .map_err(|e| e.to_string())?;
    write_provider_cfg(&app, &cfg).map_err(|e| e.to_string())?;
    let _ = write_bool_setting(&app, VENDOR_LLM_DISABLED, false);
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
    let _ = write_bool_setting(&app, VENDOR_LLM_DISABLED, true);
    Ok(())
}
