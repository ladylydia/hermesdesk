//! HermesDesk Tauri shell.
//!
//! Responsibilities:
//!  - Spawn and supervise the embedded Python process (`python_supervisor`)
//!  - Expose a tiny loopback HTTP server for secret handshake +
//!    shell-approval bridge (`bridge`)
//!  - Own the Windows Credential Manager-backed key vault (`secrets`)
//!  - Own the system tray + main window
//!  - Wait for Python's port handshake (embedded Hermes serves on loopback; the shell can open it in the system browser)
//!
//! All business logic lives in Python. This crate is a thin process
//! supervisor + secret/safety boundary.

mod bridge;
mod chat;
mod dingtalk_env;
mod feishu_env;
mod feishu_qr;
mod gateway_supervisor;
mod pairing;
mod paths;
mod proxy;
mod python_supervisor;
mod qq_env;
mod qqbot_qr;
mod secrets;
mod telegram_env;
mod tray;
mod validation;
mod wecom_env;
mod wecom_qr;
mod weixin_qr;

use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tauri::{Manager, RunEvent};
use tokio::sync::Mutex;
use url::Url;

pub struct AppState {
    pub supervisor: Arc<Mutex<Option<python_supervisor::Supervisor>>>,
    /// Optional ``hermes gateway run`` child (messaging adapters).
    pub gateway_supervisor: Arc<Mutex<Option<gateway_supervisor::GatewaySupervisor>>>,
    /// Optional Weixin QR login child (`weixin_qr_worker.py`); separate from the long-lived Hermes process.
    pub weixin_qr_child: Arc<Mutex<Option<tokio::process::Child>>>,
    /// Optional QQ Bot QR login child (`qqbot_qr_worker.py`); separate from the long-lived Hermes process.
    pub qqbot_qr_child: Arc<Mutex<Option<tokio::process::Child>>>,
    /// Optional Feishu / Lark QR login child (`feishu_qr_worker.py`); separate from the long-lived Hermes process.
    pub feishu_qr_child: Arc<Mutex<Option<tokio::process::Child>>>,
    /// Optional WeCom QR login child (`wecom_qr_worker.py`); separate from the long-lived Hermes process.
    pub wecom_qr_child: Arc<Mutex<Option<tokio::process::Child>>>,
    pub bridge_addr: Arc<Mutex<Option<std::net::SocketAddr>>>,
    /// Cached from `bridge::Bridge` for respawning Python without a second `bridge::spawn`.
    pub bridge_secret_url: Arc<Mutex<Option<String>>>,
    pub bridge_approval_url: Arc<Mutex<Option<String>>>,
    /// Loopback port for Hermes `web_server` (set after Python writes `port.txt`).
    pub hermes_port: Arc<Mutex<Option<u16>>>,
    /// Same value as Python `HERMESDESK_BRIDGE_SECRET` for `X-HermesDesk-Auth`.
    pub desk_auth_token: Arc<Mutex<Option<String>>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let supervisor = Arc::new(Mutex::new(None));
    let bridge_addr = Arc::new(Mutex::new(None));

