/**
 * The set of LLM providers HermesDesk's onboarding wizard knows about.
 * Each provider lists:
 *   - id            stable internal id matched in the Python overlay
 *   - host          the API host added to the network allowlist
 *   - signupUrl     where to send the user from "Get your access pass"
 *   - validateUrl   a cheap GET endpoint we ping with the pasted key
 *   - validateAuth  how to format the Authorization header for validation
 *   - keyPrefixHint a hint we show if the pasted key clearly looks wrong
 */
export type ProviderId =
  | "openrouter"
  | "openai"
  | "anthropic"
  | "nous"
  | "groq"
  | "mistral";

export interface Provider {
  id: ProviderId;
  label: string;
  host: string;
  signupUrl: string;
  validateUrl: string;
  validateAuth: (key: string) => string;
  keyPrefixHint?: string;
  blurb: string;
  freeTier: boolean;
}

export const PROVIDERS: Provider[] = [
  {
    id: "openrouter",
    label: "OpenRouter",
    host: "openrouter.ai",
    signupUrl: "https://openrouter.ai/keys",
    validateUrl: "https://openrouter.ai/api/v1/auth/key",
    validateAuth: (k) => `Bearer ${k}`,
    keyPrefixHint: "sk-or-",
    blurb: "200+ models from one key. Has a free tier.",
    freeTier: true,
  },
  {
    id: "openai",
    label: "OpenAI",
    host: "api.openai.com",
    signupUrl: "https://platform.openai.com/api-keys",
    validateUrl: "https://api.openai.com/v1/models",
    validateAuth: (k) => `Bearer ${k}`,
    keyPrefixHint: "sk-",
    blurb: "GPT-5.x and friends. Pay as you go.",
    freeTier: false,
  },
  {
    id: "anthropic",
    label: "Anthropic",
    host: "api.anthropic.com",
    signupUrl: "https://console.anthropic.com/settings/keys",
    validateUrl: "https://api.anthropic.com/v1/models",
    validateAuth: (k) => k,
    keyPrefixHint: "sk-ant-",
    blurb: "Claude. Excellent at writing and reasoning.",
    freeTier: false,
  },
  {
    id: "nous",
    label: "Nous Portal",
    host: "portal.nousresearch.com",
    signupUrl: "https://portal.nousresearch.com",
    validateUrl: "https://portal.nousresearch.com/api/v1/models",
    validateAuth: (k) => `Bearer ${k}`,
    blurb: "Nous Research's hosted Hermes models.",
    freeTier: false,
  },
  {
    id: "groq",
    label: "Groq",
    host: "api.groq.com",
    signupUrl: "https://console.groq.com/keys",
    validateUrl: "https://api.groq.com/openai/v1/models",
    validateAuth: (k) => `Bearer ${k}`,
    keyPrefixHint: "gsk_",
    blurb: "Very fast Llama / Mixtral. Free tier with rate limits.",
    freeTier: true,
  },
  {
    id: "mistral",
    label: "Mistral",
    host: "api.mistral.ai",
    signupUrl: "https://console.mistral.ai/api-keys",
    validateUrl: "https://api.mistral.ai/v1/models",
    validateAuth: (k) => `Bearer ${k}`,
    blurb: "Mistral's hosted models.",
    freeTier: false,
  },
];

export function findProvider(id: ProviderId): Provider {
  const p = PROVIDERS.find((x) => x.id === id);
  if (!p) throw new Error(`unknown provider ${id}`);
  return p;
}
