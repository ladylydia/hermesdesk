import { useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { ChatMarkdown } from "./ChatMarkdown";
import { cn } from "../lib/cn";

export interface ChatMessageProps {
  role: "user" | "assistant";
  text: string;
  model?: string;
  /** Unix seconds or ms (see `MessageRow.timestamp`) */
  timestamp?: number;
}

function toMillis(ts: number): number {
  if (!Number.isFinite(ts)) {
    return Date.now();
  }
  return ts > 1e12 ? ts : ts * 1000;
}

function formatChatTime(ts: number, locale: "zh" | "en"): string {
  return new Date(toMillis(ts)).toLocaleString(locale === "en" ? "en-US" : "zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function copyToClipboard(s: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(s);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement("textarea");
      ta.value = s;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      resolve();
    } catch (e) {
      reject(e);
    }
  });
}

/** 可复制的正文中不能只有占位的一两个省略号。 */
function canCopyAssistantText(raw: string): boolean {
  const t = raw.trim();
  if (!t) {
    return false;
  }
  if (t === "…" || t === "..." || t === "\u2026" || t === "\u22ef") {
    return false;
  }
  return true;
}

/**
 * 底栏内复制：带「复制」文字 + 图标，始终渲染（无内容时 disabled），避免小图标/占位逻辑导致「完全看不到」。
 */
function MessageCopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  const canCopy = canCopyAssistantText(text);

  const onCopy = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!canCopyAssistantText(text)) {
        return;
      }
      void copyToClipboard(text).then(() => {
        setDone(true);
        window.setTimeout(() => setDone(false), 1800);
      });
    },
    [text]
  );

  return (
    <div className="group relative inline-flex max-w-full shrink-0">
      <button
        type="button"
        disabled={!canCopy}
        onClick={onCopy}
        title={!canCopy ? t("chat.copy") : done ? t("chat.copied") : t("chat.copy")}
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] font-medium",
          "text-zinc-600",
          "transition",
          canCopy
            ? "hover:bg-zinc-100 hover:text-zinc-900 active:scale-[0.98] dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            : "cursor-not-allowed opacity-40"
        )}
        aria-label={done ? t("chat.copied") : t("chat.copy")}
      >
        {done ? (
          <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.5} />
        ) : (
          <Copy className="h-3.5 w-3.5" strokeWidth={2.25} />
        )}
        <span className="select-none whitespace-nowrap">{done ? t("chat.copied") : t("chat.copy")}</span>
      </button>
      {canCopy && (
        <span
          className={cn(
            "pointer-events-none absolute bottom-full right-0 z-30 mb-1.5 hidden rounded-lg bg-zinc-800 px-2.5 py-1.5",
            "text-xs font-medium text-white shadow-md",
            "sm:group-hover:block",
            "dark:bg-zinc-600"
          )}
          role="tooltip"
        >
          {t("chat.copy")}
        </span>
      )}
    </div>
  );
}

function AssistantMessageFooter({
  text,
  model,
  timeStr,
}: {
  text: string;
  model?: string;
  timeStr: string | null;
}) {
  return (
    <div
      className={cn(
        "mt-2 flex w-full min-w-0 flex-wrap items-center gap-2 border-t border-zinc-200/80 pt-1.5 text-[11px] dark:border-zinc-600/60",
        timeStr ? "justify-between" : "justify-end"
      )}
    >
      {timeStr ? (
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-zinc-400 dark:text-zinc-500">
          {timeStr}
        </span>
      ) : null}
      <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-x-1 gap-y-1 font-mono text-zinc-500 sm:gap-x-1.5 dark:text-zinc-400">
        <span className="shrink-0 min-w-0 break-all sm:break-normal">
          {model?.trim() ? `Hermes(${model.trim()})` : "Hermes"}
        </span>
        <span className="text-zinc-300 dark:text-zinc-600" aria-hidden>
          ·
        </span>
        <MessageCopyButton text={text} />
      </div>
    </div>
  );
}

export function ChatMessage({ role, text, model, timestamp }: ChatMessageProps) {
  const { locale } = useI18n();
  const isUser = role === "user";
  const hasTime = timestamp != null && Number.isFinite(timestamp);
  const timeStr = hasTime ? formatChatTime(timestamp, locale) : null;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={cn(
          "max-w-[min(100%,42rem)] overflow-visible rounded-lg px-4 py-2.5 shadow-sm",
          isUser
            ? "bg-sky-600 text-white dark:bg-[#3B5BC7] dark:text-white"
            : "border border-zinc-200/90 bg-zinc-100/90 dark:border-zinc-700 dark:bg-zinc-800/90"
        )}
      >
        {isUser ? (
          <>
            <p className="whitespace-pre-wrap text-sm leading-[1.6]">{text}</p>
            {timeStr && (
              <div className="mt-1.5 text-right text-[11px] font-mono tabular-nums text-sky-100/90 dark:text-sky-200/80">
                {timeStr}
              </div>
            )}
          </>
        ) : (
          <>
            <ChatMarkdown text={text} />
            <AssistantMessageFooter text={text} model={model} timeStr={timeStr} />
          </>
        )}
      </div>
    </div>
  );
}
