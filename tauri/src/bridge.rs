//! Loopback HTTP/1.1 bridge for the Python child.
//!
//! Two endpoints, both protected by a per-launch random token in the path:
//!
//!   GET  /secret/<token>     -> body = the API key text/plain (one shot)
//!   POST /approval/<token>   -> body = JSON { command, cwd, reason }
//!                               -> response = JSON { allowed: bool }
//!
//! Bound to 127.0.0.1 only. The tokens never leave this process except via
//! the env vars passed to the Python child.
//!
//! We hand-roll a tiny HTTP/1.1 parser (instead of pulling in hyper) for two
//! reasons: (a) the surface is two routes that we already know exhaust the
//! incoming traffic, and (b) keeping the runtime stack bare-tokio avoids a
//! whole class of "future not polled" bugs that bit us when stacking hyper
//! on top of `tauri::async_runtime`.

use anyhow::Result;
use rand::RngCore;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tauri::AppHandle;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

pub struct Bridge {
    pub addr: SocketAddr,
    pub secret_url: String,
    pub approval_url: String,
}

#[derive(Clone)]
struct State {
    secret_token: String,
    approval_token: String,
    app: AppHandle,
}

pub async fn spawn(app: AppHandle) -> Result<Bridge> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let secret_token = random_token();
    let approval_token = random_token();
    let state = Arc::new(State {
        secret_token: secret_token.clone(),
        approval_token: approval_token.clone(),
        app,
    });

    let secret_url = format!("http://{addr}/secret/{secret_token}");
    let approval_url = format!("http://{addr}/approval/{approval_token}");

    tauri::async_runtime::spawn(serve(listener, state));

    Ok(Bridge { addr, secret_url, approval_url })
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

async fn serve(listener: TcpListener, state: Arc<State>) {
    log::info!("bridge serve loop started on {:?}", listener.local_addr().ok());
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
    // Read request bytes until end-of-headers (blank line). 16 KiB is plenty
    // for our two routes (no big bodies on the secret GET).
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

    // Find Content-Length, if any.
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

    // GET /secret/<token>
    if method == "GET" && path == format!("/secret/{}", st.secret_token) {
        let body = crate::secrets::read_current_secret(&st.app).unwrap_or_default();
        return write_response(&mut stream, 200, "OK", "text/plain; charset=utf-8", body.into_bytes()).await;
    }

    // POST /approval/<token>
    if method == "POST" && path == format!("/approval/{}", st.approval_token) {
        // Read remainder of body up to content_length (we may already have part of it).
        let mut body: Vec<u8> = buf[header_end..].to_vec();
        while body.len() < content_length {
            let need = content_length - body.len();
            let mut tmp = vec![0u8; need.min(4096)];
            let n = match tokio::time::timeout(Duration::from_secs(30), stream.read(&mut tmp)).await {
                Ok(Ok(0)) => break,
                Ok(Ok(n)) => n,
                Ok(Err(e)) => return Err(e),
                Err(_) => return write_status(&mut stream, 408, "Request Timeout").await,
            };
            body.extend_from_slice(&tmp[..n]);
        }

        let payload: serde_json::Value =
            serde_json::from_slice(&body).unwrap_or(serde_json::json!({}));
        let cmd = payload.get("command").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let cwd = payload.get("cwd").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let reason = payload.get("reason").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let allowed = ask_user_to_approve(&st.app, &cmd, &cwd, &reason).await;
        let resp_body = serde_json::json!({"allowed": allowed}).to_string();
        return write_response(&mut stream, 200, "OK", "application/json", resp_body.into_bytes()).await;
    }

    write_status(&mut stream, 404, "Not Found").await
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

async fn write_status(stream: &mut TcpStream, code: u16, reason: &str) -> std::io::Result<()> {
    write_response(stream, code, reason, "text/plain", Vec::new()).await
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

async fn ask_user_to_approve(app: &AppHandle, cmd: &str, cwd: &str, reason: &str) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
    let (tx, rx) = oneshot::channel();
    let body = if reason.is_empty() {
        format!("Command:\n{cmd}\n\nFolder:\n{cwd}")
    } else {
        format!("{reason}\n\nCommand:\n{cmd}\n\nFolder:\n{cwd}")
    };
    let title = "HermesDesk wants to run a command".to_string();
    let app_clone = app.clone();
    tauri::async_runtime::spawn(async move {
        let dlg = app_clone
            .dialog()
            .message(body)
            .title(title)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Allow this once".into(),
                "Deny".into(),
            ));
        dlg.show(move |allowed| {
            let _ = tx.send(allowed);
        });
    });
    rx.await.unwrap_or(false)
}
