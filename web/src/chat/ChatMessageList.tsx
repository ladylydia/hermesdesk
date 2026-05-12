import { useEffect, useRef } from "react";
import { useI18n } from "../lib/i18n";
import type { UiMsg } from "./chat-api";
import { AgentProgress } from "./AgentProgress";
import { ChatMessage } from "./ChatMessage";
import { cn } from "../lib/cn";
import type { AgentProgressState } from "./hooks/useAgentProgress";

interface ChatMessageListProps {
  messages: UiMsg[];
  sending?: boolean;
  sendErr?: string | null;
  progress?: AgentProgressState | null;
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

function EmptyState() {
  const { t, locale } = useI18n();
  const brand = t("brand");
  const wordmarkBase =
    locale === "zh" ? "/kabuqina_logo_chinese" : "/kabuqina_logo_english";
  const greeting = t("chat.greeting", { name: brand });
  const greetingParts = greeting.split(brand);
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-center px-6 py-8 sm:py-10">
      <div className="flex w-full max-w-lg translate-y-5 flex-col items-center text-center sm:translate-y-7">
        <div className="mb-5 flex flex-col items-center sm:mb-6">
          <picture className="block leading-none">
            <source type="image/avif" srcSet={`${wordmarkBase}.avif`} />
            <source type="image/webp" srcSet={`${wordmarkBase}.webp`} />
            <img
              src={`${wordmarkBase}.webp`}
              alt={brand}
              className="mx-auto block h-auto w-full max-w-[220px] object-contain object-center dark:opacity-95 sm:max-w-[260px]"
              width={260}
              height={80}
              decoding="async"
            />
          </picture>
          <p className="mt-4 text-sm tracking-[0.2em] text-zinc-400 dark:text-zinc-500">
            {greetingParts[0]}
            <span className="font-medium text-sky-600 dark:text-sky-400">{brand}</span>
            {greetingParts[1]}
          </p>
        </div>
      </div>
    </div>
  );
}

export function ChatMessageList({
  messages,
  sending = false,
  sendErr,
  progress,
}: ChatMessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, [messages, sending, progress?.nextSeq, progress?.status]);

  const isEmpty = messages.length === 0 && !sendErr;
  const pendingAssistant = messages.find((m) => m.id === "pending-assistant");
  const completedMessages = messages.filter((m) => m.id !== "pending-assistant");
  const pendingVisibleText = !!pendingAssistant?.text.trim().replace(/^[.…]+$/, "");

  return (
    <div
      className={cn(
        "min-h-0 flex-1 overflow-y-auto bg-zinc-50/80 dark:bg-[#0F172A]",
        isEmpty && "flex min-h-0 flex-col"
      )}
    >
      {isEmpty ? (
        <EmptyState />
      ) : (
        <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:space-y-6 sm:px-5">
          {completedMessages.map((m) => (
            <ChatMessage
              key={m.id}
              role={m.role}
              text={m.text}
              model={m.model}
              timestamp={m.timestamp}
              streaming={false}
            />
          ))}
          {progress?.running && <AgentProgress progress={progress} />}
          {pendingAssistant && (
            <ChatMessage
              key={pendingAssistant.id}
              role={pendingAssistant.role}
              text={pendingAssistant.text}
              model={pendingAssistant.model}
              timestamp={pendingAssistant.timestamp}
              streaming={sending}
            />
          )}
          {sending && !progress?.running && !pendingVisibleText && <TypingIndicator />}
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
