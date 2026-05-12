//! Loopback HTTP/1.1 bridge for the Python child.
//!
//! Endpoints, all protected by per-launch random tokens in the path:
//!
//!   GET  /secret/<token>              -> body = the API key text/plain (one shot)
//!   POST /approval/<token>            -> three dialog types: shell / messaging / cron
//!   POST /desktop-delivery/<token>    -> receive desktop delivery (cron / send_message to "desktop")
//!   GET  /shell-chat/<token>          -> redirect Tauri webview to shell /chat
//!
//! Bound to 127.0.0.1 only. Tokens never leave this process except via
//! the env vars passed to the Python child.
//!
//! We hand-roll a tiny HTTP/1.1 parser (instead of pulling in hyper) for two
//! reasons: (a) the surface is three routes that we already know exhaust the
//! incoming traffic, and (b) keeping the runtime stack bare-tokio avoids a
//! whole class of "future not polled" bugs that bit us when stacking hyper
//! on top of `tauri::async_runtime`.

use anyhow::Result;
use rand::RngCore;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{oneshot, Mutex};

/// "Back to shell chat" redirect must use the same `http` vs `https` scheme as
/// the main webview's `tauri.localhost` origin.
fn shell_chat_redirect_target(app: &AppHandle) -> String {
    if tauri::is_dev() {
        return "http://localhost:5173/chat".to_string();
    }
    let use_https = app
        .config()
        .app
        .windows
        .iter()
        .find(|w| w.label == "main")
        .map(|w| w.use_https_scheme)
        .unwrap_or(false);
    let scheme = if use_https { "https" } else { "http" };
    format!("{scheme}://tauri.localhost/chat")
}

pub struct Bridge {
    pub addr: SocketAddr,
    pub secret_url: String,
    pub approval_url: String,
    pub desktop_delivery_url: String,
    /// Shared with Python `HERMESDESK_BRIDGE_SECRET` for `X-HermesDesk-Auth` on Hermes `/api/*`.
    pub desk_auth_token: String,
}

#[derive(Clone)]
struct State {
    secret_token: String,
    approval_token: String,
    desktop_delivery_token: String,
    /// Same as ``HERMESDESK_BRIDGE_SECRET`` / ``X-HermesDesk-Auth``
    desk_auth_token: String,
    app: AppHandle,
    /// Pending desktop delivery messages (frontend polls via `cmd_desktop_messages`).
    desktop_messages: Arc<Mutex<Vec<DesktopMessage>>>,
}

#[derive(Clone, serde::Serialize)]
pub struct DesktopMessage {
    pub title: String,
    pub message: String,
}

/// Start the bridge. ``desktop_messages`` MUST be the same ``Arc`` as
/// ``AppState.desktop_messages`` so POST /desktop-delivery and
/// ``cmd_desktop_messages`` share one queue — otherwise cron delivery logs
/// "ok" while the frontend always drains an empty Vec.
pub async fn spawn(app: AppHandle, desktop_messages: Arc<Mutex<Vec<DesktopMessage>>>) -> Result<Bridge> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let secret_token = random_token();
    let approval_token = random_token();
    let desktop_delivery_token = random_token();
    let desk_auth_token = random_token();

    let state = Arc::new(State {
        secret_token: secret_token.clone(),
        approval_token: approval_token.clone(),
        desktop_delivery_token: desktop_delivery_token.clone(),
        desk_auth_token: desk_auth_token.clone(),
        app,
        desktop_messages,
    });

    let secret_url = format!("http://{addr}/secret/{secret_token}");
    let approval_url = format!("http://{addr}/approval/{approval_token}");
    let desktop_delivery_url = format!("http://{addr}/desktop-delivery/{desktop_delivery_token}");

    tauri::async_runtime::spawn(serve(listener, state));

    Ok(Bridge {
        addr,
        secret_url,
        approval_url,
        desktop_delivery_url,
        desk_auth_token,
    })
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

