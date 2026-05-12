//! Kabuqina Tauri shell.
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
mod capabilities;
mod capture;
mod chat;
mod cron;
mod dingtalk_env;
mod edge_browser;
mod email_env;
mod feishu_env;
mod feishu_qr;
mod gateway_env_patch;
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
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;
use tauri::{Manager, RunEvent};
use tokio::sync::Mutex;
use url::Url;

/// Fallback ``taskkill`` when the supervisor mutex is contended and
/// ``try_lock`` cannot acquire it at shutdown.
fn _emergency_kill_python_child() {
    let _ = std::process::Command::new("taskkill")
        .args(&["/f", "/im", "python.exe"])
        .status();
}

pub struct AppState {
    /// Edge CDP browser instance for browser automation (Windows only).
    pub edge_browser: Arc<crate::edge_browser::EdgeSupervisor>,
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
    pub bridge_desktop_delivery_url: Arc<Mutex<Option<String>>>,
    /// Pending desktop delivery messages (Python cron → frontend).
    pub desktop_messages: Arc<tokio::sync::Mutex<Vec<bridge::DesktopMessage>>>,
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
    let edge_browser = Arc::new(crate::edge_browser::EdgeSupervisor::new());

    let state = AppState {
        edge_browser: edge_browser.clone(),
        supervisor: supervisor.clone(),
        gateway_supervisor: Arc::new(Mutex::new(None)),
        weixin_qr_child: Arc::new(Mutex::new(None)),
        qqbot_qr_child: Arc::new(Mutex::new(None)),
        feishu_qr_child: Arc::new(Mutex::new(None)),
        wecom_qr_child: Arc::new(Mutex::new(None)),
        bridge_addr: bridge_addr.clone(),
        bridge_secret_url: Arc::new(Mutex::new(None)),
        bridge_approval_url: Arc::new(Mutex::new(None)),
        bridge_desktop_delivery_url: Arc::new(Mutex::new(None)),
        desktop_messages: Arc::new(tokio::sync::Mutex::new(Vec::new())),
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
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
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
            paths::cmd_read_shared_prefs,
            paths::cmd_write_text_file,
            paths::cmd_save_shared_prefs,
            cmd_gateway_status,
            cmd_gateway_start,
            cmd_gateway_stop,
            cmd_get_hermes_port,
            cmd_open_hermes_dashboard,
            capabilities::cmd_capabilities_catalog,
            capabilities::cmd_capability_skill_detail,
            chat::cmd_chat_send,
            chat::cmd_chat_send_stream,
            chat::cmd_chat_preview,
            chat::cmd_desk_stop,
            chat::cmd_get_sessions,
            chat::cmd_get_session_messages,
            chat::cmd_delete_session,
            chat::cmd_transcribe,
            chat::cmd_save_voice_setup,
            chat::cmd_stt_model_status,
            chat::cmd_stt_model_download,
            chat::cmd_tts_speak,
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
            email_env::cmd_email_env_status,
            email_env::cmd_email_save_config,
            email_env::cmd_email_env_remove,
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
            gateway_env_patch::cmd_gateway_host_env_get,
            gateway_env_patch::cmd_gateway_host_env_patch,
            pairing::cmd_pairing_list,
            pairing::cmd_pairing_approve,
            pairing::cmd_pairing_revoke,
            pairing::cmd_pairing_clear_pending,
            cmd_desktop_messages,
            cron::cmd_cron_list,
            cron::cmd_cron_toggle,
            cron::cmd_cron_delete,
            capture::cmd_capture_region,
            capture::cmd_capture_fullscreen,
            capture::cmd_show_capture_overlay,
            capture::cmd_hide_capture_overlay,
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
        .expect("error building Kabuqina")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = &event {
                // Clone `Arc`s then drop `State` so `try_lock` temporaries never borrow `state`
                // across the end of the block (E0597 with nested `if let` + `try_lock`).
                let state: tauri::State<AppState> = app.state();
                let edge = state.edge_browser.clone();
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
                } else {
                    _emergency_kill_python_child();
                }
                let gw_lock = gateway.try_lock();
                if let Ok(mut gw) = gw_lock {
                    if let Some(g) = gw.take() {
                        let _ = g.shutdown();
                    }
                } else {
                    _emergency_kill_python_child();
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
                // Kill Edge CDP browser instance.
                edge.stop();
            }
        });
}

async fn resolve_spawn_config_for_children(
    app: &tauri::AppHandle,
) -> Result<python_supervisor::SpawnConfig, String> {
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
    let desktop_delivery_url = state
        .bridge_desktop_delivery_url
        .lock()
        .await
        .clone()
        .ok_or_else(|| "bridge not initialised (desktop delivery URL)".to_string())?;
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

    // Fetch the API key and determine the correct env var name.
    let (api_key, api_key_env_name) = secrets::read_current_secret(app)
        .map(|key| {
            let env_name = secrets::provider_api_key_env(&llm.provider);
            (Some(key), env_name)
        })
        .unwrap_or((None, String::new()));

    Ok(python_supervisor::SpawnConfig {
        bundle_dir,
        data_dir,
        workspace,
        secret_url,
        approval_url,
        desktop_delivery_url,
        desk_auth_token: desk_token,
        shell_chat_back_url,
        provider: llm.provider,
        llm_host: llm.llm_host,
        api_base_url: llm.api_base_url,
        hermes_model: llm.hermes_model,
        inference_provider: llm.inference_provider,
        power_user,
        api_key,
        api_key_env_name,
    })
}

