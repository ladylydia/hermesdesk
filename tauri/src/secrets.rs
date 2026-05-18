//! API key storage backed by Windows Credential Manager (DPAPI).
//!
//! We use the cross-platform `keyring` crate directly. On Windows this
//! resolves to the native Credential Manager (DPAPI-encrypted at rest,
//! per-user). The plaintext key never touches a file we write; it lives
//! only in the OS vault and (transiently) in process memory.
//!
//! This module:
//!
//!   - Names the entry consistently (service = "Kabuqina", account = provider)
//!   - Persists which provider+host the user has chosen in settings.json
//!     (no secrets — just provider id and host)
//!   - Exposes commands the onboarding wizard calls
//!   - Hands the secret to the loopback bridge on demand

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

const SERVICE: &str = "Kabuqina";

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
    if let Ok(parsed) = url::Url::parse(url.trim()) {
        if let Some(host) = parsed.host_str() {
            return host.to_string();
        }
    }
    let u = url.trim();
    let rest = u
        .strip_prefix("https://")
        .or_else(|| u.strip_prefix("http://"))
        .unwrap_or(u);
    rest.split('/').next().unwrap_or(rest).to_string()
}

fn validate_provider_config_for_save(cfg: &mut ProviderConfig, secret: &str) -> Result<(), String> {
    cfg.provider = cfg.provider.trim().to_ascii_lowercase();
    cfg.host = cfg.host.trim().to_ascii_lowercase();
    cfg.api_base_url = cfg
        .api_base_url
        .as_ref()
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .filter(|s| !s.is_empty());

    if cfg.provider.is_empty() {
        return Err("provider must be set".into());
    }
    if secret.trim().is_empty() {
        return Err("secret must not be empty".into());
    }
    crate::validation::validate_env_value(secret)?;

    if cfg.provider == "custom" {
        let url = cfg
            .api_base_url
            .as_deref()
            .ok_or_else(|| "api_base_url is required for custom OpenAI-compatible APIs".to_string())?;
        crate::validation::validate_public_endpoint(url, None)?;
        let base_host = host_from_api_base(url).to_ascii_lowercase();
        if cfg.host.is_empty() {
            cfg.host = base_host;
        } else if cfg.host != base_host {
            return Err("host must match api_base_url host".into());
        }
        return Ok(());
    }

    if cfg.host.is_empty() {
        return Err("host must be set".into());
    }
    crate::validation::validate_public_endpoint(&format!("https://{}/", cfg.host), None)?;

    if let Some(url) = cfg.api_base_url.as_deref() {
        crate::validation::validate_public_endpoint(url, None)?;
        let base_host = host_from_api_base(url).to_ascii_lowercase();
        if base_host != cfg.host {
            return Err("api_base_url host must match provider host".into());
        }
    }

    Ok(())
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

/// Map a HermesDesk provider name to the env var that should hold its API key.
/// Mirrors ``_PROVIDER_ENV`` in ``python/src/secret_store.py``.
pub fn provider_api_key_env(provider: &str) -> String {
    match provider {
        "openrouter" => "OPENROUTER_API_KEY",
        "openai" => "OPENAI_API_KEY",
        "deepseek" => "DEEPSEEK_API_KEY",
        "custom" => "OPENAI_API_KEY",
        "anthropic" => "ANTHROPIC_API_KEY",
        "nous" => "NOUS_PORTAL_API_KEY",
        "groq" => "GROQ_API_KEY",
        "mistral" => "MISTRAL_API_KEY",
        "gemini" => "GOOGLE_API_KEY",
        "zai" => "GLM_API_KEY",
        "kimi-coding" => "KIMI_API_KEY",
        "kimi-coding-cn" => "KIMI_CN_API_KEY",
        "stepfun" => "STEPFUN_API_KEY",
        "minimax" => "MINIMAX_API_KEY",
        "minimax-cn" => "MINIMAX_CN_API_KEY",
        "alibaba" => "DASHSCOPE_API_KEY",
        "fireworks" => "FIREWORKS_API_KEY",
        "together" => "TOGETHER_API_KEY",
        "google" => "GOOGLE_API_KEY",
        "xai" => "XAI_API_KEY",
        "nvidia" => "NVIDIA_API_KEY",
        "huggingface" => "HF_TOKEN",
        "arcee" => "ARCEEAI_API_KEY",
        "gmi" => "GMI_API_KEY",
        "ollama-cloud" => "OLLAMA_API_KEY",
        _ => "OPENAI_API_KEY",
    }
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::{provider_api_key_env, validate_provider_config_for_save, ProviderConfig};

    #[test]
    fn provider_api_key_env_covers_native_hermes_providers() {
        assert_eq!(provider_api_key_env("openai"), "OPENAI_API_KEY");
        assert_eq!(provider_api_key_env("deepseek"), "DEEPSEEK_API_KEY");
        assert_eq!(provider_api_key_env("alibaba"), "DASHSCOPE_API_KEY");
        assert_eq!(provider_api_key_env("zai"), "GLM_API_KEY");
        assert_eq!(provider_api_key_env("kimi-coding"), "KIMI_API_KEY");
        assert_eq!(provider_api_key_env("kimi-coding-cn"), "KIMI_CN_API_KEY");
        assert_eq!(provider_api_key_env("minimax"), "MINIMAX_API_KEY");
        assert_eq!(provider_api_key_env("minimax-cn"), "MINIMAX_CN_API_KEY");
    }

    #[test]
    fn save_config_rejects_custom_loopback_base_url() {
        let mut cfg = ProviderConfig {
            provider: "custom".into(),
            host: "127.0.0.1".into(),
            model: None,
            api_base_url: Some("http://127.0.0.1:11434/v1".into()),
        };

        let result = validate_provider_config_for_save(&mut cfg, "sk-test");

        assert!(result.is_err());
    }

    #[test]
    fn save_config_rejects_secret_with_control_chars() {
        let mut cfg = ProviderConfig {
            provider: "openrouter".into(),
            host: "openrouter.ai".into(),
            model: None,
            api_base_url: None,
        };

        let result = validate_provider_config_for_save(&mut cfg, "sk-test\nEVIL=1");

        assert!(result.is_err());
    }

    #[test]
    fn save_config_derives_custom_host_from_valid_base_url() {
        let mut cfg = ProviderConfig {
            provider: "custom".into(),
            host: "".into(),
            model: None,
            api_base_url: Some("https://api.example.com/v1".into()),
        };

        validate_provider_config_for_save(&mut cfg, "sk-test").unwrap();

        assert_eq!(cfg.host, "api.example.com");
    }
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
        provider: "deepseek".into(),
        llm_host: "api.deepseek.com".into(),
        api_base_url: Some("https://api.deepseek.com/v1".into()),
        hermes_model: Some("deepseek-v4-flash".into()),
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

/// Remove the saved provider row so we never treat a keyless `settings.json` as "configured".
fn clear_provider_cfg(app: &AppHandle) -> Result<()> {
    let f = settings_file(app)?;
    let mut v: serde_json::Value = std::fs::read_to_string(&f)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(serde_json::json!({}));
    if let Some(obj) = v.as_object_mut() {
        obj.remove("provider");
    }
    std::fs::write(&f, serde_json::to_vec_pretty(&v)?)?;
    Ok(())
}

fn entry_for(provider: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, provider).map_err(|e| e.to_string())
}

fn vendor_secret_fallback_enabled(app: &AppHandle) -> bool {
    read_provider_cfg(app).is_none() && vendor_llm_available() && !is_vendor_llm_disabled(app)
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

/// Non-secret LLM row from `settings.json` plus whether a usable secret exists (keyring or vendor demo).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LlmConfigPreview {
    pub has_secret: bool,
    pub provider: Option<String>,
    pub host: Option<String>,
    pub model: Option<String>,
    pub api_base_url: Option<String>,
}

#[tauri::command]
pub async fn cmd_llm_config_preview(app: AppHandle) -> Result<LlmConfigPreview, String> {
    let has_secret = read_current_secret(&app).is_some();
    let mut cfg = read_provider_cfg(&app);

    // Auto-migrate legacy config: provider=custom + deepseek base_url → provider=deepseek
    if let Some(ref mut c) = cfg {
        if c.provider == "custom"
            && c.api_base_url
                .as_deref()
                .unwrap_or("")
                .contains("deepseek.com")
        {
            c.provider = "deepseek".to_string();
            write_provider_cfg(&app, c).ok();
        }
    }

    Ok(LlmConfigPreview {
        has_secret,
        provider: cfg.as_ref().map(|c| c.provider.clone()),
        host: cfg
            .as_ref()
            .map(|c| c.host.clone())
            .filter(|s| !s.trim().is_empty()),
        model: cfg.as_ref().and_then(|c| c.model.clone()),
        api_base_url: cfg.as_ref().and_then(|c| c.api_base_url.clone()),
    })
}

#[tauri::command]
pub async fn cmd_save_secret(
    app: AppHandle,
    mut cfg: ProviderConfig,
    secret: String,
) -> Result<(), String> {
    validate_provider_config_for_save(&mut cfg, &secret)?;
    entry_for(&cfg.provider)?
        .set_password(&secret)
        .map_err(|e| e.to_string())?;
    write_provider_cfg(&app, &cfg).map_err(|e| e.to_string())?;
    let _ = write_bool_setting(&app, VENDOR_LLM_DISABLED, false);
    crate::respawn_embedded_hermes_python(app).await?;
    Ok(())
}

#[tauri::command]
pub async fn cmd_has_secret(app: AppHandle) -> Result<bool, String> {
    Ok(read_current_secret(&app).is_some())
}

#[tauri::command]
pub async fn cmd_clear_secret(app: AppHandle) -> Result<(), String> {
    if let Some(cfg) = read_provider_cfg(&app) {
        let _ =
            entry_for(&cfg.provider).and_then(|e| e.delete_credential().map_err(|e| e.to_string()));
    }
    clear_provider_cfg(&app).map_err(|e| e.to_string())?;
    let _ = write_bool_setting(&app, VENDOR_LLM_DISABLED, true);
    Ok(())
}

#[tauri::command]
pub async fn cmd_validate_endpoint(
    app: AppHandle,
    url: String,
    api_key: String,
) -> Result<(), String> {
    log::info!("cmd_validate_endpoint called: url={}", url);

    let cfg = read_provider_cfg(&app);
    let saved_base = cfg.as_ref().and_then(|c| c.api_base_url.as_deref());
    crate::validation::validate_public_endpoint(&url, saved_base)?;

    let trimmed = api_key.trim();
    let is_anthropic = url.contains("api.anthropic.com");

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .no_proxy()
        .build()
        .map_err(|e| format!("client build error: {}", e))?;

    let mut req = client.get(&url);
    if is_anthropic {
        req = req
            .header("x-api-key", trimmed)
            .header("anthropic-version", "2023-06-01");
    } else {
        req = req.header("Authorization", format!("Bearer {trimmed}"));
    }

    let res = req
        .send()
        .await
        .map_err(|e| format!("Couldn't reach that API address: {} (url={})", e, url))?;
    let status = res.status();
    log::info!("cmd_validate_endpoint response: status={}", status);
    if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
        return Err("That pass didn't work. Double-check you copied the whole thing.".into());
    }
    if !status.is_success() && status != reqwest::StatusCode::BAD_REQUEST {
        return Err(format!(
            "That API address answered {}. Check the URL ends with /v1.",
            status
        ));
    }
    Ok(())
}