    let state = AppState {
        supervisor: supervisor.clone(),
        gateway_supervisor: Arc::new(Mutex::new(None)),
        weixin_qr_child: Arc::new(Mutex::new(None)),
        qqbot_qr_child: Arc::new(Mutex::new(None)),
        feishu_qr_child: Arc::new(Mutex::new(None)),
        wecom_qr_child: Arc::new(Mutex::new(None)),
        bridge_addr: bridge_addr.clone(),
        bridge_secret_url: Arc::new(Mutex::new(None)),
        bridge_approval_url: Arc::new(Mutex::new(None)),
        hermes_port: Arc::new(Mutex::new(None)),
        desk_auth_token: Arc::new(Mutex::new(None)),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_fs::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            secrets::cmd_save_secret,
            secrets::cmd_has_secret,
            secrets::cmd_llm_config_preview,
            secrets::cmd_clear_secret,
            secrets::cmd_validate_endpoint,
            python_supervisor::cmd_python_status,
            paths::cmd_workspace_path,
            paths::cmd_open_workspace,
            paths::cmd_get_power_user,
            cmd_set_power_user,
            paths::cmd_get_show_recipe_market,
            paths::cmd_set_show_recipe_market,
            paths::cmd_set_personality,
            paths::cmd_get_auto_start_gateway,
            paths::cmd_set_auto_start_gateway,
            cmd_gateway_status,
            cmd_gateway_start,
            cmd_gateway_stop,
            cmd_get_hermes_port,
            cmd_open_hermes_dashboard,
            chat::cmd_chat_send,
            chat::cmd_desk_stop,
            chat::cmd_get_sessions,
            chat::cmd_get_session_messages,
            chat::cmd_delete_session,
            weixin_qr::cmd_weixin_qr_start,
            weixin_qr::cmd_weixin_qr_status,
            weixin_qr::cmd_weixin_env_status,
            qq_env::cmd_qq_env_status,
            feishu_env::cmd_feishu_env_status,
            telegram_env::cmd_telegram_env_status,
            telegram_env::cmd_telegram_save_token,
            telegram_env::cmd_telegram_remove_config,
            weixin_qr::cmd_weixin_env_remove,
            qq_env::cmd_qq_env_remove,
            feishu_env::cmd_feishu_env_remove,
            dingtalk_env::cmd_dingtalk_env_status,
            dingtalk_env::cmd_dingtalk_env_remove,
            dingtalk_env::cmd_dingtalk_save_config,
            wecom_env::cmd_wecom_env_status,
            wecom_env::cmd_wecom_env_remove,
            wecom_env::cmd_wecom_save_config,
            wecom_qr::cmd_wecom_qr_start,
            wecom_qr::cmd_wecom_qr_status,
            wecom_qr::cmd_wecom_qr_cancel,
            proxy::cmd_proxy_status,
            proxy::cmd_proxy_save,
            weixin_qr::cmd_weixin_qr_cancel,
            weixin_qr::cmd_restart_embedded_hermes,
            qqbot_qr::cmd_qqbot_qr_start,
            qqbot_qr::cmd_qqbot_qr_status,
            qqbot_qr::cmd_qqbot_qr_cancel,
            feishu_qr::cmd_feishu_qr_start,
            feishu_qr::cmd_feishu_qr_status,
            feishu_qr::cmd_feishu_qr_cancel,
            pairing::cmd_pairing_list,
            pairing::cmd_pairing_approve,
            pairing::cmd_pairing_revoke,
            pairing::cmd_pairing_clear_pending,
        ])
        .setup(|app| {
            tray::install(app)?;
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = bootstrap(handle).await {
                    log::error!("bootstrap failed: {e:#}");
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error building HermesDesk")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = &event {
                // Clone `Arc`s then drop `State` so `try_lock` temporaries never borrow `state`
                // across the end of the block (E0597 with nested `if let` + `try_lock`).
                let state: tauri::State<AppState> = app.state();
                let supervisor = state.supervisor.clone();
                let gateway = state.gateway_supervisor.clone();
                let weixin_qr = state.weixin_qr_child.clone();
                let qqbot_qr = state.qqbot_qr_child.clone();
                let feishu_qr = state.feishu_qr_child.clone();
                std::mem::drop(state);
                let sup_lock = supervisor.try_lock();
                if let Ok(mut sup) = sup_lock {
                    if let Some(s) = sup.take() {
                        let _ = s.shutdown();
                    }
                }
                let gw_lock = gateway.try_lock();
                if let Ok(mut gw) = gw_lock {
                    if let Some(g) = gw.take() {
                        let _ = g.shutdown();
                    }
                }
                let wq_lock = weixin_qr.try_lock();
                if let Ok(mut wq) = wq_lock {
                    if let Some(mut c) = wq.take() {
                        let _ = c.start_kill();
                    }
                }
                let qq_lock = qqbot_qr.try_lock();
                if let Ok(mut qq) = qq_lock {
                    if let Some(mut c) = qq.take() {
                        let _ = c.start_kill();
                    }
                }
                let fq_lock = feishu_qr.try_lock();
                if let Ok(mut fq) = fq_lock {
                    if let Some(mut c) = fq.take() {
                        let _ = c.start_kill();
                    }
                }
            }
        });
}

