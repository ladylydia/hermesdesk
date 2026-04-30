//! Second bundled Python process: ``python -m gateway.run``.
//!
//! HermesDesk always runs ``desktop_entrypoint`` (web UI). Messaging adapters live in the
//! separate gateway process — same layout as ``hermes gateway run`` on Linux.

use anyhow::{Context, Result};
use serde::Serialize;
use std::collections::HashMap;
use std::env;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

use crate::python_supervisor::SpawnConfig;

/// Same Hermes root as ``desktop_entrypoint`` / ``weixin_qr_worker`` (``HERMESDESK_DATA_DIR/hermes-home``).
pub fn hermes_home_path(data_dir: &Path) -> PathBuf {
    data_dir.join("hermes-home")
}

/// True when the shipped ``hermes/gateway/run.py`` contains the first-connect
/// “stay alive for reconnect watcher” path (HermesDesk bundle must be rebuilt
/// after upstream gateway changes).
pub fn bundled_gateway_has_startup_survival(bundle_dir: &Path) -> bool {
    let p = bundle_dir.join("hermes").join("gateway").join("run.py");
    let Ok(s) = std::fs::read_to_string(&p) else {
        return false;
    };
    s.contains("keep the process alive") && s.contains("_platform_reconnect_watcher")
}

/// Best-effort read of ``gateway_state.json`` (written by the messaging gateway) for diagnostics.
pub fn read_gateway_state_snapshot(hermes_home: &Path) -> (Option<String>, Option<String>) {
    let path = hermes_home.join("gateway_state.json");
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
            format!("{trunc}…")
        } else {
            s.to_string()
        }
    });
    (state, reason)
}

