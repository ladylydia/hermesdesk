//! Email OAuth helper flows.

use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};
use tauri::AppHandle;

const MICROSOFT_DEFAULT_SCOPE: &str = "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access";

#[derive(Debug, Deserialize)]
struct MicrosoftDeviceCodeResponse {
    device_code: String,
    user_code: String,
    verification_uri: String,
    expires_in: u64,
    interval: Option<u64>,
    message: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EmailOAuthDeviceStart {
    pub device_code: String,
    pub user_code: String,
    pub verification_uri: String,
    pub expires_in: u64,
    pub interval: u64,
    pub message: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EmailOAuthStatus {
    pub has_default_client_id: bool,
}

#[derive(Debug, Deserialize)]
struct MicrosoftTokenResponse {
    access_token: Option<String>,
    refresh_token: Option<String>,
    expires_in: Option<u64>,
    error: Option<String>,
    error_description: Option<String>,
}

fn normalize_tenant(tenant: Option<String>) -> String {
    let tenant = tenant.unwrap_or_else(|| "common".to_string());
    let tenant = tenant.trim();
    if tenant.is_empty() {
        "common".to_string()
    } else {
        tenant.to_string()
    }
}

fn normalize_scope(scope: Option<String>) -> String {
    let scope = scope.unwrap_or_default();
    let scope = scope.trim();
    if scope.is_empty() {
        MICROSOFT_DEFAULT_SCOPE.to_string()
    } else {
        scope.to_string()
    }
}

fn token_base_url(tenant: &str) -> String {
    format!("https://login.microsoftonline.com/{tenant}/oauth2/v2.0")
}

fn default_client_id() -> Option<String> {
    std::env::var("KABUQINA_MICROSOFT_OAUTH_CLIENT_ID")
        .ok()
        .or_else(|| option_env!("KABUQINA_MICROSOFT_OAUTH_CLIENT_ID").map(str::to_string))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn resolve_client_id(client_id: String) -> Result<String, String> {
    let client_id = client_id.trim().to_string();
    if !client_id.is_empty() {
        return Ok(client_id);
    }
    default_client_id().ok_or_else(|| {
        "No built-in Microsoft OAuth app is configured yet. For testing, expand advanced options and enter a Microsoft Entra client ID.".to_string()
    })
}

fn form_body<'a>(pairs: impl IntoIterator<Item = (&'a str, &'a str)>) -> String {
    let mut ser = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in pairs {
        ser.append_pair(key, value);
    }
    ser.finish()
}

#[tauri::command]
pub fn cmd_email_oauth_status() -> EmailOAuthStatus {
    EmailOAuthStatus {
        has_default_client_id: default_client_id().is_some(),
    }
}

#[tauri::command]
pub async fn cmd_email_oauth_device_start(
    app: AppHandle,
    client_id: String,
    tenant: Option<String>,
    scope: Option<String>,
) -> Result<EmailOAuthDeviceStart, String> {
    let client_id = resolve_client_id(client_id)?;
    crate::validation::validate_env_value(&client_id)?;
    let tenant = normalize_tenant(tenant);
    crate::validation::validate_env_value(&tenant)?;
    let scope = normalize_scope(scope);
    crate::validation::validate_env_value(&scope)?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("{}/devicecode", token_base_url(&tenant));
    let res = client
        .post(url)
        .header(
            reqwest::header::CONTENT_TYPE,
            "application/x-www-form-urlencoded",
        )
        .body(form_body([
            ("client_id", client_id.as_str()),
            ("scope", scope.as_str()),
        ]))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = res.status();
    let body = res.text().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!(
            "Microsoft device-code request failed ({status}): {body}"
        ));
    }
    let parsed: MicrosoftDeviceCodeResponse =
        serde_json::from_str(&body).map_err(|e| e.to_string())?;

    use tauri_plugin_opener::OpenerExt;
    let _ = app
        .opener()
        .open_url(parsed.verification_uri.as_str(), None::<&str>);

