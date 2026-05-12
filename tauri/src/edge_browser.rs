//! Edge browser lifecycle — launch a headless Edge instance with CDP for
//! browser automation.  Edge is pre-installed on Windows; no Node.js/Playwright
//! needed.  The child uses ``BROWSER_CDP_URL`` to connect via CDP protocol.

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex as SyncMutex;

const CDP_PORT: &str = "9222";

/// Locate the Edge executable on Windows.
fn find_edge() -> Option<PathBuf> {
    let candidates = [
        // 64-bit Edge on 64-bit Windows
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        // Edge on ARM / alternate install
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ];
    for path in &candidates {
        let p = PathBuf::from(path);
        if p.exists() {
            return Some(p);
        }
    }
    None
}

/// Compute a profile dir under ``{hermes_home}/edge-profile/`` so Edge
/// remembers login sessions across restarts.
fn profile_dir(data_dir: &std::path::Path) -> PathBuf {
    let dir = data_dir.join("edge-profile");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

/// The CDP URL that browser tools should connect to.
pub fn cdp_url() -> String {
    format!("http://127.0.0.1:{}", CDP_PORT)
}

/// Start a headless Edge instance with remote debugging enabled.
///
/// Returns the child process handle on success.
pub fn spawn(data_dir: &std::path::Path) -> Result<Child, String> {
    let edge = find_edge().ok_or_else(|| {
        "Microsoft Edge not found. Install Edge or configure a different browser backend."
            .to_string()
    })?;

    let profile = profile_dir(data_dir);
    let child = Command::new(&edge)
        .arg(format!("--remote-debugging-port={}", CDP_PORT))
        .arg(format!("--user-data-dir={}", profile.display()))
        .arg("--no-first-run")
        .arg("--no-default-browser-check")
        .arg("--headless")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to launch Edge: {}", e))?;

    log::info!(
        "Edge browser started (CDP port {CDP_PORT}, pid={})",
        child.id()
    );
    Ok(child)
}

/// Gracefully kill the Edge child process.
pub fn shutdown(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
    log::info!("Edge browser stopped");
}

// ---------------------------------------------------------------------------
// Managed lifecycle helper — stored in AppState so the Tauri shell can
// start/kill Edge in sync with the app.
// ---------------------------------------------------------------------------

pub struct EdgeSupervisor {
    child: SyncMutex<Option<Child>>,
}

impl EdgeSupervisor {
    pub fn new() -> Self {
        Self {
            child: SyncMutex::new(None),
        }
    }

    /// Start Edge CDP browser. Blocking — called from an async spawn context.
    pub fn start(&self, data_dir: &std::path::Path) -> Result<(), String> {
        let mut guard = self.child.lock().unwrap();
        if guard.is_some() {
            return Ok(()); // already running
        }
        let child = spawn(data_dir)?;
        *guard = Some(child);
        Ok(())
    }

    /// Kill Edge CDP browser. Sync — safe to call from Tauri RunEvent handler.
    pub fn stop(&self) {
        let mut guard = self.child.lock().unwrap();
        if let Some(mut c) = guard.take() {
            shutdown(&mut c);
        }
    }

    pub fn is_running(&self) -> bool {
        self.child.lock().unwrap().is_some()
    }
}
