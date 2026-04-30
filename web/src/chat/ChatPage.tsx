import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { AppScaffold } from "../components/AppScaffold";
import { useI18n } from "../lib/i18n";
import {
  cmdChatSend,
  cmdDeleteSession,
  cmdDeskStop,
  cmdGetHermesPort,
  cmdGetSessionMessages,
  cmdGetSessions,
  fileToDeskAttachment,
  isRecord,
  parseChatSend,
  type DeskAttachmentPayload,
  type MessageRow,
  type SessionRow,
  type UiMsg,
} from "./chat-api";
import { ChatInput } from "./ChatInput";
import { ChatMessageList } from "./ChatMessageList";
import { ChatSidebar } from "./ChatSidebar";
import { isFromOnboarding } from "../lib/chatLocationState";
import { getAllowChatWithoutApi } from "../lib/apiKeyGate";
import { ShellModal } from "../components/ShellModal";

const LAST_SESSION_KEY = "hermesdesk.shell.chat.lastSessionId";

function contentToString(content: unknown): string {
  if (content == null) {
    return "";
  }
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (typeof c === "string") {
          return c;
        }
        if (c && typeof c === "object" && "text" in c) {
          return String((c as { text?: unknown }).text ?? "");
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (typeof content === "object" && "text" in (content as object)) {
    return String((content as { text?: unknown }).text);
  }
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}

function rowsToUiMessages(rows: MessageRow[], sessionModel: string): UiMsg[] {
  const out: UiMsg[] = [];
  let n = 0;
  const mdl = sessionModel.trim();
  for (const m of rows) {
    const role = m.role;
    if (role === "session_meta" || role === "tool") {
      continue;
    }
    if (role !== "user" && role !== "assistant" && role !== "system") {
      continue;
    }
    const text = contentToString(m.content).trim();
    if (!text && role !== "assistant") {
      continue;
    }
    if (role === "system") {
      out.push({
        id: `s-${n++}`,
        role: "assistant",
        text: `_(system)_\n${text || "—"}`,
        timestamp: typeof m.timestamp === "number" ? m.timestamp : undefined,
        model: mdl || undefined,
      });
      continue;
    }
    out.push({
      id: `m-${n++}`,
      role: role as "user" | "assistant",
      text: text || (role === "assistant" ? "…" : ""),
      timestamp: typeof m.timestamp === "number" ? m.timestamp : undefined,
      model: role === "assistant" && mdl ? mdl : undefined,
    });
  }
  return out;
}

export function ChatPage() {
  const { t } = useI18n();
  const nav = useNavigate();
  const location = useLocation();
  /** After wizard completion we skip the immediate `cmd_has_secret` check once (keyring/bridge timing). */
  const skipKeyGuardOnceRef = useRef(false);
  const [hermesReady, setHermesReady] = useState(false);
  const [bootErr, setBootErr] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  /** `null` = 新对话；从侧栏点历史会话时由 `loadThread` 设置。进入页面默认不恢复上次线程。 */
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  /** Session default model (list_sessions / send response); assistant rows use this when history has no per-msg model. */
  const [threadModel, setThreadModel] = useState("");
  const [messages, setMessages] = useState<UiMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [listLoading, setListLoading] = useState(true);
  const [sendErr, setSendErr] = useState<string | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<DeskAttachmentPayload[]>([]);
  const [apiRequiredOpen, setApiRequiredOpen] = useState(false);
  const stopTurnRef = useRef(false);
  /** Session id for the in-flight request (state may not have flushed before Stop). */
  const inFlightSessionIdRef = useRef<string | null>(null);

  const loadSessions = useCallback(async () => {
    setListLoading(true);
    try {
      const r = await cmdGetSessions(50, 0);
      setSessions(r.sessions ?? []);
    } catch (e) {
      console.error(e);
      setSessions([]);
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      for (let i = 0; i < 120; i++) {
        if (cancel) {
          return;
        }
        try {
          const p = await cmdGetHermesPort();
          if (p != null) {
            if (!cancel) {
              setHermesReady(true);
              setBootErr(null);
            }
            return;
          }
        } catch {
          /* keep polling */
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      if (!cancel) {
        setBootErr(t("chat.errHermesTimeout"));
      }
    };
    void tick();
    return () => {
      cancel = true;
    };
  }, [t]);

  useEffect(() => {
    if (!hermesReady) {
      return;
    }
    void loadSessions();
  }, [hermesReady, loadSessions]);

  const persistSession = (id: string | null) => {
    if (typeof window === "undefined" || !window.localStorage) {
      return;
    }
    if (id) {
      window.localStorage.setItem(LAST_SESSION_KEY, id);
    } else {
      window.localStorage.removeItem(LAST_SESSION_KEY);
    }
  };

  const loadThread = useCallback(
    async (sid: string) => {
      setSendErr(null);
      try {
        const [r, list] = await Promise.all([cmdGetSessionMessages(sid), cmdGetSessions(100, 0)]);
        const row = (list.sessions ?? []).find((s) => s.id === sid);
        const m = (row?.model ?? "").trim();
        setThreadModel(m);
        setMessages(rowsToUiMessages(r.messages ?? [], m));
        setActiveSessionId(sid);
        persistSession(sid);
        void loadSessions();
      } catch (e) {
        console.error(e);
        setSendErr(t("chat.errLoadThread"));
        setMessages([]);
        setThreadModel("");
        setActiveSessionId(null);
        persistSession(null);
      }
    },
    [loadSessions, t]
  );

  const onNewChat = () => {
    setActiveSessionId(null);
    setThreadModel("");
    setMessages([]);
    setSendErr(null);
    setInput("");
    setPendingAttachments([]);
    persistSession(null);
  };

  const onPickSession = (id: string) => {
    if (id === activeSessionId) {
      return;
    }
    void loadThread(id);
  };

  const onDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(t("chat.confirmDelete"))) {
      return;
    }
    try {
      await cmdDeleteSession(id);
      if (activeSessionId === id) {
        onNewChat();
      }
      await loadSessions();
    } catch (err) {
      console.error(err);
      setSendErr(t("chat.errDelete"));
    }
  };

  const onAddFiles = async (list: FileList | null) => {
    if (!list?.length) {
      return;
    }
    const out = [...pendingAttachments];
    for (let i = 0; i < list.length; i++) {
      if (out.length >= 6) {
        break;
      }
      const f = list[i];
      try {
        out.push(await fileToDeskAttachment(f));
      } catch (e) {
        console.error(e);
      }
    }
    setPendingAttachments(out);
  };

  const onStopAgent = async () => {
    const sid = inFlightSessionIdRef.current || activeSessionId;
    if (!sid) {
      return;
    }
    stopTurnRef.current = true;
    setSending(false);
    setMessages((m) => m.filter((x) => x.id !== "pending-assistant"));
    setSendErr(null);
    try {
      await cmdDeskStop(sid);
    } catch (e) {
      console.error(e);
      const msg =
        typeof e === "string"
          ? e
          : e && isRecord(e) && typeof e.message === "string"
            ? e.message
            : String(e);
      setSendErr(msg);
    }
  };

  const onSend = async () => {
    const text = input.trim();
    const atts = pendingAttachments;
    if (sending || (!text && !atts.length)) {
      return;
    }
    try {
      const hasKey = await invoke<boolean>("cmd_has_secret");
      if (!hasKey) {
        setApiRequiredOpen(true);
        return;
      }
    } catch {
      setApiRequiredOpen(true);
      return;
    }
    setSending(true);
    stopTurnRef.current = false;
    setSendErr(null);
    setInput("");
    setPendingAttachments([]);

    let sessionForSend = activeSessionId;
    if (!sessionForSend) {
      sessionForSend =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `desk-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      setActiveSessionId(sessionForSend);
      persistSession(sessionForSend);
    }
    inFlightSessionIdRef.current = sessionForSend;

    const attLabel =
      atts.length > 0
        ? atts.map((a) => `📎 ${a.name}`).join("\n")
        : "";
    const userText = [text, attLabel].filter(Boolean).join("\n");
    const nowSec = Math.floor(Date.now() / 1000);
    const userMsg: UiMsg = { id: `u-${Date.now()}`, role: "user", text: userText, timestamp: nowSec };
    setMessages((m) => [...m, userMsg]);
    const placeholder: UiMsg = {
      id: "pending-assistant",
      role: "assistant",
      text: "…",
      model: threadModel || undefined,
      timestamp: nowSec,
    };
    setMessages((m) => [...m, placeholder]);

    try {
      const raw = await cmdChatSend(text, sessionForSend, atts.length ? atts : null);
      const parsed = parseChatSend(raw);
      if (stopTurnRef.current) {
        setMessages((m) => m.filter((x) => x.id !== "pending-assistant"));
        return;
      }
      if (!parsed.ok) {
        setMessages((m) => m.filter((x) => x.id !== "pending-assistant"));
        setSendErr(parsed.err);
        return;
      }
      setActiveSessionId(parsed.sessionId);
      persistSession(parsed.sessionId);
      const resolvedModel = (parsed.model || "").trim() || threadModel;
      if (resolvedModel) {
        setThreadModel(resolvedModel);
      }
      if (stopTurnRef.current) {
        setMessages((m) => m.filter((x) => x.id !== "pending-assistant"));
        return;
      }
      setMessages((m) =>
        m.map((x) =>
          x.id === "pending-assistant"
            ? {
                ...x,
                id: `a-${Date.now()}`,
                text: parsed.text,
                model: resolvedModel || undefined,
                timestamp: Math.floor(Date.now() / 1000),
              }
            : x
        )
      );
      void loadSessions();
    } catch (e) {
      if (!stopTurnRef.current) {
        setMessages((m) => m.filter((x) => x.id !== "pending-assistant"));
        const msg =
          typeof e === "string"
            ? e
            : e && isRecord(e) && typeof e.message === "string"
              ? e.message
              : String(e);
        setSendErr(msg);
      }
    } finally {
      setSending(false);
      stopTurnRef.current = false;
      inFlightSessionIdRef.current = null;
    }
  };

  useEffect(() => {
    if (isFromOnboarding(location.state)) {
      skipKeyGuardOnceRef.current = true;
      nav("/chat", { replace: true, state: {} });
      return;
    }
    if (skipKeyGuardOnceRef.current) {
      skipKeyGuardOnceRef.current = false;
      return;
    }
    const gate = async () => {
      try {
        const ok = await invoke<boolean>("cmd_has_secret");
        if (ok) return;
        if (getAllowChatWithoutApi()) return;
        nav("/onboarding/mode", { replace: true });
      } catch {
        nav("/onboarding/mode", { replace: true });
      }
    };
    void gate();
  }, [nav, location.state]);

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
              nav("/onboarding/mode", { replace: true });
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
          onDeleteSession={onDelete}
        />
        <main className="flex-1 min-w-0 flex flex-col">
          <ChatMessageList
            messages={messages}
            sending={sending}
            sendErr={sendErr}
            onPromptClick={(text) => setInput(text)}
          />
          <ChatInput
            value={input}
            onChange={setInput}
            onSend={onSend}
            sending={sending}
            pendingAttachmentNames={pendingAttachments.map((a) => a.name)}
            onRemoveAttachment={(i) =>
              setPendingAttachments((prev) => prev.filter((_, j) => j !== i))
            }
            onFilesPicked={onAddFiles}
            onStop={onStopAgent}
          />
        </main>
      </div>
    </AppScaffold>
  );
}
