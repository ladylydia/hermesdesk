import { useEffect, useRef } from "react";
import { BookOpen, Code2, FileText } from "lucide-react";
import { useI18n } from "../lib/i18n";
import type { UiMsg } from "./chat-api";
import { ChatMessage } from "./ChatMessage";
import { cn } from "../lib/cn";

interface ChatMessageListProps {
  messages: UiMsg[];
  sending?: boolean;
  sendErr?: string | null;
  onPromptClick?: (text: string) => void;
}

function TypingIndicator() {
  const { t } = useI18n();
  return (
    <div className="flex justify-start">
      <div className="max-w-[min(100%,42rem)] rounded-lg border border-zinc-200/90 bg-zinc-100/80 px-4 py-3 shadow-sm dark:border-zinc-700 dark:bg-zinc-800/60">
        <p className="mb-2 text-xs text-zinc-400 dark:text-zinc-500">
          {t("chat.typingStatus")}…
        </p>
        <div className="flex h-4 items-center gap-1" aria-hidden>
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-300 dark:bg-zinc-600" style={{ animationDelay: "0ms" }} />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-300 dark:bg-zinc-600" style={{ animationDelay: "150ms" }} />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-300 dark:bg-zinc-600" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  );
}

const PROMPT_ICONS = [Code2, BookOpen, FileText] as const;

function EmptyState({ onPromptClick }: { onPromptClick?: (text: string) => void }) {
  const { t } = useI18n();
  const brand = t("brand");
  const prompts = [
    t("chat.prompt1") || "帮我写一段代码",
    t("chat.prompt2") || "解释一下这个概念",
    t("chat.prompt3") || "总结一下文档内容",
  ];
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-center px-6 py-8 sm:py-10">
      <div className="flex w-full max-w-lg translate-y-5 flex-col items-center text-center sm:translate-y-7">
        <img
          src="/hi-agent-wordmark.png"
          alt={brand}
          className="mb-6 h-auto max-h-14 w-auto max-w-[min(85vw,280px)] object-contain object-center sm:mb-7 sm:max-h-16 sm:max-w-[320px] dark:opacity-95"
          decoding="async"
        />
        <div
          className="flex flex-wrap justify-center gap-2.5"
          role="group"
          aria-label={t("chat.emptyActionsLabel")}
        >
          {prompts.map((p, i) => {
            const Icon = PROMPT_ICONS[i] ?? Code2;
            return (
              <button
                key={p}
                type="button"
                onClick={() => onPromptClick?.(p)}
                className={cn(
                  "inline-flex max-w-full items-center gap-2.5 rounded-[var(--radius-shell-pill)] border border-zinc-200/90 bg-white",
                  "px-4 py-3 text-sm font-medium leading-snug text-zinc-700 shadow-sm transition",
                  "hover:border-sky-300/80 hover:bg-sky-50/80 active:scale-[0.98] dark:border-zinc-600 dark:bg-zinc-800/40",
                  "dark:text-zinc-200 dark:hover:border-sky-700/50 dark:hover:bg-zinc-800/80"
                )}
              >
                <Icon className="h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400" aria-hidden />
                <span className="text-left">{p}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function ChatMessageList({
  messages,
  sending = false,
  sendErr,
  onPromptClick,
}: ChatMessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, [messages, sending]);

  const isEmpty = messages.length === 0 && !sendErr;

  return (
    <div
      className={cn(
        "min-h-0 flex-1 overflow-y-auto bg-zinc-50/80 dark:bg-[#0F172A]",
        isEmpty && "flex min-h-0 flex-col"
      )}
    >
      {isEmpty ? (
        <EmptyState onPromptClick={onPromptClick} />
      ) : (
        <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:space-y-6 sm:px-5">
          {messages.map((m) => (
            <ChatMessage
              key={m.id}
              role={m.role}
              text={m.text}
              model={m.model}
              timestamp={m.timestamp}
            />
          ))}
          {sending && messages[messages.length - 1]?.role !== "assistant" && <TypingIndicator />}
          {sendErr && (
            <div className="hd-semantic-error rounded-lg px-3 py-2 text-sm">
              {sendErr}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
