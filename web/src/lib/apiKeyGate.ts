/** User chose “configure API later” on the pass step; allows opening /chat without a saved key until they configure. */
const STORAGE_KEY = "hermesdesk.allow_chat_without_api";

export function setAllowChatWithoutApi(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function getAllowChatWithoutApi(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function clearAllowChatWithoutApi(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
