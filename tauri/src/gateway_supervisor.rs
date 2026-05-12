//! Messaging gateway child processes — one per platform with per-profile HERMES_HOME.
//!
//! Each gateway platform (Telegram, Weixin, …) runs in its own OS child with
//! ``HERMES_HOME = <data_dir>/hermes-home/profiles/<platform>/`` for hard filesystem
//! isolation of memories, sessions, and credentials.
//!
//! Migration: on first launch after upgrading to this model, ``ensure_migration()``
//! creates ``profiles/<platform>/`` directories for every platform found in the
//! host ``hermes-home/.env``, plus an empty ``shared/USER_PREFS.md``.
//!
//! Identity: host ``hermes-home/SOUL.md`` is mirrored into each platform profile
//! at spawn time so bots share the same persona as the main desktop agent.
//!
//! Shared preferences: the host-only ``shared/USER_PREFS.md`` is copied into each
//! profile as ``_host_prefs.md`` at spawn time (read-only preamble for the bot).

use anyhow::{self, Context, Result};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

use crate::python_supervisor::SpawnConfig;

// ---------------------------------------------------------------------------
// Platform registry
// ---------------------------------------------------------------------------

/// Known platforms and the minimum credential keys that must be present
/// (non-empty) in `.env` for the platform to be considered "configured".
const PLATFORM_CREDENTIAL_KEYS: &[(&str, &[&str])] = &[
    ("telegram", &["TELEGRAM_BOT_TOKEN"]),
    ("weixin", &["WEIXIN_ACCOUNT_ID", "WEIXIN_TOKEN"]),
    ("feishu", &["FEISHU_APP_ID", "FEISHU_APP_SECRET"]),
    ("qqbot", &["QQ_APP_ID", "QQ_CLIENT_SECRET"]),
    (
        "dingtalk",
        &["DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET"],
    ),
    ("wecom", &["WECOM_BOT_ID", "WECOM_SECRET"]),
    ("discord", &["DISCORD_BOT_TOKEN"]),
    ("slack", &["SLACK_BOT_TOKEN"]),
    ("signal", &["SIGNAL_HTTP_URL"]),
    // Email gateway adapter (not a messaging platform per se, but runs in the gateway child).
    (
        "email",
        &[
            "EMAIL_ADDRESS",
            "EMAIL_PASSWORD",
            "EMAIL_IMAP_HOST",
            "EMAIL_SMTP_HOST",
        ],
    ),
];

/// Additional per-platform env keys to carry into the profile `.env` (not required
/// for "configured" detection, but needed for full operation).
const PLATFORM_EXTRA_KEYS: &[(&str, &[&str])] = &[
    (
        "telegram",
        &[
            "TELEGRAM_ALLOWED_USERS",
            "TELEGRAM_HOME_CHANNEL",
            "TELEGRAM_BOT_USERNAME",
        ],
    ),
    ("weixin", &[]),
    ("feishu", &[]),
    ("qqbot", &[]),
    ("dingtalk", &[]),
    ("wecom", &["WECOM_SETUP_METHOD"]),
    ("discord", &[]),
    ("slack", &[]),
    ("signal", &[]),
    ("email", &[]),
];

/// Name of the profile subdirectory.
const PROFILES_DIR: &str = "profiles";
/// Marker file written after first migration.
const MIGRATION_MARKER: &str = ".migrated";

// ---------------------------------------------------------------------------
// Host-level helpers (unchanged from single-child model)
// ---------------------------------------------------------------------------

/// Host ``HERMES_HOME = <data_dir>/hermes-home``.
pub fn hermes_home_path(data_dir: &Path) -> PathBuf {
    data_dir.join("hermes-home")
}

/// Per-profile ``HERMES_HOME = <data_dir>/hermes-home/profiles/<platform>/``.
pub fn profile_home_path(data_dir: &Path, platform: &str) -> PathBuf {
    hermes_home_path(data_dir).join(PROFILES_DIR).join(platform)
}

/// ``<data_dir>/hermes-home/shared/<filename>``.
fn shared_path(data_dir: &Path, filename: &str) -> PathBuf {
    hermes_home_path(data_dir).join("shared").join(filename)
}

/// True when the shipped ``hermes/gateway/run.py`` contains the first-connect
/// "stay alive for reconnect watcher" path.
pub fn bundled_gateway_has_startup_survival(bundle_dir: &Path) -> bool {
    let p = bundle_dir.join("hermes").join("gateway").join("run.py");
    let Ok(s) = std::fs::read_to_string(&p) else {
        return false;
    };
    s.contains("_platform_reconnect_watcher")
}

/// Best-effort read of ``gateway_state.json`` from a given ``HERMES_HOME``.
pub fn read_gateway_state_snapshot(home: &Path) -> (Option<String>, Option<String>) {
    let path = home.join("gateway_state.json");
    let Ok(raw) = std::fs::read_to_string(path) else {
        return (None, None);
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return (None, None);
    };
    let state = v
        .get("gateway_state")
        .and_then(|x| x.as_str())
        .map(str::to_string);
    let reason = v.get("exit_reason").and_then(|x| x.as_str()).map(|s| {
        const MAX: usize = 220;
        if s.chars().count() > MAX {
            let trunc: String = s.chars().take(MAX).collect();
            format!("{trunc}\u{2026}")
        } else {
            s.to_string()
        }
    });
    (state, reason)
}