    Ok(EmailOAuthDeviceStart {
        device_code: parsed.device_code,
        user_code: parsed.user_code.clone(),
        verification_uri: parsed.verification_uri,
        expires_in: parsed.expires_in,
        interval: parsed.interval.unwrap_or(5).max(1),
        message: parsed.message.unwrap_or_else(|| {
            format!(
                "Open Microsoft sign-in and enter code {}.",
                parsed.user_code
            )
        }),
    })
}

#[tauri::command]
pub async fn cmd_email_oauth_device_finish(
    app: AppHandle,
    address: String,
    imap_host: String,
    smtp_host: String,
    client_id: String,
    tenant: Option<String>,
    device_code: String,
    interval: Option<u64>,
    expires_in: Option<u64>,
) -> Result<(), String> {
    let client_id = resolve_client_id(client_id)?;
    let device_code = device_code.trim().to_string();
    if device_code.is_empty() {
        return Err("OAuth flow was not started".into());
    }
    crate::validation::validate_env_value(&client_id)?;
    crate::validation::validate_env_value(&device_code)?;
    let tenant = normalize_tenant(tenant);
    crate::validation::validate_env_value(&tenant)?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let token_url = format!("{}/token", token_base_url(&tenant));
    let poll_interval = Duration::from_secs(interval.unwrap_or(5).max(1));
    let deadline = Instant::now() + Duration::from_secs(expires_in.unwrap_or(900).max(60));

    loop {
        let res = client
            .post(&token_url)
            .header(
                reqwest::header::CONTENT_TYPE,
                "application/x-www-form-urlencoded",
            )
            .body(form_body([
                ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
                ("client_id", client_id.as_str()),
                ("device_code", device_code.as_str()),
            ]))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        let status = res.status();
        let body = res.text().await.map_err(|e| e.to_string())?;
        let parsed: MicrosoftTokenResponse = serde_json::from_str(&body)
            .map_err(|e| format!("Unexpected token response: {e}: {body}"))?;

        if status.is_success() {
            let access = parsed
                .access_token
                .filter(|s| !s.trim().is_empty())
                .ok_or_else(|| {
                    "Microsoft token response did not include an access token".to_string()
                })?;
            let refresh = parsed
                .refresh_token
                .filter(|s| !s.trim().is_empty())
                .ok_or_else(|| "Microsoft token response did not include a refresh token; make sure offline_access is granted".to_string())?;
            let _ = parsed.expires_in;
            return crate::email_env::cmd_email_save_config(
                app,
                address,
                "".to_string(),
                imap_host,
                smtp_host,
                Some("oauth2".to_string()),
                Some(access),
                Some(refresh),
                Some(client_id),
                Some("".to_string()),
                Some(tenant),
                Some("".to_string()),
                Some("".to_string()),
            );
        }

        match parsed.error.as_deref() {
            Some("authorization_pending") => {}
            Some("slow_down") => {
                tokio::time::sleep(poll_interval).await;
            }
            Some("authorization_declined") => {
                return Err("Microsoft sign-in was declined".into());
            }
            Some("expired_token") => {
                return Err("Microsoft sign-in code expired; start again".into());
            }
            Some(code) => {
                let desc = parsed.error_description.unwrap_or_default();
                return Err(format!("Microsoft OAuth error: {code} {desc}"));
            }
            None => {
                return Err(format!("Microsoft token request failed ({status}): {body}"));
            }
        }

        if Instant::now() >= deadline {
            return Err("Timed out waiting for Microsoft sign-in".into());
        }
        tokio::time::sleep(poll_interval).await;
    }
}

#[cfg(test)]
mod tests {
    use super::{
        normalize_scope, normalize_tenant, resolve_client_id, token_base_url,
        MICROSOFT_DEFAULT_SCOPE,
    };

    #[test]
    fn defaults_to_common_tenant_and_outlook_scope() {
        assert_eq!(normalize_tenant(None), "common");
        assert_eq!(normalize_tenant(Some("  ".into())), "common");
        assert_eq!(normalize_scope(None), MICROSOFT_DEFAULT_SCOPE);
        assert_eq!(
            token_base_url("common"),
            "https://login.microsoftonline.com/common/oauth2/v2.0"
        );
    }

    #[test]
    fn explicit_client_id_wins() {
        assert_eq!(
            resolve_client_id(" explicit-client ".into()).unwrap(),
            "explicit-client"
        );
    }
}
