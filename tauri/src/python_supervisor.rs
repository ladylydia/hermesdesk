//! Spawn and supervise the embedded Python child.

use anyhow::{Context, Result};
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use tauri::AppHandle;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

#[derive(Clone)]
pub struct SpawnConfig {
    pub bundle_dir: PathBuf,
    pub data_dir: PathBuf,
    pub workspace: PathBuf,
    pub secret_url: String,
    pub approval_url: String,
    pub desktop_delivery_url: String,
    /// Must match Tauri `X-HermesDesk-Auth` header for shell → Hermes HTTP.
    pub desk_auth_token: String,
    /// ``GET /shell-chat/{desk_auth_token}`` on the loopback bridge — "back to shell chat" in Hermes UI.
    pub shell_chat_back_url: String,
    pub provider: String,
    pub llm_host: String,
    pub api_base_url: Option<String>,
    pub hermes_model: Option<String>,
    pub inference_provider: Option<String>,
    pub power_user: bool,
    /// LLM API key plaintext, injected as the corresponding env var for
    /// gateway children (which can't fetch via HERMESDESK_SECRET_URL).
    pub api_key: Option<String>,
    /// The env var name to set (e.g. "OPENAI_API_KEY", "OPENROUTER_API_KEY").
    pub api_key_env_name: String,
}

pub struct Supervisor {
    child: Child,
    port_file: PathBuf,
    pub pid: Option<u32>,
}

impl Supervisor {
    pub async fn spawn(cfg: SpawnConfig) -> Result<Self> {
        let py_exe = cfg.bundle_dir.join("python").join("python.exe");
        anyhow::ensure!(
            py_exe.exists(),
            "python.exe missing at {}",
            py_exe.display()
        );

        let entry = cfg.bundle_dir.join("desktop_entrypoint.py");
        anyhow::ensure!(entry.exists(), "desktop_entrypoint.py missing");

        let port_file = cfg.data_dir.join("port.txt");
        let _ = std::fs::remove_file(&port_file);

        let mut cmd = Command::new(&py_exe);
        cmd.arg(&entry)
            .env("HERMESDESK_BUNDLE_DIR", &cfg.bundle_dir)
            .env("HERMESDESK_DATA_DIR", &cfg.data_dir)
            .env("HERMESDESK_WORKSPACE", &cfg.workspace)
            .env("HERMES_WORKSPACE", &cfg.workspace)
            .env("TERMINAL_CWD", &cfg.workspace)
            .env("HERMESDESK_PORT_FILE", &port_file)
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
            .env("HERMESDESK_DESKTOP_DELIVERY_URL", &cfg.desktop_delivery_url)
            .env("HERMESDESK_BRIDGE_SECRET", &cfg.desk_auth_token)
            .env("HERMESDESK_SHELL_CHAT_URL", &cfg.shell_chat_back_url)
            .env(
                "HERMESDESK_POWER_USER",
                if cfg.power_user { "1" } else { "0" },
            )
            // HermesDesk desktop contract version.  Must match
            // ``python/src/desktop_contract.py:CONTRACT_VERSION``.
            .env("HERMESDESK_CONTRACT_VERSION", "1")
            // Tell the upstream Hermes approval guard that we're in an
            // interactive context so it routes dangerous commands through
            // ``prompt_dangerous_approval`` (which the approval_bridge.py
            // overlay intercepts with a Tauri native dialog).  Without this
            // marker the web_server mode skips all approval checks and
            // the Tauri approval bridge is never reached.
            .env("HERMES_INTERACTIVE", "1")
            // Edge CDP browser backend — lets Hermes drive Edge via CDP
            // without Node.js / Playwright. Set unconditionally; the browser
            // tool checks connectivity at runtime.
            .env("BROWSER_CDP_URL", crate::edge_browser::cdp_url())
            .env("HERMESDESK_OVERLAY_LENIENT", "0")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("PYTHONUNBUFFERED", "1")
            // Don't inherit any stale provider keys from the user shell
            .env_remove("OPENAI_API_KEY")
            .env_remove("DEEPSEEK_API_KEY")
            .env_remove("ANTHROPIC_API_KEY")
            .env_remove("OPENROUTER_API_KEY")
            // CRITICAL: strip every proxy var the user's shell may have set.
            // Otherwise Python's urllib / httpx will route our loopback
            // bridge call (http://127.0.0.1:PORT/...) through the user's
            // VPN / Clash / SS proxy, which has no idea how to handle
            // loopback and silently hangs. The Hermes child should never
            // need an HTTP proxy: it talks to the LLM provider directly,
            // and the user's VPN sees that traffic at the system level.
            .env_remove("HTTP_PROXY")
            .env_remove("http_proxy")
            .env_remove("HTTPS_PROXY")
            .env_remove("https_proxy")
            .env_remove("ALL_PROXY")
            .env_remove("all_proxy")
            .env_remove("NO_PROXY")
            .env_remove("no_proxy")
            // Dev shells often set PYTHONPATH to the git ``hermes/`` tree; that can shadow
            // the bundle's ``site-packages`` (wrong/missing ``yaml``, ``fastapi``, …).
            .env_remove("PYTHONPATH")
            .env("NO_PROXY", "127.0.0.1,localhost,::1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Hide the console window on Windows.
        // tokio::process::Command exposes `creation_flags` directly on Windows
        // (no need to import std::os::windows::process::CommandExt).
        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd.spawn().context("spawn python")?;
        let pid = child.id();

        if let Some(out) = child.stdout.take() {
            tokio::spawn(forward("py.out", out));
        }
        if let Some(err) = child.stderr.take() {
            tokio::spawn(forward("py.err", err));
        }

        Ok(Self {
            child,
            port_file,
            pid,
        })
    }

    pub async fn wait_for_port(&self) -> Result<u16> {
        // Cold start imports `hermes_cli.web_server` before writing port.txt — on first
        // launch Windows Defender indexing this tree can exceed 30s; portable users then
        // see "connecting forever" because Rust abandoned the waiter while Python is still waking.
        let deadline = std::time::Instant::now() + Duration::from_secs(180);
        loop {
            // Use async fs so we don't starve other tasks (e.g. the bridge
            // serve loop) on Tauri's single-threaded runtime.
            if let Ok(s) = tokio::fs::read_to_string(&self.port_file).await {
                if let Ok(p) = s.trim().parse::<u16>() {
                    return Ok(p);
                }
            }
            if std::time::Instant::now() > deadline {
                anyhow::bail!("python did not write port within 30s");
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    pub fn shutdown(mut self) -> Result<()> {
        // Try graceful first, then kill.
        let _ = self.child.start_kill();
        Ok(())
    }
}

async fn forward<R: tokio::io::AsyncRead + Unpin + Send + 'static>(tag: &'static str, r: R) {
    let mut lines = BufReader::new(r).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        log::info!("{tag}: {line}");
    }
}

#[derive(serde::Serialize)]
pub struct PythonStatus {
    pub running: bool,
}

#[tauri::command]
pub async fn cmd_python_status(
    state: tauri::State<'_, crate::AppState>,
) -> Result<PythonStatus, String> {
    let sup = state.supervisor.lock().await;
    Ok(PythonStatus {
        running: sup.is_some(),
    })
}

// Keep AppHandle import linked even if unused in some build configs.
#[allow(dead_code)]
fn _hint(_a: AppHandle) {}