/// Last lines of ``{home}/logs/gateway.log`` for startup failure hints.
pub fn tail_gateway_log(home: &Path, max_tail_bytes: u64) -> Option<String> {
    let path = home.join("logs").join("gateway.log");
    let meta = std::fs::metadata(&path).ok()?;
    let len = meta.len();
    let mut f = std::fs::File::open(&path).ok()?;
    use std::io::{Read, Seek, SeekFrom};
    if len > max_tail_bytes {
        f.seek(SeekFrom::End(-(max_tail_bytes as i64))).ok()?;
    }
    let mut buf = Vec::new();
    f.read_to_end(&mut buf).ok()?;
    let s = String::from_utf8_lossy(&buf).replace('\r', "");
    let tail: String = s
        .lines()
        .rev()
        .take(6)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .collect::<Vec<_>>()
        .join(" | ");
    if tail.is_empty() {
        None
    } else if tail.chars().count() > 380 {
        Some(format!(
            "{}\u{2026}",
            tail.chars().take(380).collect::<String>()
        ))
    } else {
        Some(tail)
    }
}

fn unquote_env_value(raw: &str) -> String {
    let s = raw.trim();
    if s.len() >= 2 {
        let b = s.as_bytes();
        if (b[0] == b'"' && b[s.len() - 1] == b'"') || (b[0] == b'\'' && b[s.len() - 1] == b'\'') {
            return s[1..s.len() - 1].to_string();
        }
    }
    s.to_string()
}

/// Parse ``{hermes_home}/.env`` into upper-case keys → non-empty values.
pub fn parse_dotenv_upper(home: &Path) -> HashMap<String, String> {
    let mut keys: HashMap<String, String> = HashMap::new();
    let dotenv = home.join(".env");
    let Ok(raw) = std::fs::read_to_string(&dotenv) else {
        return keys;
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
        let val = unquote_env_value(v);
        if !val.is_empty() {
            keys.insert(key, val);
        }
    }
    keys
}

/// Heuristic: host ``hermes-home/.env`` has at least one messaging platform the gateway can connect.
pub fn dotenv_suggests_messaging_gateway(home: &Path) -> bool {
    let keys = parse_dotenv_upper(home);
    let nonempty = |k: &str| keys.get(k).map(|s| !s.is_empty()).unwrap_or(false);

    if nonempty("WEIXIN_ACCOUNT_ID") && nonempty("WEIXIN_TOKEN") {
        return true;
    }
    if nonempty("TELEGRAM_BOT_TOKEN")
        || nonempty("DISCORD_BOT_TOKEN")
        || nonempty("SLACK_BOT_TOKEN")
        || nonempty("SIGNAL_HTTP_URL")
    {
        return true;
    }
    if nonempty("FEISHU_APP_ID") && nonempty("FEISHU_APP_SECRET") {
        return true;
    }
    if nonempty("WECOM_BOT_ID") && nonempty("WECOM_SECRET") {
        return true;
    }
    if nonempty("QQ_APP_ID") && nonempty("QQ_CLIENT_SECRET") {
        return true;
    }
    if nonempty("DINGTALK_CLIENT_ID") && nonempty("DINGTALK_CLIENT_SECRET") {
        return true;
    }
    false
}

