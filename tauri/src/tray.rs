//! System tray icon + minimal menu.

use anyhow::Result;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    App, Manager,
};

pub fn install(app: &mut App) -> Result<()> {
    let handle = app.handle().clone();

    let show = MenuItem::with_id(&handle, "show", "Open HermesDesk", true, None::<&str>)?;
    let workspace = MenuItem::with_id(&handle, "workspace", "Open workspace folder", true, None::<&str>)?;
    let updates = MenuItem::with_id(&handle, "updates", "Check for updates", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(&handle)?;
    let quit = MenuItem::with_id(&handle, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(&handle, &[&show, &workspace, &updates, &sep, &quit])?;

    let _ = TrayIconBuilder::with_id("hermesdesk-tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "show" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            "workspace" => {
                let _ = crate::paths::cmd_open_workspace(app.clone());
            }
            "updates" => {
                #[cfg(desktop)]
                tauri::async_runtime::spawn({
                    let app = app.clone();
                    async move {
                        use tauri_plugin_updater::UpdaterExt;
                        if let Ok(updater) = app.updater() {
                            let _ = updater.check().await;
                        }
                    }
                });
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, .. } = event {
                let app = tray.app_handle();
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
        })
        .build(app)?;

    Ok(())
}
