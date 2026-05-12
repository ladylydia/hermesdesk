import { invoke } from "@tauri-apps/api/core";

/** Payload emitted by the Rust backend via `capture-done` event. */
export interface CaptureDonePayload {
  path: string;
  name: string;
  mime: string;
  data: string; // base64-encoded PNG bytes
}

export async function showCaptureOverlay(): Promise<void> {
  return invoke("cmd_show_capture_overlay");
}

export async function hideCaptureOverlay(): Promise<void> {
  return invoke("cmd_hide_capture_overlay");
}

export async function captureFullscreen(): Promise<string> {
  return invoke("cmd_capture_fullscreen");
}
