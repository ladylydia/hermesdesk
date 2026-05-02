//! Shared validation helpers for security-sensitive inputs.
//!
//! Two surfaces:
//!   1. `validate_env_value` — rejects control characters so a malicious
//!      token cannot inject extra env vars when written to `.env`.
//!   2. `validate_public_endpoint` — ensures the LLM endpoint URL is
//!      HTTPS and reaches a public host (not loopback / RFC1918 / link-local
//!      / multicast). When `saved_api_base` is `Some`, the URL host must
//!      also match it — so a compromised renderer cannot redirect the API
//!      key to an arbitrary host.

use std::net::{Ipv4Addr, Ipv6Addr};

/// Reject control characters that would corrupt a `.env` line.
///
/// Blocks: `\r` (0x0D), `\n` (0x0A), NUL (0x00), and every char < 0x20
/// or DEL (0x7F).
pub fn validate_env_value(value: &str) -> Result<(), String> {
    if value.contains(|c: char| {
        let cu = c as u32;
        cu < 0x20 || cu == 0x7f
    }) {
        return Err("Credentials must not contain newline or control characters".into());
    }
    Ok(())
}

/// Validate a public endpoint URL.
///
/// Requirements:
///   * Scheme must be `"https"`.
///   * Host must not resolve to a non-public address (loopback, private,
///     link-local, multicast).
///   * If `saved_api_base` is `Some`, the URL host must equal the host
///     extracted from `saved_api_base` (so a compromised renderer cannot
///     substitute an untrusted host).
pub fn validate_public_endpoint(url_str: &str, saved_api_base: Option<&str>) -> Result<(), String> {
    let parsed =
        url::Url::parse(url_str).map_err(|e| format!("Invalid URL: {e}"))?;

    if parsed.scheme() != "https" {
        return Err("Only HTTPS endpoints are allowed for custom API validation".into());
    }

    let host = parsed
        .host_str()
        .ok_or_else(|| "URL must include a host".to_string())?;

    if is_private_or_loopback(host) {
        return Err(format!("{host} is not a public address. Local and private endpoints are not supported for custom API validation."));
    }

    if let Some(base) = saved_api_base {
        let base_host = url::Url::parse(base)
            .map_err(|e| format!("Invalid saved API base URL: {e}"))?
            .host_str()
            .map(|h| h.to_string())
            .ok_or_else(|| "Saved API base URL must include a host".to_string())?;

        if host != base_host {
            return Err(format!(
                r#"The endpoint host "{host}" does not match your configured API base "{base_host}".
Enter the same host you saved as your custom provider, or update Settings first."#
            ));
        }
    }

    Ok(())
}

fn is_private_or_loopback(host: &str) -> bool {
    // Bare hostname heuristics — `localhost` and `.local` are unsafe.
    let lower = host.to_lowercase();
    if lower == "localhost" || lower.ends_with(".local") {
        return true;
    }

    // Try to interpret as an IPv4 or IPv6 address.
    if let Ok(ip4) = host.parse::<Ipv4Addr>() {
        return ip4_is_private_or_loopback(ip4);
    }
    // Strip brackets from IPv6 literal.
    let host6 = host.strip_prefix('[').and_then(|s| s.strip_suffix(']'));
    if let Some(host6) = host6 {
        if let Ok(ip6) = host6.parse::<Ipv6Addr>() {
            return ip6_is_private_or_loopback(ip6);
        }
        // Bracketed but not a valid IPv6 — reject.
        return true;
    }
    // Plain IPv6 (unbracketed).
    if let Ok(ip6) = host.parse::<Ipv6Addr>() {
        return ip6_is_private_or_loopback(ip6);
    }

    // Not an IP address and not a known-bad hostname — allow.
    false
}

fn ip4_is_private_or_loopback(ip: Ipv4Addr) -> bool {
    let octets = ip.octets();
    match octets {
        // Loopback
        [127, _, _, _] => true,
        // RFC 1918 private
        [10, _, _, _] => true,
        [172, a, _, _] if (16..=31).contains(&a) => true,
        [192, 168, _, _] => true,
        // Link-local
        [169, 254, _, _] => true,
        // Multicast
        [224..=239, _, _, _] => true,
        // Broadcast
        [255, 255, 255, 255] => true,
        _ => false,
    }
}