// ---------------------------------------------------------------------------
// Env snapshot helpers (read from a given `.env`, defaulting to host)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Env snapshot structs (unchanged, but now accept a configurable home path)
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WeixinEnvSnapshot {
    pub configured: bool,
    pub has_account_id: bool,
    pub has_token: bool,
    pub account_id_hint: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct QqEnvSnapshot {
    pub configured: bool,
    pub has_app_id: bool,
    pub has_client_secret: bool,
    pub app_id_hint: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FeishuEnvSnapshot {
    pub configured: bool,
    pub has_app_id: bool,
    pub has_app_secret: bool,
    pub app_id_hint: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct TelegramEnvSnapshot {
    pub configured: bool,
    pub has_bot_token: bool,
    pub orphan_telegram_config: bool,
    pub token_hint: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct DingTalkEnvSnapshot {
    pub configured: bool,
    pub has_client_id: bool,
    pub has_client_secret: bool,
    pub client_id_hint: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WeComEnvSnapshot {
    pub configured: bool,
    pub has_bot_id: bool,
    pub has_secret: bool,
    pub bot_id_hint: Option<String>,
    pub setup_method: Option<String>,
}

fn telegram_token_hint(raw: &str) -> String {
    let s = raw.trim();
    if s.is_empty() {
        return String::new();
    }
    let ch: Vec<char> = s.chars().collect();
    let n = ch.len();
    if n <= 10 {
        return "****".to_string();
    }
    let head: String = ch.iter().take(4).collect();
    let tail: String = ch[n.saturating_sub(4)..].iter().collect();
    format!("{head}\u{2026}{tail}")
}

fn qq_app_id_display_hint(id: &str) -> String {
    let s = id.trim();
    if s.is_empty() {
        return String::new();
    }
    let ch: Vec<char> = s.chars().collect();
    if ch.len() <= 12 {
        return s.to_string();
    }
    let tail: String = ch[ch.len().saturating_sub(8)..].iter().collect();
    format!("\u{2026}{tail}")
}

fn weixin_account_display_hint(id: &str) -> String {
    let s = id.trim();
    if s.is_empty() {
        return String::new();
    }
    let ch: Vec<char> = s.chars().collect();
    if ch.len() <= 14 {
        return s.to_string();
    }
    let tail: String = ch[ch.len().saturating_sub(12)..].iter().collect();
    format!("\u{2026}{tail}")
}

pub fn read_weixin_env_snapshot(home: &Path) -> WeixinEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let account = keys.get("WEIXIN_ACCOUNT_ID").cloned();
    let has_token = keys
        .get("WEIXIN_TOKEN")
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let has_account_id = account.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_account_id && has_token;
    let account_id_hint = account
        .map(|id| weixin_account_display_hint(&id))
        .filter(|s| !s.is_empty());
    WeixinEnvSnapshot {
        configured,
        has_account_id,
        has_token,
        account_id_hint,
    }
}

pub fn read_qq_env_snapshot(home: &Path) -> QqEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let app_id = keys.get("QQ_APP_ID").cloned();
    let has_client_secret = keys
        .get("QQ_CLIENT_SECRET")
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let has_app_id = app_id.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_app_id && has_client_secret;
    let app_id_hint = app_id
        .map(|id| qq_app_id_display_hint(&id))
        .filter(|s| !s.is_empty());
    QqEnvSnapshot {
        configured,
        has_app_id,
        has_client_secret,
        app_id_hint,
    }
}

pub fn read_feishu_env_snapshot(home: &Path) -> FeishuEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let app_id = keys.get("FEISHU_APP_ID").cloned();
    let has_app_secret = keys
        .get("FEISHU_APP_SECRET")
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let has_app_id = app_id.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_app_id && has_app_secret;
    let app_id_hint = app_id
        .map(|id| qq_app_id_display_hint(&id))
        .filter(|s| !s.is_empty());
    FeishuEnvSnapshot {
        configured,
        has_app_id,
        has_app_secret,
        app_id_hint,
    }
}

pub fn read_telegram_env_snapshot(home: &Path) -> TelegramEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let nonempty = |k: &str| keys.get(k).map(|s| !s.is_empty()).unwrap_or(false);
    let token = keys.get("TELEGRAM_BOT_TOKEN").cloned();
    let has_bot_token = token.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_bot_token;
    let orphan_telegram_config = !configured
        && (nonempty("TELEGRAM_ALLOWED_USERS")
            || nonempty("TELEGRAM_HOME_CHANNEL")
            || nonempty("TELEGRAM_BOT_USERNAME"));
    let token_hint = token
        .filter(|s| !s.is_empty())
        .map(|t| telegram_token_hint(&t));
    TelegramEnvSnapshot {
        configured,
        has_bot_token,
        orphan_telegram_config,
        token_hint,
    }
}

pub fn read_dingtalk_env_snapshot(home: &Path) -> DingTalkEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let client_id = keys.get("DINGTALK_CLIENT_ID").cloned();
    let has_client_secret = keys
        .get("DINGTALK_CLIENT_SECRET")
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let has_client_id = client_id.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_client_id && has_client_secret;
    let client_id_hint = client_id
        .map(|id| qq_app_id_display_hint(&id))
        .filter(|s| !s.is_empty());
    DingTalkEnvSnapshot {
        configured,
        has_client_id,
        has_client_secret,
        client_id_hint,
    }
}

pub fn read_wecom_env_snapshot(home: &Path) -> WeComEnvSnapshot {
    let keys = parse_dotenv_upper(home);
    let bot_id = keys.get("WECOM_BOT_ID").cloned();
    let has_secret = keys
        .get("WECOM_SECRET")
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    let has_bot_id = bot_id.as_ref().map(|s| !s.is_empty()).unwrap_or(false);
    let configured = has_bot_id && has_secret;
    let bot_id_hint = bot_id
        .map(|id| qq_app_id_display_hint(&id))
        .filter(|s| !s.is_empty());
    let setup_method = keys.get("WECOM_SETUP_METHOD").cloned();
    WeComEnvSnapshot {
        configured,
        has_bot_id,
        has_secret,
        bot_id_hint,
        setup_method,
    }
}

// ---------------------------------------------------------------------------
// Platform discovery
// ---------------------------------------------------------------------------

/// Return the list of platform names whose credential keys are all present
/// and non-empty in the given dotenv key map.
pub fn discover_configured_platforms(keys: &HashMap<String, String>) -> Vec<String> {
    let nonempty = |k: &str| keys.get(k).map(|s| !s.is_empty()).unwrap_or(false);
    let mut platforms: Vec<String> = Vec::new();
    for &(name, creds) in PLATFORM_CREDENTIAL_KEYS {
        if creds.iter().all(|k| nonempty(k)) {
            platforms.push(name.to_string());
        }
    }
    platforms
}

