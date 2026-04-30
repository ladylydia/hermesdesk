/**
 * When navigating to `/chat` right after the setup wizard completed saving the key,
 * pass this state so `ChatPage` can skip the immediate `cmd_has_secret` gate (avoids
 * a race with keyring or bridge timing) and then strip the state for normal behavior.
 */
export const CHAT_FROM_ONBOARDING_STATE: { fromOnboarding: true } = { fromOnboarding: true };

export type ChatLocationState = { fromOnboarding?: boolean };

export function isFromOnboarding(state: unknown): state is { fromOnboarding: true } {
  return typeof state === "object" && state !== null && (state as ChatLocationState).fromOnboarding === true;
}