fn ip6_is_private_or_loopback(ip: Ipv6Addr) -> bool {
    if ip.is_loopback() {
        return true;
    }
    if ip.is_multicast() {
        return true;
    }
    // Link-local: fe80::/10
    if ip.segments()[0] & 0xffc0 == 0xfe80 {
        return true;
    }
    // Unique local unicast: fc00::/7
    if ip.segments()[0] & 0xfe00 == 0xfc00 {
        return true;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── env value ──────────────────────────────────────────────────────

    #[test]
    fn env_value_ok_plain() {
        assert!(validate_env_value("sk-abc123XYZ").is_ok());
    }

    #[test]
    fn env_value_ok_unicode() {
        assert!(validate_env_value("🔑secret中文key").is_ok());
    }

    #[test]
    fn env_value_reject_newline() {
        assert!(validate_env_value("abc\ndef").is_err());
    }

    #[test]
    fn env_value_reject_cr() {
        assert!(validate_env_value("abc\rdef").is_err());
    }

    #[test]
    fn env_value_reject_nul() {
        assert!(validate_env_value("abc\0def").is_err());
    }

    #[test]
    fn env_value_reject_tab() {
        // \t = 0x09, below 0x20 → control char
        assert!(validate_env_value("abc\tdef").is_err());
    }

    #[test]
    fn env_value_reject_del() {
        assert!(validate_env_value("abc\u{7f}def").is_err());
    }

    #[test]
    fn env_value_ok_empty() {
        // Empty strings are rejected by the caller via is_empty() check,
        // but validation itself passes (no control chars).
        assert!(validate_env_value("").is_ok());
    }

    // ── public endpoint ────────────────────────────────────────────────

    #[test]
    fn endpoint_ok_public_https() {
        assert!(validate_public_endpoint("https://api.openai.com/v1/models", None).is_ok());
    }

    #[test]
    fn endpoint_reject_http() {
        assert!(validate_public_endpoint("http://api.openai.com/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_loopback_v4() {
        assert!(validate_public_endpoint("https://127.0.0.1:11434/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_loopback_localhost() {
        assert!(validate_public_endpoint("https://localhost:11434/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_private_192168() {
        assert!(validate_public_endpoint("https://192.168.1.100/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_private_10() {
        assert!(validate_public_endpoint("https://10.0.0.1/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_private_172() {
        assert!(validate_public_endpoint("https://172.16.0.1/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_link_local() {
        assert!(validate_public_endpoint("https://169.254.1.1/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_multicast() {
        assert!(validate_public_endpoint("https://224.0.0.1/v1/models", None).is_err());
    }

    #[test]
    fn endpoint_reject_invalid_url() {
        assert!(validate_public_endpoint("not-a-url", None).is_err());
    }

    #[test]
    fn endpoint_ok_known_provider_no_base_match() {
        // openrouter allows any https public URL when no api_base_url saved
        assert!(validate_public_endpoint(
            "https://openrouter.ai/api/v1/auth/key",
            None
        )
        .is_ok());
    }

    #[test]
    fn endpoint_reject_host_mismatch_when_base_saved() {
        let result = validate_public_endpoint(
            "https://evil.example.com/v1/models",
            Some("https://api.mycorp.com/v1"),
        );
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("does not match"));
    }

    #[test]
    fn endpoint_ok_host_matches_base() {
        assert!(validate_public_endpoint(
            "https://api.mycorp.com/v1/models",
            Some("https://api.mycorp.com/v1"),
        )
        .is_ok());
    }

    #[test]
    fn endpoint_ok_invalid_saved_base_returns_error() {
        // If the saved base URL is malformed, validation surfaces the error.
        assert!(validate_public_endpoint(
            "https://api.mycorp.com/v1/models",
            Some("not-a-base-url"),
        )
        .is_err());
    }

    // ── ip4 classification ─────────────────────────────────────────────

    #[test]
    fn ip4_ok_public() {
        assert!(!is_private_or_loopback("8.8.8.8"));
        assert!(!is_private_or_loopback("1.1.1.1"));
        assert!(!is_private_or_loopback("34.120.0.1"));
    }

    #[test]
    fn ip4_loopback() {
        assert!(is_private_or_loopback("127.0.0.1"));
        assert!(is_private_or_loopback("127.255.255.255"));
    }

    #[test]
    fn ip4_private() {
        assert!(is_private_or_loopback("10.0.0.1"));
        assert!(is_private_or_loopback("172.31.0.1"));
        assert!(is_private_or_loopback("192.168.1.1"));
    }

    #[test]
    fn ip4_172_32_is_public() {
        // 172.32.x.x is outside RFC 1918 range
        assert!(!is_private_or_loopback("172.32.0.1"));
    }

    // ── ip6 classification ─────────────────────────────────────────────

    #[test]
    fn ip6_loopback() {
        assert!(is_private_or_loopback("::1"));
    }

    #[test]
    fn ip6_link_local() {
        assert!(is_private_or_loopback("fe80::1"));
    }

    #[test]
    fn ip6_ula() {
        assert!(is_private_or_loopback("fc00::1"));
        assert!(is_private_or_loopback("fdff::1"));
    }
}