// ---------------------------------------------------------------------------
// Migration
/// Read the host ``hermes-home/config.yaml`` and return the ``llm:`` section
/// lines (everything from ``llm:`` to the next top-level key).  Returns
/// ``None`` if the file is missing or has no ``llm:`` key.
fn extract_llm_config_section(host_home: &Path) -> Option<String> {
    let path = host_home.join("config.yaml");
    let raw = std::fs::read_to_string(path).ok()?;
    let mut llm_lines = String::new();
    let mut in_llm = false;
    for line in raw.lines() {
        let trimmed = line.trim();
        if in_llm {
            // Top-level keys are not indented.  End of llm section.
            if !line.starts_with(' ') && !line.starts_with('\t') && !trimmed.is_empty() {
                break;
            }
            llm_lines.push_str(line);
            llm_lines.push('\n');
        } else if trimmed == "llm:" {
            in_llm = true;
            llm_lines.push_str(line);
            llm_lines.push('\n');
        }
    }
    if llm_lines.is_empty() {
        return None;
    }
    Some(llm_lines)
}

// ---------------------------------------------------------------------------

/// One-time migration: create ``profiles/<platform>/`` dirs for every
/// currently-configured platform, plus ``shared/USER_PREFS.md``.
///
/// Safe to call repeatedly — checks for the ``.migrated`` marker file.
pub fn ensure_migration(data_dir: &Path) -> Result<()> {
    let host_home = hermes_home_path(data_dir);
    let profiles_dir = host_home.join(PROFILES_DIR);
    let marker = profiles_dir.join(MIGRATION_MARKER);

    if marker.exists() {
        return Ok(());
    }

    log::info!("[gateway_migration] creating profile directories");

    std::fs::create_dir_all(&profiles_dir).context("create profiles dir")?;

    // Create shared/ dir and empty USER_PREFS.md.
    let shared_dir = host_home.join("shared");
    std::fs::create_dir_all(&shared_dir).context("create shared dir")?;
    let prefs_path = shared_dir.join("USER_PREFS.md");
    if !prefs_path.exists() {
        std::fs::write(&prefs_path, "").context("write empty USER_PREFS.md")?;
    }

    // Create per-platform profile dirs.
    let keys = parse_dotenv_upper(&host_home);
    let platforms = discover_configured_platforms(&keys);

    // Read the host LLM config section so every profile inherits the
    // user's LLM provider/model/endpoint settings.
    let host_llm_lines = extract_llm_config_section(&host_home);

    for platform in &platforms {
        let profile_dir = profile_home_path(data_dir, platform);
        std::fs::create_dir_all(profile_dir.join("memories"))
            .context("create profile memories dir")?;
        std::fs::create_dir_all(profile_dir.join("sessions"))
            .context("create profile sessions dir")?;
        if !profile_dir.join("config.yaml").exists() {
            // Write a config that enables only this platform and includes
            // the host's LLM config (provider, model, base_url, etc.).
            let mut config = format!(
                r#"platforms:
  {}:
    enable: true

"#,
                platform
            );
            if let Some(ref llm) = host_llm_lines {
                config.push_str(llm);
                config.push('\n');
            }
            std::fs::write(profile_dir.join("config.yaml"), &config)
                .context("write profile config.yaml")?;
        }
    }

    std::fs::write(&marker, "1").context("write migration marker")?;
    log::info!(
        "[gateway_migration] created {} profile(s): {:?}",
        platforms.len(),
        platforms
    );
    Ok(())
}

// ---------------------------------------------------------------------------
// Per-platform child management
// ---------------------------------------------------------------------------

struct PlatformChild {
    platform: String,
    child: Child,
    captured_stderr: Arc<Mutex<String>>,
}

pub struct GatewaySupervisor {
    children: Vec<PlatformChild>,
}

impl GatewaySupervisor {
    /// Spawn one gateway child per configured platform.
    ///
    /// Each child gets its own ``HERMES_HOME`` pointing to
    /// ``<data_dir>/hermes-home/profiles/<platform>/``.
    pub async fn spawn_all(cfg: &SpawnConfig) -> Result<Self> {
        // 0. On Windows, kill any orphan gateway Python processes that
        //    survived a crash of the Tauri process (Ctrl+C, dev restart).
        //    These orphans still hold the Windows named mutex, preventing
        //    new gateway children from acquiring the runtime lock.
        kill_orphan_gateway_processes();

        // 1. Ensure migration has run.
        ensure_migration(&cfg.data_dir)?;

        let host_home = hermes_home_path(&cfg.data_dir);
        let host_keys = parse_dotenv_upper(&host_home);
        let platforms = discover_configured_platforms(&host_keys);

        if platforms.is_empty() {
            log::info!("[gateway_spawn] no configured platforms; returning empty supervisor");
            return Ok(Self {
                children: Vec::new(),
            });
        }

        let mut children: Vec<PlatformChild> = Vec::new();
        for platform in &platforms {
            match Self::spawn_one(cfg, platform, &host_keys).await {
                Ok(pc) => {
                    log::info!(
                        "[gateway_spawn] {} child spawned (pid={:?})",
                        platform,
                        pc.child.id()
                    );
                    children.push(pc);
                }
                Err(e) => {
                    log::warn!("[gateway_spawn] failed to spawn {}: {:#}", platform, e);
                }
            }
        }

        if children.is_empty() {
            anyhow::bail!("all gateway platforms failed to spawn");
        }

        Ok(Self { children })
    }

