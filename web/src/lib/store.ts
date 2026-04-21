import { useSyncExternalStore } from "react";
import type { ProviderId } from "./providers";

export type Personality = "helpful" | "friendly" | "concise";

export interface OnboardingDraft {
  providerId: ProviderId | null;
  apiKey: string;
  personality: Personality;
  /** OpenAI-compatible API base URL (custom provider only). */
  customBaseUrl?: string;
  /** Model id as required by that endpoint (custom provider only). */
  customModel?: string;
}

const KEY = "hermesdesk.onboarding-draft";

const initial: OnboardingDraft = {
  providerId: null,
  apiKey: "",
  personality: "helpful",
};

let state: OnboardingDraft = (() => {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return { ...initial, ...JSON.parse(raw) };
  } catch {
    // ignore
  }
  return initial;
})();

const subscribers = new Set<() => void>();

function snapshot() {
  return state;
}

function subscribe(cb: () => void) {
  subscribers.add(cb);
  return () => subscribers.delete(cb);
}

export function updateDraft(patch: Partial<OnboardingDraft>) {
  state = { ...state, ...patch };
  // Persist everything EXCEPT the API key. Key must never touch disk.
  const { apiKey: _omit, ...safe } = state;
  void _omit;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(safe));
  } catch {
    // ignore
  }
  subscribers.forEach((cb) => cb());
}

export function clearDraft() {
  state = initial;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
  subscribers.forEach((cb) => cb());
}

export function useDraft() {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