async fn serve(listener: TcpListener, state: Arc<State>) {
    log::info!(
        "bridge serve loop started on {:?}",
        listener.local_addr().ok()
    );
    loop {
        let (stream, peer) = match listener.accept().await {
            Ok(p) => p,
            Err(e) => {
                log::warn!("bridge accept: {e}");
                continue;
            }
        };
        log::info!("bridge accepted conn from {peer}");
        let st = state.clone();
        tauri::async_runtime::spawn(async move {
            if let Err(e) = handle_conn(stream, st).await {
                log::warn!("bridge conn error: {e}");
            }
        });
    }
}

/// Parse a single HTTP/1.1 request, dispatch it, write a single response,
/// then close. We do not implement keep-alive.
async fn handle_conn(mut stream: TcpStream, st: Arc<State>) -> std::io::Result<()> {
    let mut buf = Vec::with_capacity(2048);
    let mut tmp = [0u8; 1024];
    let header_end;
    loop {
        let n = match tokio::time::timeout(Duration::from_secs(5), stream.read(&mut tmp)).await {
            Ok(Ok(0)) => return Ok(()),
            Ok(Ok(n)) => n,
            Ok(Err(e)) => return Err(e),
            Err(_) => return Ok(()),
        };
        buf.extend_from_slice(&tmp[..n]);
        if let Some(idx) = find_double_crlf(&buf) {
            header_end = idx + 4;
            break;
        }
        if buf.len() > 16 * 1024 {
            return write_status(&mut stream, 413, "Payload Too Large").await;
        }
    }

    let head = match std::str::from_utf8(&buf[..header_end]) {
        Ok(s) => s,
        Err(_) => return write_status(&mut stream, 400, "Bad Request").await,
    };
    let mut lines = head.split("\r\n");
    let req_line = lines.next().unwrap_or("");
    let mut parts = req_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");

    // Read Content-Length.
    let mut content_length: usize = 0;
    for line in lines {
        if line.is_empty() {
            break;
        }
        if let Some((k, v)) = line.split_once(':') {
            if k.eq_ignore_ascii_case("content-length") {
                content_length = v.trim().parse().unwrap_or(0);
            }
        }
    }

    log::info!("bridge req: {method} {path}");

    // GET /shell-chat/<token>
    if method == "GET" && path.starts_with("/shell-chat/") {
        let tok = path
            .trim_start_matches("/shell-chat/")
            .trim_start_matches('/');
        if !tok.is_empty() && tok == st.desk_auth_token {
            let target = shell_chat_redirect_target(&st.app);
            return write_redirect(&mut stream, 302, &target).await;
        }
        return write_status(&mut stream, 403, "Forbidden").await;
    }

    // GET /secret/<token>
    if method == "GET" && path == format!("/secret/{}", st.secret_token) {
        let body = crate::secrets::read_current_secret(&st.app).unwrap_or_default();
        return write_response(
            &mut stream,
            200,
            "OK",
            "text/plain; charset=utf-8",
            body.into_bytes(),
        )
        .await;
    }

    // POST /approval/<token>  — shell / messaging / cron
    if method == "POST" && path == format!("/approval/{}", st.approval_token) {
        return handle_approval(&mut stream, &st, &buf, header_end, content_length).await;
    }

    // POST /desktop-delivery/<token>
    if method == "POST" && path == format!("/desktop-delivery/{}", st.desktop_delivery_token) {
        return handle_desktop_delivery(&mut stream, &st, &buf, header_end, content_length).await;
    }

    write_status(&mut stream, 404, "Not Found").await
}

// ------------------------------------------------------------------
// Approval dispatcher (shell / messaging / cron)
// ------------------------------------------------------------------

