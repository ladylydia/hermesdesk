import { useCallback, useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { ArrowUp, Crop, FolderOpen, Paperclip, Square, Zap } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { Toggle } from "../components/ui/Toggle";
import { cn } from "../lib/cn";
import { captureFullscreen, showCaptureOverlay } from "../capture/capture-api";
import { VoiceButton } from "./VoiceButton";
import { useVoiceRecorder } from "./hooks/useVoiceRecorder";

export interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  sending?: boolean;
  placeholder?: string;
  /** Display names of files queued for the next message */
  pendingAttachmentNames: string[];
  onRemoveAttachment: (index: number) => void;
  onFilesPicked: (files: FileList | null) => void;
  onStop?: () => void;
  powerUser?: boolean;
  onTogglePowerUser?: (v: boolean) => void;
}

export function ChatInput({
  value,
  onChange,
  onSend,
  sending = false,
  placeholder,
  pendingAttachmentNames,
  onRemoveAttachment,
  onFilesPicked,
  onStop,
  powerUser = false,
  onTogglePowerUser,
}: ChatInputProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [voiceErr, setVoiceErr] = useState<string | null>(null);
  const [pathPickerErr, setPathPickerErr] = useState<string | null>(null);
  const [screenshotErr, setScreenshotErr] = useState<string | null>(null);
  const [pathMenuOpen, setPathMenuOpen] = useState(false);
  const [screenshotMenuOpen, setScreenshotMenuOpen] = useState(false);
  const [needsModelDownload, setNeedsModelDownload] = useState(false);
  const errTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pathErrTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const screenshotErrTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleVoiceErr = useCallback(
    (err: string) => {
      // The Python backend returns ``error: "stt_model_missing"`` when the
      // GGML file isn't on disk yet (first launch). Surface that as the
      // download confirm banner instead of a generic red error.
      if (err.includes("stt_model_missing") || err.includes("STT_MODEL_MISSING")) {
        setVoiceErr(null);
        setNeedsModelDownload(true);
        return;
      }
      const display = err.includes("no_stt_provider") ? t("chat.voiceNoProvider") : err;
      setVoiceErr(display);
      if (errTimerRef.current) clearTimeout(errTimerRef.current);
      errTimerRef.current = setTimeout(() => setVoiceErr(null), 5000);
    },
    [t]
  );

  const handleTranscript = useCallback(
    (text: string) => {
      onChange(value ? `${value} ${text}` : text);
    },
    [value, onChange]
  );

  const {
    recorderState,
    durationMs,
    mimeTypeSupported,
    start,
    stop,
    isLocalModelReady,
    downloadLocalModel,
  } = useVoiceRecorder({
    onTranscript: handleTranscript,
    onError: handleVoiceErr,
  });

  const handleMicPress = useCallback(async () => {
    if (recorderState === "recording") {
      stop();
      return;
    }
    if (recorderState !== "idle") return;
    setVoiceErr(null);
    // Probe local model: if not on disk and no banner shown yet, prompt
    // the user before pulling 60 MB. The check is a single Tauri RT call,
    // not a network round-trip.
    const ready = await isLocalModelReady();
    if (!ready) {
      setNeedsModelDownload(true);
      return;
    }
    void start();
  }, [recorderState, isLocalModelReady, start, stop]);

  const handleConfirmDownload = useCallback(async () => {
    setNeedsModelDownload(false);
    const ok = await downloadLocalModel();
    if (ok) {
      void start();
    }
  }, [downloadLocalModel, start]);

  const handleCancelDownload = useCallback(() => {
    setNeedsModelDownload(false);
  }, []);

  useEffect(() => {
    return () => {
      if (errTimerRef.current) clearTimeout(errTimerRef.current);
      if (pathErrTimerRef.current) clearTimeout(pathErrTimerRef.current);
      if (screenshotErrTimerRef.current) clearTimeout(screenshotErrTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!pathMenuOpen && !screenshotMenuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPathMenuOpen(false);
        setScreenshotMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pathMenuOpen, screenshotMenuOpen]);

  const flashPathPickerErr = useCallback((msg: string) => {
    setPathPickerErr(msg);
    if (pathErrTimerRef.current) clearTimeout(pathErrTimerRef.current);
    pathErrTimerRef.current = setTimeout(() => setPathPickerErr(null), 4000);
  }, []);

  const flashScreenshotErr = useCallback((msg: string) => {
    setScreenshotErr(msg);
    if (screenshotErrTimerRef.current) clearTimeout(screenshotErrTimerRef.current);
    screenshotErrTimerRef.current = setTimeout(() => setScreenshotErr(null), 4000);
  }, []);

  const insertPathIntoPrompt = useCallback(
    (path: string) => {
      const ta = textareaRef.current;
      if (!ta) {
        onChange(value ? `${value}${/\s$/.test(value) ? "" : " "}${path}` : path);
        return;
      }
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const before = value.slice(0, start);
      const after = value.slice(end);
      const needsSpace = before.length > 0 && !/\s$/.test(before);
      const insert = `${needsSpace ? " " : ""}${path}`;
      const next = `${before}${insert}${after}`;
      onChange(next);
      requestAnimationFrame(() => {
        ta.focus();
        const pos = start + insert.length;
        ta.setSelectionRange(pos, pos);
      });
    },
    [value, onChange]
  );

  const handlePickPath = useCallback(
    async (kind: "folder" | "file") => {
      setPathMenuOpen(false);
      if (!isTauri()) {
        flashPathPickerErr(t("chat.insertPathNeedsApp"));
        return;
      }
      try {
        const selected = await open({
          directory: kind === "folder",
          multiple: false,
          title: kind === "folder" ? t("chat.insertPathFolder") : t("chat.insertPathFile"),
        });
        if (selected == null) return;
        const p = typeof selected === "string" ? selected : selected[0];
        if (p) insertPathIntoPrompt(p);
      } catch {
        flashPathPickerErr(t("chat.insertPathFailed"));
      }
    },
    [flashPathPickerErr, insertPathIntoPrompt, t]
  );

  const handleScreenshotAction = useCallback(
    async (mode: "region" | "fullscreen") => {
      setScreenshotMenuOpen(false);
      if (!isTauri()) {
        flashScreenshotErr(t("chat.insertPathNeedsApp"));
        return;
      }
      try {
        if (mode === "region") {
          await showCaptureOverlay();
        } else {
          await captureFullscreen();
        }
      } catch {
        flashScreenshotErr(t("chat.screenshotFailed"));
      }
    },
    [flashScreenshotErr, t]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!sending) {
          const canSend = value.trim() || pendingAttachmentNames.length > 0;
          if (canSend) {
            onSend();
          }
        }
      }
    },
    [onSend, sending, value, pendingAttachmentNames.length]
  );

  const canSend = !sending && (value.trim() || pendingAttachmentNames.length > 0);

  return (
    <div className="shrink-0 bg-zinc-50/90 px-3 pb-5 pt-2 dark:bg-[#0F172A]">
      <div
        className={cn(
          "mx-auto max-w-3xl rounded-lg border border-zinc-200/95 bg-white",
          "shadow-[0_2px_12px_rgba(0,0,0,0.05)]",
          "dark:border-zinc-700 dark:bg-zinc-800/50"
        )}
      >
        {pendingAttachmentNames.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-b border-zinc-100 px-3 py-2 dark:border-zinc-800">
            {pendingAttachmentNames.map((name, i) => (
              <span
                key={`${name}-${i}`}
                className="inline-flex max-w-[min(100%,14rem)] items-center gap-1 rounded-full bg-zinc-100 pl-2.5 pr-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                <span className="truncate" title={name}>
                  {name}
                </span>
                <button
                  type="button"
                  disabled={sending}
                  onClick={() => onRemoveAttachment(i)}
                  className="shrink-0 rounded-full p-0.5 text-zinc-400 hover:text-zinc-700 disabled:opacity-40 dark:hover:text-zinc-200"
                  aria-label={t("chat.removeAttachment")}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder={placeholder ?? t("chat.placeholder")}
          disabled={sending}
          className="max-h-[200px] min-h-[3.25rem] w-full resize-none bg-transparent px-4 py-3.5 text-[15px] leading-relaxed text-zinc-900 placeholder:text-zinc-400 outline-none disabled:opacity-50 dark:text-zinc-100 dark:placeholder:text-zinc-500"
        />

        <div className="flex items-center justify-between gap-2 border-t border-zinc-100 px-2.5 pb-2.5 pt-1 dark:border-zinc-800">
          <div className="flex items-center gap-1 overflow-visible">
            <div className="relative">
              <button
                type="button"
                disabled={sending}
                onClick={() => {
                  if (sending) return;
                  setScreenshotMenuOpen(false);
                  setPathMenuOpen((o) => !o);
                }}
                className="group relative flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 active:scale-[0.98] dark:text-zinc-400 dark:hover:bg-zinc-700/80 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label={t("chat.insertPath")}
                aria-expanded={pathMenuOpen}
                aria-haspopup="menu"
              >
                <FolderOpen className="h-5 w-5" strokeWidth={2} />
                <span className="pointer-events-none absolute -bottom-9 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded-lg bg-white/80 px-3 py-1.5 text-xs font-medium text-zinc-600 opacity-0 shadow-md ring-1 ring-zinc-200/60 backdrop-blur-sm transition-opacity group-hover:opacity-100 dark:bg-zinc-900/70 dark:text-zinc-300 dark:ring-zinc-700/60">
                  {t("chat.insertPathHint")}
                </span>
              </button>
              {pathMenuOpen && (
                <>
                  <div
                    role="presentation"
                    className="fixed inset-0 z-[15]"
                    onClick={() => setPathMenuOpen(false)}
                  />
                  <div
                    role="menu"
                    className="absolute bottom-full left-0 z-[25] mb-1 min-w-[10.5rem] overflow-hidden rounded-lg border border-zinc-200/95 bg-white py-1 shadow-lg dark:border-zinc-600 dark:bg-zinc-900"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className="block w-full px-3 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      onClick={() => void handlePickPath("folder")}
                    >
                      {t("chat.insertPathFolder")}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      className="block w-full px-3 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      onClick={() => void handlePickPath("file")}
                    >
                      {t("chat.insertPathFile")}
                    </button>
                  </div>
                </>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept="image/*,text/*,.csv,.c,.cpp,.cs,.css,.doc,.docx,.go,.h,.hpp,.html,.java,.js,.jsx,.json,.log,.md,.pdf,.ppt,.pptx,.ps1,.py,.rs,.sh,.ts,.tsx,.xml,.yaml,.yml,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              multiple
              onChange={(e) => {
                onFilesPicked(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={sending}
              onClick={() => fileRef.current?.click()}
              className="group relative flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 active:scale-[0.98] dark:text-zinc-400 dark:hover:bg-zinc-700/80 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={t("chat.attach")}
            >
              <Paperclip className="h-5 w-5" />
              {/* Tooltip */}
              <span className="pointer-events-none absolute -bottom-9 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded-lg bg-white/80 px-3 py-1.5 text-xs font-medium text-zinc-600 opacity-0 shadow-md ring-1 ring-zinc-200/60 backdrop-blur-sm transition-opacity group-hover:opacity-100 dark:bg-zinc-900/70 dark:text-zinc-300 dark:ring-zinc-700/60">
                {t("chat.attachHint")}
              </span>
            </button>
            <div className="relative">
              <button
                type="button"
                disabled={sending}
                onClick={() => {
                  if (sending) return;
                  setPathMenuOpen(false);
                  setScreenshotMenuOpen((o) => !o);
                }}
                className="group relative flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 active:scale-[0.98] dark:text-zinc-400 dark:hover:bg-zinc-700/80 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label={t("chat.screenshot")}
                aria-expanded={screenshotMenuOpen}
                aria-haspopup="menu"
              >
                <Crop className="h-5 w-5" strokeWidth={2} />
                <span className="pointer-events-none absolute -bottom-9 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded-lg bg-white/80 px-3 py-1.5 text-xs font-medium text-zinc-600 opacity-0 shadow-md ring-1 ring-zinc-200/60 backdrop-blur-sm transition-opacity group-hover:opacity-100 dark:bg-zinc-900/70 dark:text-zinc-300 dark:ring-zinc-700/60">
                  {t("chat.screenshotHint")}
                </span>
              </button>
              {screenshotMenuOpen && (
                <>
                  <div
                    role="presentation"
                    className="fixed inset-0 z-[15]"
                    onClick={() => setScreenshotMenuOpen(false)}
                  />
                  <div
                    role="menu"
                    className="absolute bottom-full left-0 z-[25] mb-1 min-w-[10.5rem] overflow-hidden rounded-lg border border-zinc-200/95 bg-white py-1 shadow-lg dark:border-zinc-600 dark:bg-zinc-900"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className="block w-full px-3 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      onClick={() => void handleScreenshotAction("region")}
                    >
                      {t("chat.screenshotRegion")}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      className="block w-full px-3 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
                      onClick={() => void handleScreenshotAction("fullscreen")}
                    >
                      {t("chat.screenshotFullscreen")}
                    </button>
                  </div>
                </>
              )}
            </div>
            {mimeTypeSupported && (
              <VoiceButton
                state={recorderState}
                durationMs={durationMs}
                disabled={sending}
                onPress={() => void handleMicPress()}
              />
            )}
          </div>

          <div className="flex items-center gap-2">
            {sending && onStop && (
              <button
                type="button"
                onClick={() => void onStop()}
                className={cn(
                  "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white",
                  "text-zinc-600 shadow-sm transition active:scale-[0.98]",
                  "hover:border-red-200/90 hover:bg-red-50/90 hover:text-red-600",
                  "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
                  "dark:hover:border-red-900/50 dark:hover:bg-red-950/30 dark:hover:text-red-400"
                )}
                title={t("chat.stop")}
                aria-label={t("chat.stop")}
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            )}
            <button
              type="button"
              onClick={() => void onSend()}
              disabled={!canSend}
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-sky-600 text-white shadow-sm transition hover:opacity-90 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400 dark:bg-[#3B5BC7] dark:disabled:bg-zinc-800 dark:disabled:text-zinc-500"
              title={sending ? t("chat.sending") : t("chat.send")}
              aria-label={sending ? t("chat.sending") : t("chat.send")}
            >
              <ArrowUp className="h-5 w-5" strokeWidth={2.25} />
            </button>
          </div>
        </div>
      </div>
      {needsModelDownload && (
        <div className="mx-auto mt-1.5 flex max-w-3xl flex-wrap items-center justify-between gap-2 rounded-md border border-sky-200 bg-sky-50/70 px-3 py-2 text-xs text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-100">
          <span className="leading-relaxed">{t("chat.voiceModelConfirm")}</span>
          <span className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={handleCancelDownload}
              className="rounded px-2 py-1 text-zinc-600 transition hover:bg-zinc-200/60 dark:text-zinc-300 dark:hover:bg-zinc-700/60"
            >
              {t("chat.voiceModelCancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleConfirmDownload()}
              className="rounded bg-sky-600 px-2 py-1 font-medium text-white shadow-sm transition hover:opacity-90 dark:bg-[#3B5BC7]"
            >
              {t("chat.voiceModelDownload")}
            </button>
          </span>
        </div>
      )}
      {voiceErr && (
        <p className="mx-auto mt-1.5 max-w-3xl text-xs text-red-500 dark:text-red-400">
          {voiceErr}
        </p>
      )}
      {pathPickerErr && (
        <p className="mx-auto mt-1.5 max-w-3xl text-xs text-amber-700 dark:text-amber-400">
          {pathPickerErr}
        </p>
      )}
      {screenshotErr && (
        <p className="mx-auto mt-1.5 max-w-3xl text-xs text-amber-700 dark:text-amber-400">
          {screenshotErr}
        </p>
      )}
      <div className="mx-auto mt-2.5 flex max-w-3xl items-center justify-between gap-3">
        <p className="text-xs leading-[1.5] text-zinc-400 dark:text-zinc-500">{t("chat.hint")}</p>
        {onTogglePowerUser && (
          <button
            type="button"
            onClick={() => onTogglePowerUser(!powerUser)}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-zinc-500 transition hover:bg-zinc-200/50 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-200"
            title={t("settings.powerTitle")}
          >
            <Zap
              className={cn(
                "h-3.5 w-3.5 transition",
                powerUser ? "text-amber-500 dark:text-amber-400" : "text-zinc-400 dark:text-zinc-500"
              )}
              strokeWidth={2.5}
            />
            <span>{t("settings.powerTitle")}</span>
            <Toggle value={powerUser} onChange={(v) => onTogglePowerUser(v)} />
          </button>
        )}
      </div>
    </div>
  );
}
