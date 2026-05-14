import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Bell, MessageCircle, Minus, X } from "lucide-react";
import { createDesktopDeliveryNotice, type DesktopDeliveryMessage, type DesktopDeliveryNotice } from "../lib/desktopDelivery";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

const EVENT_NAME = "desktop-delivery";
type CompanionMode = "expanded" | "compact";

export function CompanionWindow() {
  const { t, locale } = useI18n();
  const [notice, setNotice] = useState<DesktopDeliveryNotice | null>(null);
  const [mode, setMode] = useState<CompanionMode>("expanded");
  const sequenceRef = useRef(0);

  useEffect(() => {
    const unlisten = listen<DesktopDeliveryMessage>(EVENT_NAME, ({ payload }) => {
      setNotice(
        createDesktopDeliveryNotice(
          payload,
          Date.now() + sequenceRef.current++,
          t("cron.toastFallbackTitle"),
        ),
      );
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [t]);

  const title = notice?.title || (locale === "zh" ? "小娜待机中" : "Nana is here");
  const preview = notice?.preview || (locale === "zh" ? "需要时点开主窗口就好。" : "Open the main window whenever you need me.");

  const hide = () => {
    void invoke("cmd_hide_companion");
  };

  const openMain = () => {
    void invoke("cmd_focus_main_window");
  };

  const setCompanionMode = async (next: CompanionMode) => {
    try {
      await invoke("cmd_set_companion_mode", { mode: next });
    } catch (error) {
      console.error("cmd_set_companion_mode failed:", error);
      try {
        await getCurrentWindow().setSize(
          next === "compact"
            ? new LogicalSize(120, 48)
            : new LogicalSize(320, 160),
        );
      } catch (fallbackError) {
        console.error("companion setSize fallback failed:", fallbackError);
      }
    }
    if (next === "compact") {
      setMode("compact");
    } else {
      setMode("expanded");
    }
  };

  const startDrag = (event: React.MouseEvent) => {
    if (event.button !== 0) {
      return;
    }
    void getCurrentWindow().startDragging().catch((error) => {
      console.error("companion startDragging failed:", error);
    });
  };

  if (mode === "compact") {
    return (
      <button
        type="button"
        className={cn(
          "flex h-screen w-screen cursor-move select-none items-center gap-2 overflow-hidden rounded-3xl border border-white/50 bg-white/95 px-2 text-left text-zinc-800 shadow-lg shadow-zinc-950/10 backdrop-blur",
          "dark:border-zinc-700/60 dark:bg-zinc-950/95 dark:text-zinc-100",
        )}
        onClick={() => void setCompanionMode("expanded")}
        onMouseDown={startDrag}
        aria-label={t("companion.expand")}
        title={t("companion.expand")}
        data-tauri-drag-region
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300">
          <img src="/kabuqina_na_blue_48.png" alt="" className="h-5 w-5" />
        </span>
        <span className="min-w-0 truncate text-xs font-semibold">
          {locale === "zh" ? t("companion.idleShort") : "Nana"}
        </span>
      </button>
    );
  }

  return (
    <div
      className={cn(
        "select-none cursor-move",
        "h-screen w-screen overflow-hidden rounded-xl border border-white/70 bg-white/90 p-2.5 text-zinc-800 shadow-2xl shadow-zinc-950/15 backdrop-blur",
        "dark:border-zinc-700/70 dark:bg-zinc-950/90 dark:text-zinc-100",
      )}
      onMouseDown={startDrag}
      data-tauri-drag-region
    >
      <div className="flex h-full items-center gap-2.5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300">
          {notice ? <Bell className="h-5 w-5" aria-hidden /> : <img src="/kabuqina_na_blue_48.png" alt="" className="h-6 w-6" />}
        </div>
        <div
          className="min-w-0 flex-1"
          data-tauri-drag-region
        >
          <p className="truncate text-sm font-semibold">{title}</p>
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-zinc-500 dark:text-zinc-400">
            {preview}
          </p>
        </div>
        <div className="hermes-titlebar-nodrag flex shrink-0 flex-col gap-1">
          <button
            type="button"
            onClick={openMain}
            onMouseDown={(event) => event.stopPropagation()}
            className="flex h-6 w-6 cursor-default items-center justify-center rounded-md text-zinc-500 transition hover:bg-sky-50 hover:text-sky-700 dark:hover:bg-sky-950 dark:hover:text-sky-300"
            aria-label={t("cron.toastOpen")}
            title={t("cron.toastOpen")}
          >
            <MessageCircle className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => void setCompanionMode("compact")}
            onMouseDown={(event) => event.stopPropagation()}
            className="flex h-6 w-6 cursor-default items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            aria-label={t("companion.minimize")}
            title={t("companion.minimize")}
          >
            <Minus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={hide}
            onMouseDown={(event) => event.stopPropagation()}
            className="flex h-6 w-6 cursor-default items-center justify-center rounded-md text-zinc-500 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-300"
            aria-label={t("shell.close")}
            title={t("shell.close")}
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