async fn resolve_spawn_config_for_children(app: &tauri::AppHandle) -> Result<python_supervisor::SpawnConfig, String> {
    let state: tauri::State<'_, AppState> = app.state();
    let secret_url = state
        .bridge_secret_url
        .lock()
        .await
        .clone()
        .ok_or_else(|| "bridge not initialised (secret URL)".to_string())?;
    let approval_url = state
        .bridge_approval_url
        .lock()
        .await
        .clone()
        .ok_or_else(|| "bridge not initialised (approval URL)".to_string())?;
    let desk_token = state
        .desk_auth_token
        .lock()
        .await
        .clone()
        .ok_or_else(|| "bridge not initialised (token)".to_string())?;
    let baddr = *state
        .bridge_addr
        .lock()
        .await
        .as_ref()
        .ok_or_else(|| "bridge not initialised (addr)".to_string())?;

    let workspace = paths::ensure_workspace(app).map_err(|e| e.to_string())?;
    let bundle_dir = paths::resolve_runtime_dir(app).map_err(|e| e.to_string())?;
    let data_dir = paths::ensure_data_dir(app).map_err(|e| e.to_string())?;
    let llm = secrets::resolve_llm_spawn_params(app);
    let power_user = paths::is_power_user(app);
    let shell_chat_back_url = format!(
        "http://127.0.0.1:{}/shell-chat/{}",
        baddr.port(),
        desk_token
    );

    Ok(python_supervisor::SpawnConfig {
        bundle_dir,
        data_dir,
        workspace,
        secret_url,
        approval_url,
        desk_auth_token: desk_token,
        shell_chat_back_url,
        provider: llm.provider,
        llm_host: llm.llm_host,
        api_base_url: llm.api_base_url,
        hermes_model: llm.hermes_model,
        inference_provider: llm.inference_provider,
        power_user,
    })
}

async fn stop_gateway_service(app: &tauri::AppHandle) {
    let state: tauri::State<AppState> = app.state();
    let mut g = state.gateway_supervisor.lock().await;
    if let Some(gw) = g.take() {
        let _ = gw.shutdown().await;
    }
    drop(g);

    // Clean up stale gateway state files that the Python process may not
    // have had a chance to remove (atexit handlers don't run on SIGKILL).
    let data_dir = match paths::ensure_data_dir(app) {
        Ok(d) => d,
        Err(_) => return,
    };
    let hh = gateway_supervisor::hermes_home_path(&data_dir);
    let _ = std::fs::remove_file(hh.join("gateway.lock"));
    let _ = std::fs::remove_file(hh.join("gateway.pid"));
    // Write gateway_state as "stopped" so frontend doesn't show stale state.
    if let Ok(json) = serde_json::to_string(&serde_json::json!({
        "gateway_state": "stopped",
        "pid": null,
        "exit_reason": "stopped_by_user",
        "restart_requested": false,
        "platforms": {},
    })) {
        let _ = std::fs::write(hh.join("gateway_state.json"), &json);
    }
}

async fn maybe_auto_start_gateway_service(
    app: &tauri::AppHandle,
    cfg: &python_supervisor::SpawnConfig,
) {
    if !paths::is_auto_start_gateway(app) {
        return;
    }
    let hh = gateway_supervisor::hermes_home_path(&cfg.data_dir);
    if !gateway_supervisor::dotenv_suggests_messaging_gateway(&hh) {
        return;
    }
    let state: tauri::State<AppState> = app.state();
    let mut lock = state.gateway_supervisor.lock().await;
    if let Some(mut existing) = lock.take() {
        match existing.try_reap() {
            Ok(None) => {
                *lock = Some(existing);
                log::info!("messaging gateway already running; skip auto-start");
                return;
            }
            Ok(Some(st)) => {
                log::info!("messaging gateway had exited ({st}); starting a new one");
                let _ = existing.shutdown();
            }
            Err(e) => {
                log::warn!("messaging gateway try_reap: {e}; replacing process");
                let _ = existing.shutdown();
            }
        }
    }
    drop(lock);
    match gateway_supervisor::GatewaySupervisor::spawn(cfg).await {
        Ok(gw) => {
            log::info!("messaging gateway started (auto)");
            let state: tauri::State<AppState> = app.state();
            *state.gateway_supervisor.lock().await = Some(gw);
        }
        Err(e) => log::warn!("messaging gateway auto-start failed: {e:#}"),
    }
}

