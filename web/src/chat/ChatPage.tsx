import { useCallback, useEffect } from "react";
import { usePowerUser, setPowerUser } from "../lib/powerUser";
import { useLocation, useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { ask } from "@tauri-apps/plugin-dialog";
import { AppScaffold } from "../components/AppScaffold";
import { useI18n } from "../lib/i18n";
import { ChatInput } from "./ChatInput";
import { ChatMessageList } from "./ChatMessageList";
import { ChatSidebar } from "./ChatSidebar";
import {
  armPendingChatSecretGateBypass,
  getDraftPrompt,
  isFromOnboarding,
  takePendingChatSecretGateBypass,
} from "../lib/chatLocationState";
import { getAllowChatWithoutApi } from "../lib/apiKeyGate";
import { ShellModal } from "../components/ShellModal";
import { clearDraft } from "../lib/store";
import { useHermesReadiness } from "./hooks/useHermesReadiness";
import { useSessions } from "./hooks/useSessions";
import { useChatState } from "./hooks/useChatState";
import { useSendMessage } from "./hooks/useSendMessage";
import { type CaptureDonePayload } from "../capture/capture-api";

export function ChatPage() {
  const { t } = useI18n();
  const nav = useNavigate();
  const location = useLocation();
  const powerUser = usePowerUser();

  const { hermesReady, bootErr } = useHermesReadiness();
  const { sessions, listLoading, loadSessions, deleteSession } = useSessions({ hermesReady });
  const {
    activeSessionId,
    setActiveSessionId,
    threadModel,
    setThreadModel,
    messages,
    setMessages,
    sendErr,
    setSendErr,
    apiRequiredOpen,
    setApiRequiredOpen,
    onNewChat,
    onPickSession,
    onDeleteSession,
  } = useChatState({ loadSessions });
  const {
    input,
    setInput,
    sending,
    progress,
    pendingAttachments,
    onAddFiles,
    onAddCaptureAttachment,
    onRemoveAttachment,
    onSend,
    onStopAgent,
  } = useSendMessage({
    activeSessionId,
    setActiveSessionId,
    threadModel,
    setThreadModel,
    setMessages,
    loadSessions,
    setApiRequiredOpen,
    setSendErr,
  });

  useEffect(() => {
    if (isFromOnboarding(location.state)) {
      armPendingChatSecretGateBypass();
      clearDraft();
      nav("/chat", { replace: true, state: {} });
      return;
    }
    if (takePendingChatSecretGateBypass()) {
      return;
    }
    const gate = async () => {
      try {
        const ok = await invoke<boolean>("cmd_has_secret");
        if (ok) return;
        if (getAllowChatWithoutApi()) return;
        nav("/onboarding/welcome", { replace: true });
      } catch {
        nav("/onboarding/welcome", { replace: true });
      }
    };
    void gate();
  }, [nav, location.state]);

  useEffect(() => {
    void (async () => {
      try {
        const v = await invoke<boolean>("cmd_get_power_user");
        setPowerUser(!!v);
      } catch {
        /* optional */
      }
    })();
  }, []);

  useEffect(() => {
    const draft = getDraftPrompt(location.state);
    if (!draft) return;
    setInput(draft);
    nav("/chat", { replace: true, state: {} });
  }, [location.state, nav, setInput]);

  // Listen for screenshot capture events from the overlay window.
  useEffect(() => {
    const unlisten = listen<CaptureDonePayload>("capture-done", (event) => {
      const { name, mime, data } = event.payload;
      onAddCaptureAttachment({ name, mime, data });
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [onAddCaptureAttachment]);

  // Poll for desktop deliveries (cron job output, send_message to "desktop")
  // and inject them into the chat stream as system-style assistant messages.
  // Toast notifications fire from the Rust side (bridge.rs); this effect is
  // the in-app counterpart so the user sees the full content even if they
  // missed the toast.
  useEffect(() => {
    let cancelled = false;
    const streamHeader = t("cron.streamTitle");
    const tick = async () => {
      try {
        const msgs = await invoke<Array<{ title: string; message: string }>>(
          "cmd_desktop_messages",
        );
        if (cancelled || !msgs || msgs.length === 0) return;
        const now = Date.now();
        setMessages((prev) => [
          ...prev,
          ...msgs.map((m, idx) => ({
            id: `cron-${now}-${idx}`,
            role: "assistant" as const,
            text: `**${streamHeader}: ${m.title || ""}**\n\n${m.message || ""}`,
            timestamp: now / 1000,
          })),
        ]);
      } catch (e) {
        console.debug("cmd_desktop_messages poll skipped:", e);
      }
    };
    void tick();
    const handle = window.setInterval(() => {
      void tick();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [setMessages, t]);

  const togglePowerUser = useCallback(async (next: boolean) => {
    if (next) {
      const ok = await ask(t("settings.powerAsk"), {
        title: t("settings.powerAskTitle"),
        kind: "warning",
      });
      if (!ok) return;
    }
    try {
      await invoke("cmd_set_power_user", { enabled: next });
      setPowerUser(next);
    } catch (e) {
      console.error(e);
    }
  }, [t]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(t("chat.confirmDelete"))) {
      return;
    }
    try {
      await deleteSession(id);
      await onDeleteSession(id);
    } catch (err) {
      console.error(err);
      setSendErr(t("chat.errDelete"));
    }
  };

  if (bootErr) {
    return (
      <AppScaffold surface="chat" className="flex h-full flex-col items-center justify-center px-6 text-center">
        <p className="max-w-md text-sm text-zinc-600 dark:text-zinc-400">{bootErr}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 text-sm text-sky-600 underline-offset-2 dark:text-sky-400"
        >
          {t("chat.reload")}
        </button>
      </AppScaffold>
    );
  }

  if (!hermesReady) {
    return (
      <AppScaffold surface="chat" className="flex h-full flex-col items-center justify-center">
        <p className="hd-hint">
          <span aria-hidden>⏳</span>
          {t("chat.waitingHermes")}
        </p>
        <div className="mt-5 h-1 w-40 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-zinc-400 dark:bg-zinc-600" />
        </div>
      </AppScaffold>
    );
  }

  return (
    <AppScaffold surface="chat" className="flex h-full min-h-0 flex-col">
      <ShellModal
        open={apiRequiredOpen}
        onClose={() => setApiRequiredOpen(false)}
        title={t("chat.apiRequiredTitle")}
      >
        <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{t("chat.apiRequiredBody")}</p>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
            onClick={() => setApiRequiredOpen(false)}
          >
            {t("chat.apiRequiredClose")}
          </button>
          <button
            type="button"
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900"
            onClick={() => {
              setApiRequiredOpen(false);
              nav("/onboarding/welcome", { replace: true });
            }}
          >
            {t("chat.apiRequiredGoSetup")}
          </button>
        </div>
      </ShellModal>
      <div className="flex min-h-0 flex-1">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          loading={listLoading}
          onNewChat={onNewChat}
          onSelectSession={onPickSession}
          onDeleteSession={handleDelete}
        />
        <main className="flex-1 min-w-0 flex flex-col">
          <ChatMessageList
            messages={messages}
            sending={sending}
            sendErr={sendErr}
            progress={progress}
          />
          <ChatInput
            value={input}
            onChange={setInput}
            onSend={onSend}
            sending={sending}
            pendingAttachmentNames={pendingAttachments.map((a) => a.name)}
            onRemoveAttachment={onRemoveAttachment}
            onFilesPicked={onAddFiles}
            onStop={onStopAgent}
            powerUser={powerUser}
            onTogglePowerUser={togglePowerUser}
          />
        </main>
      </div>
    </AppScaffold>
  );
}
