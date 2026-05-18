//! Short-lived bundled Python process for QQ Bot scan-to-configure QR login (`qqbot_qr_worker.py`).

use serde_json::{json, Value};
use std::path::PathBuf;
use tauri::AppHandle;
use tokio::io::{AsyncBufReadExt, BufReader};

const PROGRESS_FILE: &str = "qqbot_qr_progress.json";
const RESULT_FILE: &str = "qqbot_qr_result.json";

fn progress_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(crate::paths::ensure_data_dir(app)
        .map_err(|e| e.to_string())?
        .join(PROGRESS_FILE))
}

fn result_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(crate::paths::ensure_data_dir(app)
        .map_err(|e| e.to_string())?
        .join(RESULT_FILE))
}

async fn read_json_file(path: &PathBuf) -> Option<Value> {
    let s = tokio::fs::read_to_string(path).await.ok()?;
    serde_json::from_str(&s).ok()
}

async fn log_pipe(tag: &'static str, r: impl tokio::io::AsyncRead + Unpin + Send + 'static) {
    let mut lines = BufReader::new(r).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        log::info!("{tag}: {line}");
    }
}

/// Start `python.exe qqbot_qr_worker.py` (CREATE_NO_WINDOW on Windows). Clears prior progress/result.
#[tauri::command]
pub async fn cmd_qqbot_qr_start(
    app: AppHandle,
    state: tauri::State<'_, crate::AppState>,
) -> Result<(), String> {
    let _ = tokio::fs::remove_file(progress_path(&app)?).await;
    let _ = tokio::fs::remove_file(result_path(&app)?).await;

    let bundle = crate::paths::resolve_runtime_dir(&app).map_err(|e| e.to_string())?;
    let worker = bundle.join("qqbot_qr_worker.py");
    if !worker.exists() {
        return Err(
            "qqbot_qr_worker.py is missing from the runtime bundle. Rebuild the Python bundle."
                .into(),
        );
    }
    let py = bundle.join("python").join("python.exe");
    if !py.exists() {
        return Err("bundled python.exe not found".into());
    }

    let mut slot = state.qqbot_qr_child.lock().await;
    if let Some(mut c) = slot.take() {
        let _ = c.start_kill();
    }

    let workspace = crate::paths::ensure_workspace(&app).map_err(|e| e.to_string())?;
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;

    let mut cmd = tokio::process::Command::new(&py);
    cmd.arg(&worker)
        .current_dir(&bundle)
        .env("HERMESDESK_BUNDLE_DIR", &bundle)
        .env("HERMESDESK_DATA_DIR", &data_dir)
        .env("HERMESDESK_WORKSPACE", &workspace)
        .env_remove("HTTP_PROXY")
        .env_remove("http_proxy")
        .env_remove("HTTPS_PROXY")
        .env_remove("https_proxy")
        .env_remove("ALL_PROXY")
        .env_remove("all_proxy")
        .env_remove("NO_PROXY")
        .env_remove("no_proxy")
        .env_remove("PYTHONPATH")
        .env("NO_PROXY", "127.0.0.1,localhost,::1")
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    if let Some(out) = child.stdout.take() {
        tokio::spawn(log_pipe("qqbot_qr.out", out));
    }
    if let Some(err) = child.stderr.take() {
        tokio::spawn(log_pipe("qqbot_qr.err", err));
    }

    *slot = Some(child);
    Ok(())
}

/// Poll worker state: `running`, optional `progress` / `result` JSON from the data dir.
#[tauri::command]
pub async fn cmd_qqbot_qr_status(
    app: AppHandle,
    state: tauri::State<'_, crate::AppState>,
) -> Result<Value, String> {
    let pp = progress_path(&app)?;
    let rp = result_path(&app)?;

    let mut slot = state.qqbot_qr_child.lock().await;
    let mut running = false;
    if let Some(child) = slot.as_mut() {
        match child.try_wait() {
            Ok(None) => running = true,
            Ok(Some(_status)) => {
                let _ = slot.take();
            }
            Err(e) => return Err(e.to_string()),
        }
    }

    let progress = read_json_file(&pp).await;
    let result = read_json_file(&rp).await;

    Ok(json!({
        "running": running,
        "progress": progress,
        "result": result,
    }))
}

#[tauri::command]
pub async fn cmd_qqbot_qr_cancel(state: tauri::State<'_, crate::AppState>) -> Result<(), String> {
    let mut slot = state.qqbot_qr_child.lock().await;
    if let Some(mut c) = slot.take() {
        let _ = c.start_kill();
    }
    Ok(())
}