    /// Build and spawn a single platform child.
    async fn spawn_one(
        cfg: &SpawnConfig,
        platform: &str,
        host_keys: &HashMap<String, String>,
    ) -> Result<PlatformChild> {
        let py_exe = cfg.bundle_dir.join("python").join("python.exe");
        anyhow::ensure!(
            py_exe.exists(),
            "python.exe missing at {}",
            py_exe.display()
        );

        let profile_dir = profile_home_path(&cfg.data_dir, platform);
        std::fs::create_dir_all(&profile_dir).context("create profile dir")?;

        // Copy the host config.yaml into the profile so the upstream
        // gateway finds its llm/credential_pool/credentials sections.
        // Without this, the gateway can't authenticate with the LLM
        // provider and falls back to upstream defaults (Qwen → 401).
        copy_host_config(&cfg.data_dir, &profile_dir);

        // Copy the host SOUL.md into the platform profile so gateway bots
        // share the same identity/persona as the main desktop agent.
        copy_host_soul(&cfg.data_dir, &profile_dir)?;

        // Write profile-specific `.env` — only this platform's credentials.
        write_profile_dotenv(&cfg.data_dir, platform, host_keys)?;

        // Also append the LLM API key to the profile's .env as a safety net.
        // The upstream gateway reads .env for credentials; if the env var
        // injection above fails, this ensures the key is still available.
        if let (Some(key), name) = (&cfg.api_key, &cfg.api_key_env_name) {
            if !name.is_empty() && !key.is_empty() {
                let dotenv_path = profile_dir.join(".env");
                use std::io::Write;
                if let Ok(mut f) = std::fs::OpenOptions::new().append(true).open(&dotenv_path) {
                    let _ = writeln!(f, "{}={}", name, key);
                }
            }
        }

        // Copy shared/USER_PREFS.md → _host_prefs.md (if non-empty).
        copy_host_prefs(&cfg.data_dir, &profile_dir)?;

        // Clean up stale lock files from previous instances.
        cleanup_stale_locks(&profile_dir);

        let mut cmd = Command::new(&py_exe);
        cmd.args(["-m", "gateway.run"])
            .current_dir(&cfg.bundle_dir)
            .env("HERMES_HOME", &profile_dir)
            .env("HERMESDESK_GATEWAY_PLATFORM", platform)
            .env("HERMESDESK_BUNDLE_DIR", &cfg.bundle_dir)
            .env("HERMESDESK_DATA_DIR", &cfg.data_dir)
            .env("HERMESDESK_WORKSPACE", &cfg.workspace)
            .env("HERMESDESK_PROVIDER", &cfg.provider)
            .env("HERMESDESK_LLM_HOST", &cfg.llm_host)
            .env(
                "HERMESDESK_API_BASE_URL",
                cfg.api_base_url.as_deref().unwrap_or(""),
            )
            .env(
                "HERMESDESK_MODEL",
                cfg.hermes_model.as_deref().unwrap_or(""),
            )
            .env(
                "HERMESDESK_INFERENCE_PROVIDER",
                cfg.inference_provider.as_deref().unwrap_or(""),
            )
            .env("HERMESDESK_SECRET_URL", &cfg.secret_url)
            .env("HERMESDESK_APPROVAL_URL", &cfg.approval_url)
            .env("HERMESDESK_BRIDGE_SECRET", &cfg.desk_auth_token)
            .env("HERMESDESK_SHELL_CHAT_URL", &cfg.shell_chat_back_url)
            .env(
                "HERMESDESK_POWER_USER",
                if cfg.power_user { "1" } else { "0" },
            )
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            // Strip any stray API keys inherited from the user shell or
            // parent process, then inject the correct one from our vault.
            .env_remove("OPENAI_API_KEY")
            .env_remove("ANTHROPIC_API_KEY")
            .env_remove("OPENROUTER_API_KEY")
            .env_remove("NOUS_PORTAL_API_KEY")
            .env_remove("GROQ_API_KEY")
            .env_remove("GOOGLE_API_KEY")
            .env_remove("XAI_API_KEY")
            .env_remove("OPENAI_BASE_URL")
            .env_remove("HERMES_INFERENCE_PROVIDER")
            .env(
                "PYTHONPATH",
                std::env::join_paths([
                    cfg.bundle_dir.join("site-packages"),
                    cfg.bundle_dir.join("hermes"),
                ])
                .map_err(|e| anyhow::anyhow!("PYTHONPATH: {e}"))?,
            )
            .env("NO_PROXY", "127.0.0.1,localhost,::1")
            .env("BROWSER_CDP_URL", crate::edge_browser::cdp_url());

        // Inject the LLM API key from our vault so the upstream gateway
        // can authenticate with the LLM provider.  The web child fetches
        // this via HERMESDESK_SECRET_URL; gateway children have no overlay
        // to do that, so we inject it directly.
        log::info!(
            "[gateway_spawn] {} api_key env_name={:?} key={}",
            platform,
            cfg.api_key_env_name,
            cfg.api_key.as_ref().map(|_| "present").unwrap_or("missing"),
        );
        if !cfg.api_key_env_name.is_empty() {
            if let Some(key) = &cfg.api_key {
                cmd.env(&cfg.api_key_env_name, key);
                log::info!(
                    "[gateway_spawn] {} injected {} (len={})",
                    platform,
                    cfg.api_key_env_name,
                    key.len(),
                );
            }
        }

        // Also inject OPENAI_BASE_URL for custom providers (upstream
        // gateway reads this, not HERMESDESK_API_BASE_URL).
        if let Some(url) = &cfg.api_base_url {
            if !url.trim().is_empty() {
                cmd.env("OPENAI_BASE_URL", url);
            }
        }

        // Inject email creds from the PROFILE's .env (not the host's).
        let profile_keys = parse_dotenv_upper(&profile_dir);
        for key in [
            "EMAIL_ADDRESS",
            "EMAIL_PASSWORD",
            "EMAIL_IMAP_HOST",
            "EMAIL_SMTP_HOST",
        ] {
            if let Some(val) = profile_keys.get(key) {
                cmd.env(key, val);
            }
        }

        // Inject proxy config from the HOST (proxy is a system-level setting).
        if let Some(proxy_url) =
            crate::proxy::read_effective_proxy_for_hermes_home(&hermes_home_path(&cfg.data_dir))
        {
            cmd.env("HERMESDESK_PROXY_URL", &proxy_url);
            cmd.env("HTTP_PROXY", &proxy_url);
            cmd.env("HTTPS_PROXY", &proxy_url);
        }

        cmd.stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd.spawn().context("spawn gateway python child")?;
        let captured = Arc::new(Mutex::new(String::new()));

        if let Some(out) = child.stdout.take() {
            let tag = format!("gw.{}.out", platform);
            tokio::spawn(forward(tag, out, None));
        }
        if let Some(err) = child.stderr.take() {
            let tag = format!("gw.{}.err", platform);
            tokio::spawn(forward(tag, err, Some(captured.clone())));
        }

        Ok(PlatformChild {
            platform: platform.to_string(),
            child,
            captured_stderr: captured,
        })
    }