async fn handle_approval(
    stream: &mut TcpStream,
    st: &State,
    buf: &[u8],
    header_end: usize,
    content_length: usize,
) -> std::io::Result<()> {
    let body = read_body(stream, buf, header_end, content_length).await?;
    let payload: serde_json::Value =
        serde_json::from_slice(&body).unwrap_or(serde_json::json!({}));

    let approval_type = payload
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("shell");

    let allowed = match approval_type {
        "messaging" => {
            let target = payload
                .get("target")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let content_preview = payload
                .get("content_preview")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            ask_user_to_approve_messaging(&st.app, &target, &content_preview).await
        }
        "cron" => {
            let action = payload
                .get("action")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let schedule = payload
                .get("schedule")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let description = payload
                .get("description")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let delivery_target = payload
                .get("delivery_target")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            ask_user_to_approve_cron(&st.app, &action, &schedule, &description, &delivery_target)
                .await
        }
        _ => {
            // Legacy shell command approval (and any unknown type defaults to shell)
            let cmd = payload
                .get("command")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let cwd = payload
                .get("cwd")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let reason = payload
                .get("reason")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            ask_user_to_approve(&st.app, &cmd, &cwd, &reason).await
        }
    };

    let resp_body = serde_json::json!({"allowed": allowed}).to_string();
    write_response(
        stream,
        200,
        "OK",
        "application/json",
        resp_body.into_bytes(),
    )
    .await
}

// ------------------------------------------------------------------
// Desktop delivery handler
// ------------------------------------------------------------------