async fn stop_gateway_service(app: &tauri::AppHandle) {
    let state: tauri::State<AppState> = app.state();
    let mut g = state.gateway_supervisor.lock().await;
    if let Some(gw) = g.take() {
        let _ = gw.shutdown().await;
    }
    drop(g);

    // Clean up stale gateway state files per profile.
    let data_dir = match paths::ensure_data_dir(app) {
        Ok(d) => d,
        Err(_) => return,
    };
    let host_home = gateway_supervisor::hermes_home_path(&data_dir);
    let profiles_dir = host_home.join("profiles");
    if let Ok(entries) = std::fs::read_dir(&profiles_dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                for name in &["gateway.lock", "gateway.pid", "gateway_state.json"] {
                    let _ = std::fs::remove_file(p.join(name));
                }
            }
        }
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
        if existing.any_running() {
            *lock = Some(existing);
            log::info!("messaging gateway already running; skip auto-start");
            return;
        }
        let _ = existing.shutdown();
    }
    drop(lock);
    match gateway_supervisor::GatewaySupervisor::spawn_all(cfg).await {
        Ok(gw) => {
            log::info!(
                "messaging gateway started (auto): {} platform(s)",
                gw.platform_count()
            );
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
    match gateway_supervisor::GatewaySupervisor::spawn_all(cfg).await {
        Ok(gw) => {
            log::info!(
                "messaging gateway started after Hermes respawn: {} platform(s)",
                gw.platform_count()
            );
            let state: tauri::State<AppState> = app.state();
            *state.gateway_supervisor.lock().await = Some(gw);
        }
        Err(e) => log::warn!("messaging gateway start after Hermes respawn failed: {e:#}"),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformStatus {
    pub platform: String,
    pub running: bool,
    pub disk_gateway_state: Option<String>,
    pub disk_exit_reason: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GatewayStatusPayload {
    pub running: bool,
    pub eligible: bool,
    /// Bundled ``hermes/gateway/run.py`` includes first-connect survival (post build_bundle).
    pub embedded_gateway_startup_survival: bool,
    /// Per-platform status.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub per_platform: Vec<PlatformStatus>,
}

#[tauri::command]
async fn cmd_gateway_status(app: tauri::AppHandle) -> Result<GatewayStatusPayload, String> {
    let data_dir = paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = gateway_supervisor::hermes_home_path(&data_dir);
    let eligible = gateway_supervisor::dotenv_suggests_messaging_gateway(&hh);

    let embedded_gateway_startup_survival = match resolve_spawn_config_for_children(&app).await {
        Ok(cfg) => gateway_supervisor::bundled_gateway_has_startup_survival(&cfg.bundle_dir),
        Err(_) => false,
    };

    let state: tauri::State<AppState> = app.state();
    let mut g = state.gateway_supervisor.lock().await;

    // Reap any exited children and collect per-platform running state.
    let mut per_platform: Vec<PlatformStatus> = Vec::new();
    let mut running = false;

    if let Some(gw) = g.as_mut() {
        // Collect running platforms before reaping.
        let running_set: HashSet<String> = gw.running_map().into_keys().collect();

        // Read per-profile state files for each known platform.
        let configured = gateway_supervisor::discover_configured_platforms(
            &gateway_supervisor::parse_dotenv_upper(&hh),
        );
        for platform in &configured {
            let profile_home = gateway_supervisor::profile_home_path(&data_dir, platform);
            let (state_str, exit_reason) =
                gateway_supervisor::read_gateway_state_snapshot(&profile_home);
            let is_running = running_set.contains(platform.as_str());
            if is_running {
                running = true;
            }
            per_platform.push(PlatformStatus {
                platform: platform.clone(),
                running: is_running,
                disk_gateway_state: state_str,
                disk_exit_reason: exit_reason,
            });
        }

        // Reap so stale children don't accumulate.
        gw.reap_exited();
    }

    Ok(GatewayStatusPayload {
        running,
        eligible,
        embedded_gateway_startup_survival,
        per_platform,
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
    // Ensure migration first.
    gateway_supervisor::ensure_migration(&cfg.data_dir)
        .map_err(|e| format!("migration failed: {e}"))?;
    let gw = gateway_supervisor::GatewaySupervisor::spawn_all(&cfg)
        .await
        .map_err(|e| e.to_string())?;
    let platform_count = gw.platform_count();
    let state: tauri::State<AppState> = app.state();
    *state.gateway_supervisor.lock().await = Some(gw);
    // Detect immediate crash (e.g. all platform children died at startup).
    tokio::time::sleep(Duration::from_secs(2)).await;
    let state: tauri::State<AppState> = app.state();
    let mut lock = state.gateway_supervisor.lock().await;
    if let Some(mut gw) = lock.take() {
        if gw.any_running() {
            *lock = Some(gw);
            log::info!(
                "messaging gateway still running after manual start ({platform_count} platform(s))"
            );
            return Ok(());
        }
        // All children exited — collect diagnostics.
        let stderr = gw.aggregate_stderr();
        let mut parts = vec!["All gateway platforms exited during startup.".to_string()];
        for (platform, status) in gw.reap_exited() {
            let profile_home = gateway_supervisor::profile_home_path(&cfg.data_dir, &platform);
            let (_, exit_reason) = gateway_supervisor::read_gateway_state_snapshot(&profile_home);
            let log_tail = gateway_supervisor::tail_gateway_log(&profile_home, 4096);
            let mut per = vec![format!("[{}] exit code {}", platform, status)];
            if let Some(r) = exit_reason.as_ref().filter(|s| !s.is_empty()) {
                per.push(format!("recorded: {r}"));
            }
            if let Some(t) = log_tail {
                per.push(format!("gateway.log (tail): {t}"));
            }
            parts.push(per.join(" | "));
        }
        if !stderr.is_empty() {
            const MAX: usize = 2000;
            let capped: String = if stderr.chars().count() > MAX {
                let trunc: String = stderr.chars().take(MAX).collect();
                format!("{trunc}…")
            } else {
                stderr.to_string()
            };
            parts.push(format!("stderr (captured): {capped}"));
        }
        parts.push(
            "If this persists: run python/build_bundle.ps1 so hermes-home picks up the latest gateway (first-connect retry fix), then relaunch Kabuqina."
                .into(),
        );
        if !gateway_supervisor::bundled_gateway_has_startup_survival(&cfg.bundle_dir) {
            parts.push(
                "Detected: the embedded runtime's hermes/gateway/run.py does NOT include the first-connect survival patch — your bundle is almost certainly stale. Close Kabuqina, run python/build_bundle.ps1 from the repo root, then relaunch (a dev build must use the refreshed python/dist/runtime)."
                    .into(),
            );
        }
        return Err(parts.join(" "));
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

    // 2a. Start Edge CDP browser instance (Windows only) for browser tool.
    //     Edge is pre-installed on Windows; this replaces the need for Node.js
    //     Playwright or a Camofox server.
    {
        let state: tauri::State<AppState> = app.state();
        let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| anyhow::anyhow!(e))?;
        if let Err(e) = state.edge_browser.start(&data_dir) {
            log::warn!("Edge browser start skipped (browser tool will be unavailable): {e}");
        }
    }

    // 2. Stand up the loopback bridge (secret handshake + shell approval + desktop delivery).
    let desktop_q = {
        let state: tauri::State<AppState> = app.state();
        state.desktop_messages.clone()
    };
    let bridge = bridge::spawn(app.clone(), desktop_q).await?;
    {
        let state: tauri::State<AppState> = app.state();
        *state.bridge_addr.lock().await = Some(bridge.addr);
        *state.desk_auth_token.lock().await = Some(bridge.desk_auth_token.clone());
        *state.bridge_secret_url.lock().await = Some(bridge.secret_url.clone());
        *state.bridge_approval_url.lock().await = Some(bridge.approval_url.clone());
        *state.bridge_desktop_delivery_url.lock().await =
            Some(bridge.desktop_delivery_url.clone());
    }

    // 3. Spawn the Python child (Hermes web_server / desktop_entrypoint).
    //    Errors here are logged but do NOT block the window from showing,
    //    so the user can see the shell UI and diagnose startup issues.
    let hermes_ok = async {
        let spawn_cfg = resolve_spawn_config_for_children(&app)
            .await
            .map_err(|e| anyhow::anyhow!(e))?;
        let supervisor = python_supervisor::Supervisor::spawn(spawn_cfg.clone()).await?;

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

    // 5. Register global screenshot shortcut (Ctrl+Alt+A).
    capture::register_global_shortcut(&app);

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
    let supervisor = python_supervisor::Supervisor::spawn(spawn_cfg.clone())
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
            u.query_pairs_mut().append_pair("hermesdesk_lang", loc);
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
    app.opener()
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
    let port =
        state.hermes_port.lock().await.ok_or_else(|| {
            "Hermes is not ready yet. Wait a few seconds and try again.".to_string()
        })?;
    open_hermes_dashboard_in_browser(&app, port, shell_locale, path)
}

/// Return pending desktop delivery messages (from Python cron/send_message)
/// and clear the buffer.  The frontend polls this periodically.
#[tauri::command]
async fn cmd_desktop_messages(
    app: tauri::AppHandle,
) -> Result<Vec<bridge::DesktopMessage>, String> {
    let state: tauri::State<AppState> = app.state();
    let mut msgs = state.desktop_messages.lock().await;
    let drained = std::mem::take(&mut *msgs);
    Ok(drained)
}
