//! Read/write arbitrary gateway-related keys in the host ``hermes-home/.env``.
//! Used by Settings UI for per-channel behavior (connection mode, DM policy, …).

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use serde::Deserialize;
use tauri::AppHandle;

use crate::gateway_supervisor::{hermes_home_path, parse_dotenv_upper};
use crate::validation::validate_env_value;

#[derive(Debug, Clone, Deserialize)]
pub struct EnvKv {
    pub key: String,
    pub value: String,
}

fn validate_env_key(key: &str) -> Result<(), String> {
    let k = key.trim();
    if k.is_empty() {
        return Err("Env key must not be empty".into());
    }
    if !k
        .chars()
        .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
    {
        return Err("Env key must be A-Z, digits, underscore only".into());
    }
    if !k.starts_with(|c: char| c.is_ascii_uppercase()) {
        return Err("Env key must start with a letter".into());
    }
    Ok(())
}

/// Read selected keys from host ``~hermes-home/.env``. Omits keys that are unset or empty.
#[tauri::command]
pub fn cmd_gateway_host_env_get(
    app: AppHandle,
    keys: Vec<String>,
) -> Result<HashMap<String, String>, String> {
    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = hermes_home_path(&data_dir);
    let map = parse_dotenv_upper(&hh);
    let mut out = HashMap::new();
    for k in keys {
        let ku = k.trim().to_uppercase();
        validate_env_key(&ku)?;
        if let Some(v) = map.get(&ku).filter(|s| !s.is_empty()) {
            out.insert(ku, v.clone());
        }
    }
    Ok(out)
}

/// Upsert and/or remove keys in host ``.env``. Values are validated (no control chars).
#[tauri::command]
pub fn cmd_gateway_host_env_patch(
    app: AppHandle,
    upserts: Vec<EnvKv>,
    remove_keys: Vec<String>,
) -> Result<(), String> {
    for kv in &upserts {
        validate_env_key(&kv.key)?;
        validate_env_value(&kv.value)?;
    }
    for k in &remove_keys {
        validate_env_key(k)?;
    }

    let data_dir = crate::paths::ensure_data_dir(&app).map_err(|e| e.to_string())?;
    let hh = hermes_home_path(&data_dir);
    std::fs::create_dir_all(&hh).map_err(|e| e.to_string())?;

    let env_path: PathBuf = hh.join(".env");
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut lines: Vec<String> = content.lines().map(|l| l.to_string()).collect();

    let remove_upper: HashSet<String> = remove_keys
        .iter()
        .map(|k| k.trim().to_uppercase())
        .collect();

    let upsert_upper: HashMap<String, String> = upserts
        .iter()
        .map(|kv| (kv.key.trim().to_uppercase(), kv.value.clone()))
        .collect();

    let mut seen_upsert = HashSet::<String>::new();

    for line in &mut lines {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((raw_k, _)) = trimmed.split_once('=') else {
            continue;
        };
        let ku = raw_k.trim().to_uppercase();
        if remove_upper.contains(&ku) {
            *line = String::new();
            continue;
        }
        if let Some(val) = upsert_upper.get(&ku) {
            *line = format!("{}={}", ku, strip_wrapping_quotes(val));
            seen_upsert.insert(ku.clone());
        }
    }

    lines.retain(|l| !l.is_empty());

    for (k, v) in &upsert_upper {
        if seen_upsert.contains(k) {
            continue;
        }
        lines.push(format!("{}={}", k, strip_wrapping_quotes(v)));
    }

    std::fs::write(&env_path, lines.join("\n") + "\n").map_err(|e| e.to_string())
}

fn strip_wrapping_quotes(s: &str) -> String {
    let t = s.trim();
    if t.len() >= 2 {
        let b = t.as_bytes();
        if (b[0] == b'"' && b[t.len() - 1] == b'"')
            || (b[0] == b'\'' && b[t.len() - 1] == b'\'')
        {
            return t[1..t.len() - 1].to_string();
        }
    }
    t.to_string()
}