async fn handle_desktop_delivery(
    stream: &mut TcpStream,
    st: &State,
    buf: &[u8],
    header_end: usize,
    content_length: usize,
) -> std::io::Result<()> {
    let body = read_body(stream, buf, header_end, content_length).await?;
    let payload: serde_json::Value =
        serde_json::from_slice(&body).unwrap_or(serde_json::json!({}));

    let title = payload
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("Kabuqina")
        .to_string();
    let message = payload
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    log::info!("desktop delivery: title={title:?} len={}", message.len());

    // Q1 part A: native Windows toast notification. Body is truncated to a
    // reasonable preview length (the full content lives in chat-stream).
    {
        use tauri_plugin_notification::NotificationExt;
        let preview = truncate_for_toast(&message, 200);
        if let Err(e) = st
            .app
            .notification()
            .builder()
            .title(&title)
            .body(&preview)
            .show()
        {
            log::warn!("desktop delivery: toast notification failed: {e}");
        }
    }

    // Q1 part B: store so the chat stream can pick it up via polling.
    {
        let mut msgs = st.desktop_messages.lock().await;
        msgs.push(DesktopMessage {
            title: title.clone(),
            message: message.clone(),
        });
    }

    if let Err(e) = st.app.emit(
        "desktop-delivery",
        DesktopMessage {
            title: title.clone(),
            message: message.clone(),
        },
    ) {
        log::warn!("desktop delivery: frontend event failed: {e}");
    }

    let resp_body = serde_json::json!({"ok": true}).to_string();
    write_response(
        stream,
        200,
        "OK",
        "application/json",
        resp_body.into_bytes(),
    )
    .await
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

async fn read_body(
    stream: &mut TcpStream,
    buf: &[u8],
    header_end: usize,
    content_length: usize,
) -> std::io::Result<Vec<u8>> {
    let mut body: Vec<u8> = buf[header_end..].to_vec();
    while body.len() < content_length {
        let need = content_length - body.len();
        let mut tmp = vec![0u8; need.min(4096)];
        let n = match tokio::time::timeout(Duration::from_secs(30), stream.read(&mut tmp)).await {
            Ok(Ok(0)) => break,
            Ok(Ok(n)) => n,
            Ok(Err(e)) => return Err(e),
            Err(_) => {
                let _ = write_status(stream, 408, "Request Timeout").await;
                return Ok(Vec::new());
            }
        };
        body.extend_from_slice(&tmp[..n]);
    }
    Ok(body)
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

/// Truncate a string at a UTF-8 char boundary so toast bodies stay short.
fn truncate_for_toast(s: &str, max_chars: usize) -> String {
    let mut count = 0;
    let mut end = s.len();
    for (i, _) in s.char_indices() {
        if count >= max_chars {
            end = i;
            break;
        }
        count += 1;
    }
    if end < s.len() {
        let mut out = s[..end].to_string();
        out.push('…');
        out
    } else {
        s.to_string()
    }
}

async fn write_status(stream: &mut TcpStream, code: u16, reason: &str) -> std::io::Result<()> {
    write_response(stream, code, reason, "text/plain", Vec::new()).await
}

async fn write_redirect(stream: &mut TcpStream, code: u16, location: &str) -> std::io::Result<()> {
    let head = format!(
        "HTTP/1.1 {code} Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(head.as_bytes()).await?;
    stream.flush().await?;
    let _ = stream.shutdown().await;
    log::info!("bridge redirect {code} -> {location}");
    Ok(())
}

async fn write_response(
    stream: &mut TcpStream,
    code: u16,
    reason: &str,
    content_type: &str,
    body: Vec<u8>,
) -> std::io::Result<()> {
    let head = format!(
        "HTTP/1.1 {code} {reason}\r\n\
         Content-Type: {content_type}\r\n\
         Content-Length: {}\r\n\
         Connection: close\r\n\
         \r\n",
        body.len()
    );
    stream.write_all(head.as_bytes()).await?;
    if !body.is_empty() {
        stream.write_all(&body).await?;
    }
    stream.flush().await?;
    let _ = stream.shutdown().await;
    log::info!("bridge req done: {code}");
    Ok(())
}

// ------------------------------------------------------------------
// Approval dialogs
// ------------------------------------------------------------------

async fn ask_user_to_approve(app: &AppHandle, cmd: &str, cwd: &str, reason: &str) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
    let (tx, rx) = oneshot::channel();
    let body = if reason.is_empty() {
        format!("Command:\n{cmd}\n\nFolder:\n{cwd}")
    } else {
        format!("{reason}\n\nCommand:\n{cmd}\n\nFolder:\n{cwd}")
    };
    let title = "Kabuqina wants to run a command".to_string();
    let app_clone = app.clone();
    tauri::async_runtime::spawn(async move {
        let dlg = app_clone.dialog().message(body).title(title).buttons(
            MessageDialogButtons::OkCancelCustom("Allow this once".into(), "Deny".into()),
        );
        dlg.show(move |allowed| {
            let _ = tx.send(allowed);
        });
    });
    rx.await.unwrap_or(false)
}

async fn ask_user_to_approve_messaging(
    app: &AppHandle,
    target: &str,
    content_preview: &str,
) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
    let (tx, rx) = oneshot::channel();
    let preview_display = if content_preview.len() > 300 {
        format!("{}…", &content_preview[..300])
    } else {
        content_preview.to_string()
    };
    let body = format!(
        "AI wants to send a message:\n\nTarget: {target}\n\nContent preview:\n{preview_display}"
    );
    let title = "Kabuqina wants to send a message".to_string();
    let app_clone = app.clone();
    tauri::async_runtime::spawn(async move {
        let dlg = app_clone.dialog().message(body).title(title).buttons(
            MessageDialogButtons::OkCancelCustom("Allow once".into(), "Deny".into()),
        );
        dlg.show(move |allowed| {
            let _ = tx.send(allowed);
        });
    });
    rx.await.unwrap_or(false)
}

async fn ask_user_to_approve_cron(
    app: &AppHandle,
    _action: &str,
    schedule: &str,
    description: &str,
    delivery_target: &str,
) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
    let (tx, rx) = oneshot::channel();
    let mut body = format!("AI wants to schedule a recurring task:\n\n");
    if !description.is_empty() {
        body.push_str(&format!("Task: {description}\n"));
    }
    body.push_str(&format!("Trigger: {schedule}\n"));
    if !delivery_target.is_empty() && delivery_target != "desktop" {
        body.push_str(&format!("Deliver to: {delivery_target}\n"));
    } else if delivery_target == "desktop" {
        body.push_str("Deliver to: Desktop (local notification)\n");
    }
    body.push_str("\nYou can manage or delete this task anytime in Settings → Scheduled Tasks.");
    let title = "Kabuqina wants to schedule a task".to_string();
    let app_clone = app.clone();
    tauri::async_runtime::spawn(async move {
        let dlg = app_clone.dialog().message(body).title(title).buttons(
            MessageDialogButtons::OkCancelCustom("Allow".into(), "Deny".into()),
        );
        dlg.show(move |allowed| {
            let _ = tx.send(allowed);
        });
    });
    rx.await.unwrap_or(false)
}
