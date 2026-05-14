//! Lightweight companion window controls.

use tauri::{Manager, WebviewWindowBuilder};

const COMPANION_LABEL: &str = "companion";

pub async fn show_companion(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(COMPANION_LABEL) {
        let _ = w.show();
        let _ = w.set_focus();
        if let Some(main) = app.get_webview_window("main") {
            let _ = main.hide();
        }
        return Ok(());
    }

    let companion = WebviewWindowBuilder::new(
        &app,
        COMPANION_LABEL,
        tauri::WebviewUrl::App("index.html".into()),
    )
    .title("Kabuqina")
    .decorations(false)
    .always_on_top(true)
    .transparent(true)
    .visible(true)
    .resizable(false)
    .inner_size(220.0, 88.0)
    .min_inner_size(220.0, 88.0)
    .skip_taskbar(true)
    .build()
    .map_err(|e| format!("create companion window: {e}"))?;

    let _ = companion.set_focus();
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.hide();
    }

    Ok(())
}

pub fn focus_main_window(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    if let Some(w) = app.get_webview_window(COMPANION_LABEL) {
        let _ = w.hide();
    }
}

#[tauri::command]
pub async fn cmd_show_companion(app: tauri::AppHandle) -> Result<(), String> {
    show_companion(app).await
}

#[tauri::command]
pub async fn cmd_hide_companion(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(COMPANION_LABEL) {
        let _ = w.hide();
    }
    Ok(())
}

#[tauri::command]
pub async fn cmd_focus_main_window(app: tauri::AppHandle) -> Result<(), String> {
    focus_main_window(&app);
    Ok(())
}