    /// Kill every child and wait up to 3 s for each to exit.
    pub async fn shutdown(mut self) -> Result<()> {
        let children = std::mem::take(&mut self.children);
        for mut pc in children {
            let _ = pc.child.start_kill();
            let start = tokio::time::Instant::now();
            loop {
                match pc.child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => {
                        if start.elapsed() > std::time::Duration::from_secs(3) {
                            log::warn!(
                                "gateway child {} did not exit within 3s of kill",
                                pc.platform
                            );
                            break;
                        }
                        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                    }
                    Err(e) => {
                        log::warn!("gateway child {} wait error: {}", pc.platform, e);
                        break;
                    }
                }
            }
        }
        Ok(())
    }

    /// True when at least one child is still running.
    pub fn any_running(&mut self) -> bool {
        self.children
            .iter_mut()
            .any(|pc| match pc.child.try_wait() {
                Ok(None) => true,
                _ => false,
            })
    }

    /// Remove exited children, return (platform, status) for each.
    pub fn reap_exited(&mut self) -> Vec<(String, std::process::ExitStatus)> {
        let mut exited = Vec::new();
        let mut i = 0;
        while i < self.children.len() {
            match self.children[i].child.try_wait() {
                Ok(Some(st)) => {
                    let pc = self.children.swap_remove(i);
                    exited.push((pc.platform, st));
                }
                _ => {
                    i += 1;
                }
            }
        }
        exited
    }

    /// Per-platform running state map.
    pub fn running_map(&self) -> HashMap<String, bool> {
        let mut map = HashMap::new();
        // We can't call try_wait on &self, so just report the presence of each child.
        // The caller should call try_reap first to clean up exited children.
        for pc in &self.children {
            map.insert(pc.platform.clone(), true);
        }
        map
    }

    /// Aggregate stderr from all children (best-effort, truncated).
    pub fn aggregate_stderr(&self) -> String {
        let mut buf = String::new();
        for pc in &self.children {
            if let Ok(g) = pc.captured_stderr.try_lock() {
                let s = g.trim();
                if !s.is_empty() {
                    if !buf.is_empty() {
                        buf.push_str("\n---\n");
                    }
                    buf.push_str(&format!("[{}]\n{}", pc.platform, s));
                }
            }
        }
        buf
    }

    /// Number of platform children.
    pub fn platform_count(&self) -> usize {
        self.children.len()
    }
}

impl Drop for GatewaySupervisor {
    fn drop(&mut self) {
        for pc in &mut self.children {
            let _ = pc.child.start_kill();
        }
    }
}

// ---------------------------------------------------------------------------
// Profile helpers
// ---------------------------------------------------------------------------

/// Env key prefixes copied from the host ``.env`` into a platform profile.
/// Any host key starting with one of these prefixes is included (so Settings
/// can persist behavior keys like ``FEISHU_CONNECTION_MODE`` alongside creds).
fn platform_env_prefixes(platform: &str) -> &'static [&'static str] {
    match platform {
        "telegram" => &["TELEGRAM_"],
        "weixin" => &["WEIXIN_"],
        "feishu" => &["FEISHU_"],
        "qqbot" => &["QQ_", "QQBOT_"],
        "dingtalk" => &["DINGTALK_"],
        "wecom" => &["WECOM_"],
        "discord" => &["DISCORD_"],
        "slack" => &["SLACK_"],
        "signal" => &["SIGNAL_"],
        "email" => &["EMAIL_", "SMS_", "TWILIO_"],
        _ => &[],
    }
}

