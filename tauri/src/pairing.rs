//! DM pairing management — read / approve / revoke pairing codes from the desktop UI.
//!
//! Pairing data lives in ``hermes-home/pairing/`` as JSON files:
//!   - ``{platform}-pending.json``  — pending pairing requests
//!   - ``{platform}-approved.json`` — approved (paired) users
//!
//! The Python gateway's ``PairingStore`` reads these on every auth check,
//! so changes written here will be picked up automatically within one message.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use tauri::AppHandle;

// ---- serialization types (mirror pairing.py JSON shape) ----

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PendingEntry {
    user_id: String,
    user_name: String,
    #[serde(rename = "created_at")]
    _created_at: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ApprovedEntry {
    user_name: String,
    #[serde(rename = "approved_at")]
    _approved_at: f64,
}

// ---- types returned to the frontend ----

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingInfo {
    pub platform: String,
    pub code: String,
    pub user_id: String,
    pub user_name: String,
    pub age_minutes: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ApprovedInfo {
    pub platform: String,
    pub user_id: String,
    pub user_name: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingSnapshot {
    pub pending: Vec<PendingInfo>,
    pub approved: Vec<ApprovedInfo>,
}

// ---- helpers ----

fn pairing_dir(data_dir: &std::path::Path) -> PathBuf {
    let hh = crate::gateway_supervisor::hermes_home_path(data_dir);
    // Match Python's PAIRING_DIR = get_hermes_dir("platforms/pairing", "pairing")
    let legacy = hh.join("pairing");
    if legacy.exists() {
        return legacy;
    }
    hh.join("platforms").join("pairing")
}

fn pending_path(data_dir: &std::path::Path, platform: &str) -> PathBuf {
    pairing_dir(data_dir).join(format!("{}-pending.json", platform))
}

fn approved_path(data_dir: &std::path::Path, platform: &str) -> PathBuf {
    pairing_dir(data_dir).join(format!("{}-approved.json", platform))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &PathBuf) -> Option<T> {
    let raw = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&raw).ok()
}

fn write_json<T: Serialize>(path: &PathBuf, data: &T) -> Result<(), String> {
    let dir = path.parent().ok_or("no parent dir")?;
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    // Atomic write via temp-file + rename (same pattern as PairingStore._secure_write)
    let tmp = path.with_extension("json.tmp");
    let json = serde_json::to_string_pretty(data).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, &json).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())?;
    Ok(())
}

fn discover_platforms(data_dir: &std::path::Path, suffix: &str) -> Vec<String> {
    let dir = pairing_dir(data_dir);
    let Ok(entries) = std::fs::read_dir(&dir) else {
        return vec![];
    };
    let mut platforms = Vec::new();
    for entry in entries.flatten() {
        let fname = entry.file_name();
        let name = fname.to_string_lossy();
        if name.ends_with(suffix) && !name.starts_with('_') {
            let platform = name.replace(suffix, "");
            platforms.push(platform);
        }
    }
    platforms
}

fn now_epoch() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

// ---- Tauri commands ----

#[tauri::command]
pub fn cmd_pairing_list(app: AppHandle, platform: Option<String>) -> Result<PairingSnapshot, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let platforms: Vec<String> = match platform {
        Some(ref p) if !p.is_empty() => vec![p.trim().to_lowercase()],
        _ => {
            let mut all = discover_platforms(&data_dir, "-pending.json");
            let approved_platforms = discover_platforms(&data_dir, "-approved.json");
            for p in approved_platforms {
                if !all.contains(&p) {
                    all.push(p);
                }
            }
            all
        }
    };

    let now = now_epoch();
    let mut pending = Vec::new();
    let mut approved = Vec::new();

    for p in &platforms {
        if let Some(pending_raw) =
            read_json::<HashMap<String, PendingEntry>>(&pending_path(&data_dir, p))
        {
            for (code, entry) in &pending_raw {
                let age_secs = now.saturating_sub(entry._created_at as u64);
                pending.push(PendingInfo {
                    platform: p.clone(),
                    code: code.clone(),
                    user_id: entry.user_id.clone(),
                    user_name: entry.user_name.clone(),
                    age_minutes: age_secs / 60,
                });
            }
        }
        if let Some(approved_raw) =
            read_json::<HashMap<String, ApprovedEntry>>(&approved_path(&data_dir, p))
        {
            for (user_id, entry) in &approved_raw {
                approved.push(ApprovedInfo {
                    platform: p.clone(),
                    user_id: user_id.clone(),
                    user_name: entry.user_name.clone(),
                });
            }
        }
    }

    Ok(PairingSnapshot { pending, approved })
}

#[tauri::command]
pub fn cmd_pairing_approve(app: AppHandle, platform: String, code: String) -> Result<String, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let platform = platform.trim().to_lowercase();
    let code = code.trim().to_uppercase();

    if platform.is_empty() || code.is_empty() {
        return Err("platform and code are required".into());
    }

    let pending_file = pending_path(&data_dir, &platform);

    let mut pending: HashMap<String, PendingEntry> =
        read_json(&pending_file).unwrap_or_default();

    let entry = pending
        .remove(&code)
        .ok_or_else(|| format!("Code '{}' not found or expired for '{}'", code, platform))?;

    write_json(&pending_file, &pending)?;

    let approved_file = approved_path(&data_dir, &platform);
    let mut approved: HashMap<String, ApprovedEntry> =
        read_json(&approved_file).unwrap_or_default();

    approved.insert(
        entry.user_id.clone(),
        ApprovedEntry {
            user_name: entry.user_name.clone(),
            _approved_at: now_epoch() as f64,
        },
    );

    write_json(&approved_file, &approved)?;

    let display = if entry.user_name.is_empty() {
        entry.user_id.clone()
    } else {
        format!("{} ({})", entry.user_name, entry.user_id)
    };
    Ok(format!("Approved user {} on {}", display, platform))
}

#[tauri::command]
pub fn cmd_pairing_revoke(app: AppHandle, platform: String, user_id: String) -> Result<String, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let platform = platform.trim().to_lowercase();
    let user_id = user_id.trim().to_string();

    if platform.is_empty() || user_id.is_empty() {
        return Err("platform and user_id are required".into());
    }

    let approved_file = approved_path(&data_dir, &platform);
    let mut approved: HashMap<String, ApprovedEntry> =
        read_json(&approved_file).unwrap_or_default();

    if approved.remove(&user_id).is_none() {
        return Err(format!("User '{}' not found in approved list for '{}'", user_id, platform));
    }

    write_json(&approved_file, &approved)?;

    Ok(format!("Revoked access for user {} on {}", user_id, platform))
}

#[tauri::command]
pub fn cmd_pairing_clear_pending(app: AppHandle, platform: Option<String>) -> Result<String, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let platforms: Vec<String> = match platform {
        Some(ref p) if !p.is_empty() => vec![p.trim().to_lowercase()],
        _ => discover_platforms(&data_dir, "-pending.json"),
    };

    let mut cleared = 0usize;
    for p in &platforms {
        let f = pending_path(&data_dir, p);
        if f.exists() {
            cleared += 1;
            write_json(&f, &serde_json::json!({}))?;
        }
    }

    Ok(format!("Cleared {} pending request(s) across {} platform(s)", cleared, platforms.len()))
}
