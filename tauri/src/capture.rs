//! Screenshot capture — xcap wrapper + overlay window lifecycle.
//!
//! Provides Tauri commands for region/fullscreen/window capture and
//! manages the transparent capture-overlay webview window.

use base64::Engine;
use std::path::PathBuf;
use tauri::{Emitter, Manager};

type ImageBuf = image::ImageBuffer<image::Rgba<u8>, Vec<u8>>;

/// Payload emitted to the main window when capture is done.
#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct CaptureDonePayload {
    path: String,
    name: String,
    mime: String,
    data: String, // base64-encoded PNG bytes
}

/// Save a capture to `workspace/captures/<uuid>.png` and return the path.
fn save_capture(app: &tauri::AppHandle, png_bytes: &[u8]) -> Result<PathBuf, String> {
    let workspace = crate::paths::ensure_workspace(app).map_err(|e| e.to_string())?;
    let captures_dir = workspace.join("captures");
    std::fs::create_dir_all(&captures_dir)
        .map_err(|e| format!("create captures dir: {e}"))?;
    let filename = format!("{}.png", uuid::Uuid::new_v4());
    let dest = captures_dir.join(&filename);
    std::fs::write(&dest, png_bytes).map_err(|e| format!("write capture: {e}"))?;
    Ok(dest)
}

/// Encode an RGBA image buffer as PNG bytes.
fn encode_png(img: &ImageBuf) -> Result<Vec<u8>, String> {
    let mut cursor = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(img.clone())
        .write_to(&mut cursor, image::ImageFormat::Png)
        .map_err(|e| format!("encode png: {e}"))?;
    Ok(cursor.into_inner())
}

/// Finish a capture: encode, save, emit event, hide overlay.
fn finish_capture(
    app: &tauri::AppHandle,
    img: &ImageBuf,
) -> Result<String, String> {
    let png_bytes = encode_png(img)?;
    let path = save_capture(app, &png_bytes)?;
    let path_str = path.to_string_lossy().to_string();
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "capture.png".into());
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png_bytes);

    let _ = app
        .get_webview_window("main")
        .and_then(|w| {
            w.emit(
                "capture-done",
                CaptureDonePayload {
                    path: path_str.clone(),
                    name,
                    mime: "image/png".into(),
                    data: b64,
                },
            )
            .ok()
        });

    if let Some(w) = app.get_webview_window("capture-overlay") {
        let _ = w.hide();
    }

    Ok(path_str)
}

#[tauri::command]
pub async fn cmd_capture_region(
    app: tauri::AppHandle,
    x: i32,
    y: i32,
    w: u32,
    h: u32,
) -> Result<String, String> {
    let monitors =
        xcap::Monitor::all().map_err(|e| format!("enumerate monitors: {e}"))?;
    if monitors.is_empty() {
        return Err("no monitors found".into());
    }

    // Find the monitor containing the selection rectangle centre point.
    let cx = x + (w as i32) / 2;
    let cy = y + (h as i32) / 2;
    let monitor = monitors
        .iter()
        .find(|m| {
            let mx = m.x();
            let my = m.y();
            cx >= mx
                && cy >= my
                && cx < mx + (m.width() as i32)
                && cy < my + (m.height() as i32)
        })
        .unwrap_or(&monitors[0]);

    let full: ImageBuf = monitor
        .capture_image()
        .map_err(|e| format!("capture screen: {e}"))?;

    let img_w = full.width();
    let img_h = full.height();
    let mon_x = monitor.x();
    let mon_y = monitor.y();
    let crop_x = ((x - mon_x).max(0) as u32).min(img_w.saturating_sub(1));
    let crop_y = ((y - mon_y).max(0) as u32).min(img_h.saturating_sub(1));
    let crop_w = w.min(img_w.saturating_sub(crop_x));
    let crop_h = h.min(img_h.saturating_sub(crop_y));

    if crop_w == 0 || crop_h == 0 {
        return Err("selection is outside visible area".into());
    }

    let cropped = image::imageops::crop_imm(&full, crop_x, crop_y, crop_w, crop_h).to_image();
    finish_capture(&app, &cropped)
}

#[tauri::command]
pub async fn cmd_capture_fullscreen(app: tauri::AppHandle) -> Result<String, String> {
    let monitors =
        xcap::Monitor::all().map_err(|e| format!("enumerate monitors: {e}"))?;
    if monitors.is_empty() {
        return Err("no monitors found".into());
    }

    let monitor = &monitors[0];
    let full: ImageBuf = monitor
        .capture_image()
        .map_err(|e| format!("capture screen: {e}"))?;

    finish_capture(&app, &full)
}

/// Show the transparent overlay window for region selection.
#[tauri::command]
pub async fn cmd_show_capture_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let workspace = crate::paths::ensure_workspace(&app).map_err(|e| e.to_string())?;
    let _ = std::fs::create_dir_all(workspace.join("captures"));

    if let Some(w) = app.get_webview_window("capture-overlay") {
        let _ = w.show();
        let _ = w.set_focus();
        return Ok(());
    }

    use tauri::WebviewWindowBuilder;
    let _w = WebviewWindowBuilder::new(
        &app,
        "capture-overlay",
        tauri::WebviewUrl::App("index.html".into()),
    )
    .title("")
    .decorations(false)
    .always_on_top(true)
    .transparent(true)
    .visible(true)
    .resizable(false)
    .fullscreen(true)
    .build()
    .map_err(|e| format!("create overlay window: {e}"))?;

    Ok(())
}

#[tauri::command]
pub async fn cmd_hide_capture_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("capture-overlay") {
        let _ = w.hide();
    }
    Ok(())
}

/// Register the global shortcut (Ctrl+Alt+A) that shows the capture overlay.
/// Call this after the app is set up (plugin already registered on the Builder).
pub fn register_global_shortcut(app: &tauri::AppHandle) {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

    let app_handle = app.clone();
    let shortcut_str = "Ctrl+Alt+A";

    // `on_shortcut` registers the hotkey and attaches the handler; do not call
    // `register` separately or the OS returns "already registered".
    match app.global_shortcut().on_shortcut(shortcut_str, move |_app, _shortcut, event| {
        if !matches!(event.state, ShortcutState::Pressed) {
            return;
        }
        let h = app_handle.clone();
        tauri::async_runtime::spawn(async move {
            if let Err(e) = cmd_show_capture_overlay(h).await {
                log::error!("show capture overlay: {e}");
            }
        });
    }) {
        Ok(_) => log::info!("global shortcut '{}' registered", shortcut_str),
        Err(e) => log::error!("register global shortcut '{}' failed: {e}", shortcut_str),
    }
}
