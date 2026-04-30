import { useCallback, useRef } from "react";
import { ArrowUp, Paperclip, Square } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

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
}: ChatInputProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
          "mx-auto max-w-3xl overflow-hidden rounded-lg border border-zinc-200/95 bg-white",
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
          <div className="flex items-center gap-1">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept="image/*,text/*,.md,.json,.xml,.yaml,.yml,.csv,.log,.ts,.tsx,.js,.jsx,.py,.rs,.go,.c,.h,.cpp,.hpp,.cs,.java,.html,.css,.sh,.ps1"
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
              className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 active:scale-[0.98] dark:text-zinc-400 dark:hover:bg-zinc-700/80 disabled:cursor-not-allowed disabled:opacity-40"
              title={t("chat.attach")}
              aria-label={t("chat.attach")}
            >
              <Paperclip className="h-5 w-5" />
            </button>
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
      <p className="mx-auto mt-2.5 max-w-3xl text-center text-xs leading-[1.5] text-zinc-400 dark:text-zinc-500">
        {t("chat.hint")}
      </p>
    </div>
  );
}
