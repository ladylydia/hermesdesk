//! Loopback HTTP bridge for the Python child.
//!
//! Two endpoints, both protected by a per-launch random token in the path:
//!
//!   GET  /secret/<token>     -> body = the API key text/plain (one shot)
//!   POST /approval/<token>   -> body = JSON { command, cwd, reason }
//!                               -> response = JSON { allowed: bool }
//!
//! Bound to 127.0.0.1 only. The tokens never leave this process except via
//! the env vars passed to the Python child.

use anyhow::Result;
use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::{Request, Response, StatusCode};
use hyper_util::rt::TokioIo;
use rand::RngCore;
use std::net::SocketAddr;
use std::sync::Arc;
use tauri::{AppHandle, Manager};
use tokio::net::TcpListener;
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

    tokio::spawn(serve(listener, state));

    Ok(Bridge { addr, secret_url, approval_url })
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

async fn serve(listener: TcpListener, state: Arc<State>) {
    loop {
        let (stream, _) = match listener.accept().await {
            Ok(p) => p,
            Err(e) => {
                log::warn!("bridge accept: {e}");
                continue;
            }
        };
        let io = TokioIo::new(stream);
        let st = state.clone();
        tokio::spawn(async move {
            let svc = hyper::service::service_fn(move |req| {
                let st = st.clone();
                async move { handle(req, st).await }
            });
            if let Err(e) = hyper::server::conn::http1::Builder::new()
                .serve_connection(io, svc)
                .await
            {
                log::debug!("bridge conn: {e}");
            }
        });
    }
}

async fn handle(
    req: Request<hyper::body::Incoming>,
    st: Arc<State>,
) -> std::result::Result<Response<Full<Bytes>>, std::convert::Infallible> {
    let path = req.uri().path().to_string();
    let method = req.method().clone();

    // Constant-time-ish prefix matching is fine here; tokens are 256 bits.
    if method == hyper::Method::GET && path == format!("/secret/{}", st.secret_token) {
        let secret = crate::secrets::read_current_secret(&st.app).unwrap_or_default();
        return Ok(text(secret));
    }
    if method == hyper::Method::POST && path == format!("/approval/{}", st.approval_token) {
        let body = match req.into_body().collect().await {
            Ok(b) => b.to_bytes(),
            Err(_) => return Ok(status(StatusCode::BAD_REQUEST)),
        };
        let payload: serde_json::Value =
            serde_json::from_slice(&body).unwrap_or(serde_json::json!({}));
        let cmd = payload.get("command").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let cwd = payload.get("cwd").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let reason = payload.get("reason").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let allowed = ask_user_to_approve(&st.app, &cmd, &cwd, &reason).await;
        let resp_body = serde_json::json!({"allowed": allowed}).to_string();
        return Ok(json(resp_body));
    }
    Ok(status(StatusCode::NOT_FOUND))
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

fn text(s: String) -> Response<Full<Bytes>> {
    Response::builder()
        .header("content-type", "text/plain; charset=utf-8")
        .body(Full::new(Bytes::from(s)))
        .unwrap()
}
fn json(s: String) -> Response<Full<Bytes>> {
    Response::builder()
        .header("content-type", "application/json")
        .body(Full::new(Bytes::from(s)))
        .unwrap()
}
fn status(s: StatusCode) -> Response<Full<Bytes>> {
    Response::builder().status(s).body(Full::new(Bytes::new())).unwrap()
}