/// Write a platform-specific `.env` inside the profile directory.
///
/// Contains:
///   - Every host key matching this platform's credential keys **or** env prefixes
///   - LLM API keys and provider config (from the host `.env`)
///   - ``GATEWAY_ALLOW_ALL_USERS`` from host when set, otherwise ``true`` (legacy default)
fn write_profile_dotenv(
    data_dir: &Path,
    platform: &str,
    host_keys: &HashMap<String, String>,
) -> Result<()> {
    let profile_dir = profile_home_path(data_dir, platform);
    let dotenv_path = profile_dir.join(".env");

    let mut written = HashSet::<String>::new();
    let mut content = String::new();

    let mut platform_keys: Vec<&str> = Vec::new();
    for &(name, creds) in PLATFORM_CREDENTIAL_KEYS {
        if name == platform {
            platform_keys.extend_from_slice(creds);
            break;
        }
    }
    for &(name, extras) in PLATFORM_EXTRA_KEYS {
        if name == platform {
            platform_keys.extend_from_slice(extras);
            break;
        }
    }

    let push_kv = |k: &str, val: &str, written: &mut HashSet<String>, buf: &mut String| {
        let ku = k.to_string();
        if written.insert(ku.clone()) {
            buf.push_str(&format!("{}={}\n", ku, val));
        }
    };

    // 1. Explicit credential + legacy extra keys.
    for key in &platform_keys {
        if let Some(val) = host_keys.get(*key) {
            push_kv(key, val, &mut written, &mut content);
        }
    }

    // 2. All host keys with this platform's prefixes (behavior + webhook + allowlists, etc.).
    let prefixes = platform_env_prefixes(platform);
    for (key, val) in host_keys {
        if prefixes.iter().any(|p| key.starts_with(*p)) {
            push_kv(key, val, &mut written, &mut content);
        }
    }

    // 3. LLM / Hermes host keys — skip keys already copied as platform vars.
    for (key, val) in host_keys {
        if written.contains(key) {
            continue;
        }
        if key.ends_with("_API_KEY") || key == "OPENAI_BASE_URL" || key.starts_with("HERMES_") {
            push_kv(key, val, &mut written, &mut content);
        }
    }

    // 4. Pairing gate: inherit from host if the user set it in Settings / .env.
    if !written.contains("GATEWAY_ALLOW_ALL_USERS") {
        if let Some(v) = host_keys.get("GATEWAY_ALLOW_ALL_USERS") {
            content.push_str(&format!("GATEWAY_ALLOW_ALL_USERS={}\n", v));
        } else {
            content.push_str("GATEWAY_ALLOW_ALL_USERS=true\n");
        }
    }

    std::fs::write(&dotenv_path, &content).context("write profile .env")?;
    Ok(())
}

/// Copy the host ``hermes-home/config.yaml`` into the profile directory.
/// The profile needs the host's LLM config (provider, model, credential_pool)
/// so the upstream gateway can authenticate.  If the host config is missing
/// the copy is silently skipped (the gateway falls back to defaults).
fn copy_host_config(data_dir: &Path, profile_dir: &Path) {
    let src = hermes_home_path(data_dir).join("config.yaml");
    let dst = profile_dir.join("config.yaml");
    if src.exists() {
        if let Err(e) = std::fs::copy(&src, &dst) {
            log::warn!("[gateway_spawn] copy host config.yaml: {e}");
        }
    }
}

/// Mirror host ``hermes-home/SOUL.md`` into the profile directory.
/// If the host identity file is missing or empty, remove any stale profile copy
/// so the gateway does not keep an older persona after the main agent changes.
fn copy_host_soul(data_dir: &Path, profile_dir: &Path) -> Result<()> {
    let src = hermes_home_path(data_dir).join("SOUL.md");
    let dst = profile_dir.join("SOUL.md");

    match std::fs::read_to_string(&src) {
        Ok(content) if !content.trim().is_empty() => {
            std::fs::write(&dst, content).context("write profile SOUL.md")?;
        }
        _ => {
            let _ = std::fs::remove_file(&dst);
        }
    }
    Ok(())
}

/// Copy ``shared/USER_PREFS.md`` into the profile directory as ``_host_prefs.md``.
/// If the shared file is empty or missing, ensure ``_host_prefs.md`` does not exist.
fn copy_host_prefs(data_dir: &Path, profile_dir: &Path) -> Result<()> {
    let src = shared_path(data_dir, "USER_PREFS.md");
    let dst = profile_dir.join("_host_prefs.md");

    match std::fs::read_to_string(&src) {
        Ok(content) if !content.trim().is_empty() => {
            std::fs::write(&dst, &content).context("write _host_prefs.md")?;
        }
        _ => {
            // Ensure stale copy is removed.
            let _ = std::fs::remove_file(&dst);
        }
    }
    Ok(())
}

/// Remove stale lock/pid/state files from a profile directory.
fn cleanup_stale_locks(profile_dir: &Path) {
    for name in &["gateway.lock", "gateway.pid", "gateway_state.json"] {
        let _ = std::fs::remove_file(profile_dir.join(name));
    }
    // Clean up token-scoped locks (XDG state path under profile).
    let lock_dir = profile_dir.join("gateway-locks");
    if lock_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(&lock_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.extension().map_or(false, |e| e == "lock") {
                    let _ = std::fs::remove_file(&p);
                }
            }
        }
    }

    // Clean up system-level token-scoped locks from previous gateway instances.
    // The upstream platform adapters (Telegram, Weixin, etc.) call
    // acquire_scoped_lock() which writes to ~/.local/state/hermes/gateway-locks/.
    // These are NOT inside HERMES_HOME — they live in the XDG state path.
    let sys_lock_base = std::env::var("XDG_STATE_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("USERPROFILE")
                .map(std::path::PathBuf::from)
                .unwrap_or_default();
            home.join(".local").join("state")
        });
    let sys_lock_dir = sys_lock_base.join("hermes").join("gateway-locks");
    if sys_lock_dir.exists() {
        if let Ok(entries) = std::fs::read_dir(&sys_lock_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.extension().map_or(false, |e| e == "lock") {
                    let _ = std::fs::remove_file(&p);
                }
            }
        }
    }
}