/// After embedded Hermes restarts (e.g. Weixin QR saved env), always bring the gateway up when
/// ``.env`` looks configured — independent of ``is_auto_start_gateway`` (that toggle is cold-start only).
async fn ensure_gateway_after_hermes_respawn(
    app: &tauri::AppHandle,
    cfg: &python_supervisor::SpawnConfig,
) {
    let hh = gateway_supervisor::hermes_home_path(&cfg.data_dir);
    if !gateway_supervisor::dotenv_suggests_messaging_gateway(&hh) {
        return;
    }
    match gateway_supervisor::GatewaySupervisor::spawn(cfg).await {
        Ok(gw) => {
            log::info!("messaging gateway started after Hermes respawn");
            let state: tauri::State<AppState> = app.state();
            *state.gateway_supervisor.lock().await = Some(gw);
        }
        Err(e) => log::warn!("messaging gateway start after Hermes respawn failed: {e:#}"),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GatewayStatusPayload {
    pub running: bool,
    pub eligible: bool,
    /// Bundled ``hermes/gateway/run.py`` includes first-connect survival (post build_bundle).
    pub embedded_gateway_startup_survival: bool,
    /// Last ``gateway_state`` from ``hermes-home/gateway_state.json`` when readable.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disk_gateway_state: Option<String>,
    /// Last ``exit_reason`` from the same file (truncated).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disk_exit_reason: Option<String>,
    /// Platform connection states from ``gateway_state.json`` (per-adapter progress).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub platforms: Option<serde_json::Map<String, serde_json::Value>>,
}

#[tauri::command]
async fn cmd_gateway_status(app: tauri::AppHandle) -> Result<GatewayStatusPayload, String> {
    let data_dir = paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = gateway_supervisor::hermes_home_path(&data_dir);
    let eligible = gateway_supervisor::dotenv_suggests_messaging_gateway(&hh);
    let (disk_gateway_state, disk_exit_reason) =
        gateway_supervisor::read_gateway_state_snapshot(&hh);

    let platforms: Option<serde_json::Map<String, serde_json::Value>> =
        std::fs::read_to_string(hh.join("gateway_state.json"))
            .ok()
            .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
            .and_then(|v| v.get("platforms").cloned())
            .and_then(|p| p.as_object().cloned());

    let embedded_gateway_startup_survival =
        match resolve_spawn_config_for_children(&app).await {
            Ok(cfg) => gateway_supervisor::bundled_gateway_has_startup_survival(&cfg.bundle_dir),
            Err(_) => false,
        };
    let state: tauri::State<AppState> = app.state();
    let mut g = state.gateway_supervisor.lock().await;
    let running = match g.as_mut() {
        None => false,
        Some(gw) => match gw.try_reap() {
            Ok(None) => true,
            Ok(Some(_st)) => {
                let _ = g.take();
                false
            }
            Err(_) => true,
        },
    };
    Ok(GatewayStatusPayload {
        running,
        eligible,
        embedded_gateway_startup_survival,
        disk_gateway_state,
        disk_exit_reason,
        platforms,
    })
}

#[tauri::command]
async fn cmd_gateway_start(app: tauri::AppHandle) -> Result<(), String> {
    let cfg = resolve_spawn_config_for_children(&app).await?;
    let hh = gateway_supervisor::hermes_home_path(&cfg.data_dir);
    if !gateway_supervisor::dotenv_suggests_messaging_gateway(&hh) {
        return Err(
            "No messaging credentials found in hermes-home/.env. Open Keys in Hermes and save tokens first."
                .into(),
        );
    }
    stop_gateway_service(&app).await;
    let gw = gateway_supervisor::GatewaySupervisor::spawn(&cfg)
        .await
        .map_err(|e| e.to_string())?;
    let state: tauri::State<AppState> = app.state();
    *state.gateway_supervisor.lock().await = Some(gw);
    // Detect immediate crash (e.g. old Hermes exited when all platforms failed on first connect).
    tokio::time::sleep(Duration::from_secs(2)).await;
    let state: tauri::State<AppState> = app.state();
    let mut lock = state.gateway_supervisor.lock().await;
    if let Some(mut gw) = lock.take() {
        match gw.try_reap() {
            Ok(None) => {
                *lock = Some(gw);
                log::info!("messaging gateway still running after manual start");
            }
            Ok(Some(st)) => {
                let stderr = gw.stderr_snapshot();
                drop(lock);
                let hh = gateway_supervisor::hermes_home_path(&cfg.data_dir);
                let (_, disk_exit) = gateway_supervisor::read_gateway_state_snapshot(&hh);
                let log_tail = gateway_supervisor::tail_gateway_log(&hh, 4096);
                let mut parts = vec![format!("Gateway exited during startup ({st}).")];
                if let Some(r) = disk_exit.as_ref().filter(|s| !s.is_empty()) {
                    parts.push(format!("Recorded: {r}"));
                }
                if let Some(t) = log_tail {
                    parts.push(format!("gateway.log (tail): {t}"));
                }
                let stderr_trimmed = stderr.trim();
                if !stderr_trimmed.is_empty() {
                    const MAX: usize = 2000;
                    let capped: String = if stderr_trimmed.chars().count() > MAX {
                        let trunc: String = stderr_trimmed.chars().take(MAX).collect();
                        format!("{trunc}…")
                    } else {
                        stderr_trimmed.to_string()
                    };
                    parts.push(format!("stderr (captured): {capped}"));
                }
                parts.push(
                    "If this persists: run python/build_bundle.ps1 so hermes-home picks up the latest gateway (first-connect retry fix), then relaunch HermesDesk."
                        .into(),
                );
                if !gateway_supervisor::bundled_gateway_has_startup_survival(&cfg.bundle_dir) {
                    parts.push(
                        "Detected: the embedded runtime’s hermes/gateway/run.py does NOT include the first-connect survival patch — your bundle is almost certainly stale. Close HermesDesk, run python/build_bundle.ps1 from the repo root, then relaunch (a dev build must use the refreshed python/dist/runtime)."
                            .into(),
                    );
                }
                return Err(parts.join(" "));
            }
            Err(e) => {
                log::warn!("gateway try_reap after manual start: {e}");
                *lock = Some(gw);
            }
        }
    }
    Ok(())
}

#[tauri::command]
async fn cmd_gateway_stop(app: tauri::AppHandle) -> Result<(), String> {
    stop_gateway_service(&app).await;
    Ok(())
}

async fn bootstrap(app: tauri::AppHandle) -> anyhow::Result<()> {
    // 1. Workspace + data dirs (spawn config resolves paths again).
    paths::ensure_workspace(&app)?;
    paths::ensure_data_dir(&app)?;
    paths::resolve_runtime_dir(&app)?;
    paths::sync_show_recipe_market_flag(&app)?;

    // 2. Stand up the loopback bridge (secret handshake + shell approval).
    let bridge = bridge::spawn(app.clone()).await?;
    {
        let state: tauri::State<AppState> = app.state();
        *state.bridge_addr.lock().await = Some(bridge.addr);
        *state.desk_auth_token.lock().await = Some(bridge.desk_auth_token.clone());
        *state.bridge_secret_url.lock().await = Some(bridge.secret_url.clone());
        *state.bridge_approval_url.lock().await = Some(bridge.approval_url.clone());
    }

    // 3. Spawn the Python child (Hermes web_server / desktop_entrypoint).
    //    Errors here are logged but do NOT block the window from showing,
    //    so the user can see the shell UI and diagnose startup issues.
    let hermes_ok = async {
        let spawn_cfg = resolve_spawn_config_for_children(&app)
            .await
            .map_err(|e| anyhow::anyhow!(e))?;
        let supervisor =
            python_supervisor::Supervisor::spawn(app.clone(), spawn_cfg.clone()).await?;

        let port = supervisor.wait_for_port().await?;
        log::info!("python ready on port {port}");

        {
            let state: tauri::State<AppState> = app.state();
            *state.supervisor.lock().await = Some(supervisor);
            *state.hermes_port.lock().await = Some(port);
        }

        maybe_auto_start_gateway_service(&app, &spawn_cfg).await;
        anyhow::Result::<()>::Ok(())
    }
    .await;

    match hermes_ok {
        Ok(()) => log::info!("Hermes Python bootstrap complete"),
        Err(e) => log::error!("Hermes Python bootstrap failed: {e}"),
    }

    // 4. Reveal the window regardless of Hermes state.
    //    The frontend will show a "waiting for Hermes" or error state if needed.
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    Ok(())
}

/// Re-spawn the Hermes child so `HERMESDESK_POWER_USER` and
/// `default_toolset.install()` take effect. Tooling is re-seeded on every
/// Python start; a simple settings write does not update the child.
pub(crate) async fn respawn_embedded_hermes_python(app: tauri::AppHandle) -> Result<u16, String> {
    let state: tauri::State<'_, AppState> = app.state();
    stop_gateway_service(&app).await;

    {
        let mut s = state.supervisor.lock().await;
        if let Some(sup) = s.take() {
            let _ = sup.shutdown();
        }
    }
    *state.hermes_port.lock().await = None;

    let spawn_cfg = resolve_spawn_config_for_children(&app).await?;
    let power_user = spawn_cfg.power_user;
    let supervisor = python_supervisor::Supervisor::spawn(app.clone(), spawn_cfg.clone())
        .await
        .map_err(|e| e.to_string())?;
    let port = supervisor
        .wait_for_port()
        .await
        .map_err(|e| e.to_string())?;
    *state.supervisor.lock().await = Some(supervisor);
    *state.hermes_port.lock().await = Some(port);
    log::info!("embedded Python respawned: port {port} power_user={power_user}");
    ensure_gateway_after_hermes_respawn(&app, &spawn_cfg).await;
    Ok(port)
}

/// Save the power-user flag and restart embedded Python so
/// `platform_toolsets[cli]` matches the toggle (terminal, browser, …).
#[tauri::command]
async fn cmd_set_power_user(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    paths::set_power_user_enabled(&app, enabled)?;
    respawn_embedded_hermes_python(app).await.map(|_| ())
}

/// Build `http://127.0.0.1:{port}{path}` with optional `?hermesdesk_lang=` for the embedded Hermes web UI.
fn hermes_dashboard_url(
    port: u16,
    shell_locale: Option<String>,
    path: Option<String>,
) -> Result<Url, String> {
    let path_part = path
        .as_ref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(|s| {
            if s.starts_with('/') {
                s.to_string()
            } else {
                format!("/{s}")
            }
        })
        .unwrap_or_else(|| "/".to_string());
    let mut u: Url = format!("http://127.0.0.1:{port}{path_part}")
        .parse()
        .map_err(|e: url::ParseError| e.to_string())?;
    if let Some(loc) = shell_locale
        .as_ref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        if loc == "zh" || loc == "en" {
            u.query_pairs_mut()
                .append_pair("hermesdesk_lang", loc);
        }
    }
    Ok(u)
}

/// Open the Hermes Python web UI in the **system default browser** (not the shell webview).
/// The app window stays on the current shell page; config still applies to the same local `127.0.0.1` process.
fn open_hermes_dashboard_in_browser(
    app: &tauri::AppHandle,
    port: u16,
    shell_locale: Option<String>,
    path: Option<String>,
) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let u = hermes_dashboard_url(port, shell_locale, path)?;
    app
        .opener()
        .open_url(u.as_str(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// Get the Hermes Python backend port (for diagnostics and fallbacks).
#[tauri::command]
async fn cmd_get_hermes_port(app: tauri::AppHandle) -> Result<Option<u16>, String> {
    let state: tauri::State<AppState> = app.state();
    let port = *state.hermes_port.lock().await;
    Ok(port)
}

/// Open the Hermes dashboard in the **default browser** (shell webview is unchanged).
/// Optional `shell_locale` (`"zh"` | `"en"`) is passed as `?hermesdesk_lang=` for Hermes i18n.
/// Optional `path` (e.g. `"/env"`, `"/config"`) deep-links into the SPA; `None` is the home page.
#[tauri::command]
async fn cmd_open_hermes_dashboard(
    app: tauri::AppHandle,
    shell_locale: Option<String>,
    path: Option<String>,
) -> Result<(), String> {
    let state: tauri::State<AppState> = app.state();
    let port = state
        .hermes_port
        .lock()
        .await
        .ok_or_else(|| "Hermes is not ready yet. Wait a few seconds and try again.".to_string())?;
    open_hermes_dashboard_in_browser(&app, port, shell_locale, path)
}