/// Last lines of ``{hermes_home}/logs/gateway.log`` for startup failure hints.
pub fn tail_gateway_log(hermes_home: &Path, max_tail_bytes: u64) -> Option<String> {
    let path = hermes_home.join("logs").join("gateway.log");
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
        Some(format!("{}…", tail.chars().take(380).collect::<String>()))
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

/// Parse ``hermes-home/.env`` into upper-case keys → non-empty values.
fn parse_dotenv_upper(hermes_home: &Path) -> HashMap<String, String> {
    let mut keys: HashMap<String, String> = HashMap::new();
    let dotenv = hermes_home.join(".env");
    let Ok(raw) = std::fs::read_to_string(&dotenv) else {
        return keys;
    };
    // Strip UTF-8 BOM so the first key is not stored as "\u{feff}WEIXIN_…".
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

/// Whether route-C Weixin credentials exist on disk, plus a short display hint (no token).
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WeixinEnvSnapshot {
    pub configured: bool,
    /// ``WEIXIN_ACCOUNT_ID`` present and non-empty in ``.env`` (used for partial-config UI).
    pub has_account_id: bool,
    /// ``WEIXIN_TOKEN`` present and non-empty in ``.env``.
    pub has_token: bool,
    pub account_id_hint: Option<String>,
}

pub fn read_weixin_env_snapshot(hermes_home: &Path) -> WeixinEnvSnapshot {
    let keys = parse_dotenv_upper(hermes_home);
    let account = keys.get("WEIXIN_ACCOUNT_ID").cloned();
    let has_token = keys.get("WEIXIN_TOKEN").map(|s| !s.is_empty()).unwrap_or(false);
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

/// QQ Bot credentials on disk (no ``QQ_CLIENT_SECRET`` returned).
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct QqEnvSnapshot {
    pub configured: bool,
    pub has_app_id: bool,
    pub has_client_secret: bool,
    pub app_id_hint: Option<String>,
}

pub fn read_qq_env_snapshot(hermes_home: &Path) -> QqEnvSnapshot {
    let keys = parse_dotenv_upper(hermes_home);
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

/// Feishu / Lark custom-app credentials (no ``FEISHU_APP_SECRET`` returned).
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FeishuEnvSnapshot {
    pub configured: bool,
    pub has_app_id: bool,
    pub has_app_secret: bool,
    pub app_id_hint: Option<String>,
}

pub fn read_feishu_env_snapshot(hermes_home: &Path) -> FeishuEnvSnapshot {
    let keys = parse_dotenv_upper(hermes_home);
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

/// Telegram bot token presence (token value is never returned; optional masked hint when configured).
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct TelegramEnvSnapshot {
    pub configured: bool,
    pub has_bot_token: bool,
    /// True when other ``TELEGRAM_*`` keys exist but the bot token is missing.
    pub orphan_telegram_config: bool,
    pub token_hint: Option<String>,
}

pub fn read_telegram_env_snapshot(hermes_home: &Path) -> TelegramEnvSnapshot {
    let keys = parse_dotenv_upper(hermes_home);
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
    format!("{head}…{tail}")
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
    format!("…{tail}")
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
    format!("…{tail}")
}

/// Heuristic: ``hermes-home/.env`` has at least one messaging platform the gateway can connect.
pub fn dotenv_suggests_messaging_gateway(hermes_home: &Path) -> bool {
    let keys = parse_dotenv_upper(hermes_home);
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
    false
}

pub struct GatewaySupervisor {
    child: Child,
    /// Captured early stderr lines (first 4 KiB) — for startup diagnostics.
    captured_stderr: Arc<Mutex<String>>,
}

impl GatewaySupervisor {
    pub async fn spawn(cfg: &SpawnConfig) -> Result<Self> {
        let py_exe = cfg.bundle_dir.join("python").join("python.exe");
        anyhow::ensure!(py_exe.exists(), "python.exe missing at {}", py_exe.display());

        let hermes_home = hermes_home_path(&cfg.data_dir);
        std::fs::create_dir_all(&hermes_home).context("create hermes-home")?;

        let mut cmd = Command::new(&py_exe);
        cmd.args([
       	        "-m",
                "gateway.run",
        ])
        .current_dir(&cfg.bundle_dir)
        .env("HERMES_HOME", hermes_home.as_os_str())
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
        .env_remove("OPENAI_API_KEY")
        .env_remove("ANTHROPIC_API_KEY")
        .env_remove("OPENROUTER_API_KEY")
        // Keep generic proxy vars so the gateway can still pick them up via
        // resolve_proxy_url() as a fallback.  Loopback is protected by NO_PROXY.
        .env_remove("PYTHONPATH")
        // ``-m hermes_cli.gateway.run`` does not run ``desktop_entrypoint``'s ``_wire_sys_path()``;
        // deps (PyYAML → ``import yaml``, fastapi, …) live under ``site-packages/``.
        .env(
            "PYTHONPATH",
            env::join_paths([cfg.bundle_dir.join("site-packages"), cfg.bundle_dir.join("hermes")])
                .map_err(|e| anyhow::anyhow!("PYTHONPATH: {e}"))?,
        )
        .env("NO_PROXY", "127.0.0.1,localhost,::1");

    // Inject HermesDesk-managed proxy if the user has opted in.
    if let Some(proxy_url) = crate::proxy::read_effective_proxy_for_hermes_home(&hermes_home) {
        cmd.env("HERMESDESK_PROXY_URL", proxy_url);
    }

    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

        log::info!("[gateway_spawn] about to spawn: {:?}", py_exe);
        let mut child = match cmd.spawn() {
            Ok(c) => {
                log::info!("[gateway_spawn] child spawned, pid={:?}", c.id());
                c
            }
            Err(e) => {
                log::error!("[gateway_spawn] spawn FAILED: {:#}", e);
                return Err(e).context("spawn gateway python");
            }
        };

        let captured = Arc::new(Mutex::new(String::new()));

        if let Some(out) = child.stdout.take() {
            tokio::spawn(forward("gw.out", out, None));
        }
        if let Some(err) = child.stderr.take() {
            tokio::spawn(forward("gw.err", err, Some(captured.clone())));
        }

        log::info!("[gateway_spawn] returning GatewaySupervisor");
        Ok(Self { child, captured_stderr: captured })
    }

    pub fn shutdown(mut self) -> Result<()> {
        let _ = self.child.start_kill();
        Ok(())
    }

    /// Non-blocking: reap if the child already exited.
    pub fn try_reap(&mut self) -> std::io::Result<Option<std::process::ExitStatus>> {
        self.child.try_wait()
    }

    /// Early stderr lines captured during spawn (up to first 4 KiB).
    pub fn stderr_snapshot(&self) -> String {
        // best-effort: try deprecated poll_lock first for single-threaded runtime
        match self.captured_stderr.try_lock() {
            Ok(g) => g.clone(),
            Err(_) => String::from("(stderr capture busy)"),
        }
    }
}

async fn forward<R: tokio::io::AsyncRead + Unpin + Send + 'static>(
    tag: &'static str,
    r: R,
    capture: Option<Arc<Mutex<String>>>,
) {
    log::info!("[forward] starting tag={}", tag);
    let mut lines = BufReader::new(r).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        log::info!("{}: {}", tag, line);
        if let Some(buf) = &capture {
            if let Ok(mut g) = buf.try_lock() {
                if g.len() < 4096 {
                    use std::fmt::Write;
                    let _ = writeln!(g, "{line}");
                }
            }
        }
    }
    log::info!("[forward] tag={} ended (stream closed or error)", tag);
}