/// Remove orphan gateway Python processes that survived a Tauri crash.
/// On Windows, the gateway uses a named kernel mutex (`CreateMutexW`) for
/// its runtime lock.  When `cargo tauri dev` is force-restarted (Ctrl+C),
/// the Tauri supervisor dies but orphan Python children survive, still
/// holding the mutex.  New gateway children then fail with:
///   "Gateway runtime lock is already held by another instance."
///
/// This function enumerates running `python.exe` processes and terminates
/// any that are running `gateway.run`, allowing fresh spawns to acquire
/// the mutex.
#[cfg(windows)]
fn kill_orphan_gateway_processes() {
    use std::process::Command;

    // WMIC query: get all python.exe processes with their PIDs and command lines.
    // CSV format: Node,ProcessId,CommandLine (CommandLine may contain commas and be quoted).
    let output = match Command::new("wmic")
        .args([
            "process",
            "where",
            "name='python.exe'",
            "get",
            "ProcessId,CommandLine",
            "/format:csv",
        ])
        .output()
    {
        Ok(o) => o,
        Err(_) => {
            log::debug!("[gateway_cleanup] wmic not available (non-Windows?)");
            return;
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);

    for line in stdout.lines().skip(1) {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with("Node") {
            continue;
        }
        // CSV: HOSTNAME,1234,"C:\path\python.exe -m gateway.run ..."
        // Use splitn(3) so the CommandLine (3rd field) retains any internal commas.
        let mut cols = trimmed.splitn(3, ',');
        let _node = cols.next();
        let pid = cols.next().unwrap_or("").trim();
        let cmdline = cols.next().unwrap_or("").trim();

        if pid.is_empty() || !pid.bytes().all(|b| b.is_ascii_digit()) {
            continue;
        }

        // CommandLine in WMIC CSV may be wrapped in double quotes.
        let cl = cmdline.trim_matches('"');

        if cl.contains("gateway.run") {
            log::info!(
                "[gateway_cleanup] terminating orphan gateway process pid={}",
                pid,
            );
            let _ = Command::new("taskkill").args(["/F", "/PID", pid]).output();
        }
    }
}

#[cfg(not(windows))]
fn kill_orphan_gateway_processes() {
    // On Unix, orphaned children are automatically reaped by init when the
    // parent exits, so no explicit cleanup is needed.
}

// ---------------------------------------------------------------------------
// Stderr forwarder
// ---------------------------------------------------------------------------

async fn forward<R: tokio::io::AsyncRead + Unpin + Send + 'static>(
    tag: String,
    r: R,
    capture: Option<Arc<Mutex<String>>>,
) {
    let mut lines = BufReader::new(r).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        log::info!("{}: {}", tag, line);
        if let Some(buf) = &capture {
            if let Ok(mut g) = buf.try_lock() {
                use std::fmt::Write;
                let _ = writeln!(g, "{line}");
                const MAX: usize = 8192;
                if g.len() > MAX {
                    let excess = g.len() - MAX;
                    *g = g[excess..].to_string();
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_data_dir(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("hermesdesk-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    #[test]
    fn copy_host_soul_overwrites_profile_soul() {
        let data_dir = temp_data_dir("soul-copy");
        let host_home = hermes_home_path(&data_dir);
        let profile_dir = profile_home_path(&data_dir, "telegram");
        std::fs::create_dir_all(&host_home).expect("create host home");
        std::fs::create_dir_all(&profile_dir).expect("create profile dir");
        std::fs::write(host_home.join("SOUL.md"), "You are Kabuqina.")
            .expect("write host SOUL");
        std::fs::write(profile_dir.join("SOUL.md"), "You are Hermes Agent.")
            .expect("write stale profile SOUL");

        copy_host_soul(&data_dir, &profile_dir).expect("copy host SOUL");

        assert_eq!(
            std::fs::read_to_string(profile_dir.join("SOUL.md")).expect("read profile SOUL"),
            "You are Kabuqina."
        );

        let _ = std::fs::remove_dir_all(data_dir);
    }

    #[test]
    fn copy_host_soul_removes_stale_profile_soul_when_host_missing() {
        let data_dir = temp_data_dir("soul-remove");
        let profile_dir = profile_home_path(&data_dir, "telegram");
        std::fs::create_dir_all(&profile_dir).expect("create profile dir");
        std::fs::write(profile_dir.join("SOUL.md"), "You are Hermes Agent.")
            .expect("write stale profile SOUL");

        copy_host_soul(&data_dir, &profile_dir).expect("sync missing host SOUL");

        assert!(!profile_dir.join("SOUL.md").exists());

        let _ = std::fs::remove_dir_all(data_dir);
    }
}
