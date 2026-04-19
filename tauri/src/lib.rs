//! HermesDesk Tauri shell.
//!
//! Responsibilities:
//!  - Spawn and supervise the embedded Python process (`python_supervisor`)
//!  - Expose a tiny loopback HTTP server for secret handshake +
//!    shell-approval bridge (`bridge`)
//!  - Own the Windows Credential Manager-backed key vault (`secrets`)
//!  - Own the system tray + main window
//!  - Wait for Python's port handshake, then point the WebView at it
//!
//! All business logic lives in Python. This crate is a thin process
//! supervisor + secret/safety boundary.

mod bridge;
mod paths;
mod python_supervisor;
mod secrets;
mod tray;

use std::sync::Arc;
use tauri::{Manager, RunEvent};
use tokio::sync::Mutex;

pub struct AppState {
    pub supervisor: Arc<Mutex<Option<python_supervisor::Supervisor>>>,
    pub bridge_addr: Arc<Mutex<Option<std::net::SocketAddr>>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let supervisor = Arc::new(Mutex::new(None));
    let bridge_addr = Arc::new(Mutex::new(None));

    let state = AppState {
        supervisor: supervisor.clone(),
        bridge_addr: bridge_addr.clone(),
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
            secrets::cmd_clear_secret,
            python_supervisor::cmd_python_status,
            paths::cmd_workspace_path,
            paths::cmd_open_workspace,
            paths::cmd_get_power_user,
            paths::cmd_set_power_user,
            paths::cmd_set_personality,
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
                let state: tauri::State<AppState> = app.state();
                if let Ok(mut sup) = state.supervisor.try_lock() {
                    if let Some(s) = sup.take() {
                        let _ = s.shutdown();
                    }
                }
            }
        });
}

async fn bootstrap(app: tauri::AppHandle) -> anyhow::Result<()> {
    // 1. Make sure the workspace folder exists.
    let workspace = paths::ensure_workspace(&app)?;
    let bundle_dir = paths::resolve_runtime_dir(&app)?;
    let data_dir = paths::ensure_data_dir(&app)?;

    // 2. Stand up the loopback bridge (secret handshake + shell approval).
    let bridge = bridge::spawn(app.clone()).await?;
    {
        let state: tauri::State<AppState> = app.state();
        *state.bridge_addr.lock().await = Some(bridge.addr);
    }

    // 3. Spawn the Python child.
    let supervisor = python_supervisor::Supervisor::spawn(
        python_supervisor::SpawnConfig {
            bundle_dir,
            data_dir,
            workspace,
            secret_url: bridge.secret_url.clone(),
            approval_url: bridge.approval_url.clone(),
            provider: secrets::current_provider(&app).unwrap_or_else(|| "openrouter".into()),
            llm_host: secrets::current_host(&app).unwrap_or_else(|| "openrouter.ai".into()),
            power_user: paths::is_power_user(&app),
        },
    )
    .await?;

    let port = supervisor.wait_for_port().await?;
    log::info!("python ready on port {port}");

    {
        let state: tauri::State<AppState> = app.state();
        *state.supervisor.lock().await = Some(supervisor);
    }

    // 4. Point the main window at Python and reveal it.
    if let Some(w) = app.get_webview_window("main") {
        let url = format!("http://127.0.0.1:{port}/");
        log::info!("loading {url}");
        let _ = w.eval(&format!("window.location.replace({:?})", url));
        let _ = w.show();
        let _ = w.set_focus();
    }
    Ok(())
}
