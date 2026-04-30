import { Plus, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import type { SessionRow } from "./chat-api";
import { cn } from "../lib/cn";

export interface ChatSidebarProps {
  sessions: SessionRow[];
  activeSessionId: string | null;
  loading?: boolean;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string, e: React.MouseEvent) => void;
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  loading = false,
  onNewChat,
  onSelectSession,
  onDeleteSession,
}: ChatSidebarProps) {
  const { t } = useI18n();
  const nav = useNavigate();

  return (
    <aside className="flex w-[272px] shrink-0 flex-col border-r border-zinc-200/90 bg-zinc-100/30 dark:border-zinc-700 dark:bg-zinc-900/30">
      <div className="border-b border-zinc-200/80 p-4 pb-3 dark:border-zinc-700/80">
        <button
          type="button"
          onClick={() => onNewChat()}
          className="inline-flex w-full items-center justify-start gap-2 rounded-lg bg-sky-600 px-3 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-sky-700 active:scale-[0.99] dark:bg-sky-500 dark:text-white dark:hover:bg-sky-600"
        >
          <span>{t("chat.newChat")}</span>
          <Plus className="h-4 w-4 shrink-0 stroke-[2.75]" aria-hidden />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-4 pt-2">
        {loading && (
          <p className="px-1.5 py-2 text-xs text-zinc-400 dark:text-zinc-500">{t("chat.loadingSessions")}</p>
        )}
        {!loading && sessions.length === 0 && (
          <p className="px-1.5 py-2 text-center text-xs leading-relaxed text-zinc-400 dark:text-zinc-500">
            {t("chat.noSessions")}
          </p>
        )}
        {sessions.map((s) => {
          const label = (s.title && s.title.trim()) || s.preview || s.id.slice(0, 8);
          const active = s.id === activeSessionId;
          return (
            <div
              key={s.id}
              className={cn(
                "group flex items-stretch overflow-hidden rounded-lg",
                active && "bg-zinc-200/60 dark:bg-zinc-800/60"
              )}
            >
              <button
                type="button"
                onClick={() => onSelectSession(s.id)}
                title={label}
                className="min-w-0 flex-1 px-2.5 py-2.5 text-left"
              >
                <div
                  className={cn(
                    "truncate text-[13px] leading-snug",
                    active
                      ? "font-medium text-zinc-900 dark:text-zinc-100"
                      : "text-zinc-600 group-hover:text-zinc-900 dark:text-zinc-400 dark:group-hover:text-zinc-100"
                  )}
                >
                  {label}
                </div>
              </button>
              <button
                type="button"
                title={t("chat.delete")}
                onClick={(e) => onDeleteSession(s.id, e)}
                className="shrink-0 px-1.5 text-zinc-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100 dark:text-zinc-600 dark:hover:text-red-400"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
      <div className="shrink-0 border-t border-zinc-200/80 bg-zinc-100/50 px-3 py-3 dark:border-zinc-700/80 dark:bg-zinc-900/50">
        <button
          type="button"
          onClick={() => {
            nav("/onboarding/mode");
          }}
          className="inline-flex w-full items-start gap-2.5 rounded-lg border border-zinc-200/90 bg-white/90 px-3 py-2.5 text-left text-sm font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 active:scale-[0.99] dark:border-zinc-600 dark:bg-zinc-800/80 dark:text-zinc-100 dark:hover:bg-zinc-800/95"
        >
          <Sparkles
            className="mt-0.5 h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400"
            strokeWidth={2.25}
            aria-hidden
          />
          <span className="min-w-0 flex-1">
            <span className="block leading-snug">{t("chat.wizardButton")}</span>
            <span className="mt-0.5 block text-[11px] font-normal leading-relaxed text-zinc-500 dark:text-zinc-500">
              {t("chat.wizardHint")}
            </span>
          </span>
        </button>
      </div>
    </aside>
  );
}
