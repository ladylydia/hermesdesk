import { findProvider, type ProviderId } from "./providers";

/** Strip trailing slashes for OpenAI-compatible base URLs. */
export function normalizeOpenAiBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

/**
 * Validate a custom OpenAI-compatible endpoint via GET /v1/models (or /models under the given base).
 */
export async function validateCustomEndpoint(
  baseUrl: string,
  apiKey: string
): Promise<ValidateResult> {
  const base = normalizeOpenAiBaseUrl(baseUrl);
  if (!base) {
    return { ok: false, message: "Please paste your API address (for example https://example.com/v1)." };
  }
  const trimmed = apiKey.trim();
  if (!trimmed) {
    return { ok: false, message: "Please paste your access pass." };
  }
  const modelsUrl = `${base}/models`;
  try {
    const res = await fetch(modelsUrl, {
      method: "GET",
      headers: { Authorization: `Bearer ${trimmed}` },
    });
    if (res.status === 401 || res.status === 403) {
      return { ok: false, message: "That pass didn't work. Double-check you copied the whole thing." };
    }
    if (!res.ok) {
      return {
        ok: false,
        message: `That API address answered ${res.status}. Check the URL ends with /v1 (or your vendor's equivalent).`,
      };
    }
    return { ok: true };
  } catch {
    return {
      ok: false,
      message: "Couldn't reach that API address. Check your internet connection and the URL.",
    };
  }
}

export interface ValidateResult {
  ok: boolean;
  message?: string;
}

/**
 * Live-validate a key by hitting the provider's cheapest authenticated
 * endpoint. We do this from the WebView (CSP allows the provider host
 * during onboarding). The key is NOT sent to Tauri until validation
 * succeeds and the user clicks "Save".
 */
export async function validateKey(
  providerId: ProviderId,
  key: string
): Promise<ValidateResult> {
  const provider = findProvider(providerId);
  const trimmed = key.trim();
  if (!trimmed) return { ok: false, message: "Please paste your access pass." };

  if (provider.keyPrefixHint && !trimmed.startsWith(provider.keyPrefixHint)) {
    return {
      ok: false,
      message: `That doesn't look like a ${provider.label} pass. They usually start with "${provider.keyPrefixHint}".`,
    };
  }

  try {
    const res = await fetch(provider.validateUrl, {
      method: "GET",
      headers: {
        Authorization: provider.validateAuth(trimmed),
        // Anthropic wants its own header style:
        ...(provider.id === "anthropic"
          ? { "x-api-key": trimmed, "anthropic-version": "2023-06-01" }
          : {}),
      },
    });
    if (res.status === 401 || res.status === 403) {
      return { ok: false, message: "That pass didn't work. Double-check you copied the whole thing." };
    }
    if (!res.ok) {
      return { ok: false, message: `${provider.label} answered ${res.status}. Try again in a moment.` };
    }
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      message: `Couldn't reach ${provider.label}. Check your internet connection.`,
    };
  }
}
