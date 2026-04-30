import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Maximize2, Minus, X } from "lucide-react";
import { LanguageToggle } from "./LanguageToggle";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

/** 与系统关闭/最小化/最大化同一行的顶栏；需 `tauri.conf.json` 中 `decorations: false`。 */
export function WindowTitleBar() {
  const { t } = useI18n();
  const location = useLocation();
  const inApp = isTauri();
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    if (!inApp) {
      return;
    }
    const win = getCurrentWindow();
    let unlisten: (() => void) | undefined;
    void win.isMaximized().then(setIsMaximized);
    void win
      .onResized(() => {
        void win.isMaximized().then(setIsMaximized);
      })
      .then((u) => {
        unlisten = u;
      });
    return () => {
      unlisten?.();
    };
  }, [inApp]);

  const onMinimize = () => {
    if (!inApp) {
      return;
    }
    void getCurrentWindow().minimize();
  };

  const onToggleMax = () => {
    if (!inApp) {
      return;
    }
    void getCurrentWindow().toggleMaximize();
  };

  const onClose = () => {
    if (!inApp) {
      return;
    }
    void getCurrentWindow().close();
  };

  const isSettings = location.pathname === "/settings";
  const settingsLabel = t("chat.openSettings");

  return (
    <div
      className={cn(
        "flex h-9 shrink-0 select-none items-stretch border-b border-zinc-200/90 bg-zinc-50/95",
        "dark:border-zinc-700 dark:bg-zinc-900/95"
      )}
    >
      <div
        className="hermes-titlebar-drag flex min-w-0 flex-1 items-center pl-3 sm:pl-4"
        data-tauri-drag-region
        aria-label={t("brand")}
      >
        <img
          src="/logo.svg"
          alt=""
          className="h-5 w-5 shrink-0 object-contain dark:opacity-95"
          width={20}
          height={20}
          decoding="async"
          aria-hidden
        />
      </div>

      <div
        className="hermes-titlebar-nodrag flex items-center gap-0.5 pr-1 pl-1 sm:gap-1.5"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <LanguageToggle />

        <Link
          to="/settings"
          className={cn(
            "hd-btn-ghost no-underline rounded-md px-2.5 py-1 text-sm",
            isSettings && "bg-sky-100/90 text-sky-900 dark:bg-sky-900/40 dark:text-sky-100"
          )}
          title={settingsLabel}
        >
          {settingsLabel}
        </Link>

        {inApp && (
          <>
            <div className="mx-0.5 h-4 w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" aria-hidden />
            <button
              type="button"
              onClick={onMinimize}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-zinc-500 transition hover:bg-zinc-200/90 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              title={t("shell.minimize")}
              aria-label={t("shell.minimize")}
            >
              <Minus className="h-3.5 w-3.5" strokeWidth={2.25} />
            </button>
            <button
              type="button"
              onClick={onToggleMax}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-zinc-500 transition hover:bg-zinc-200/90 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              title={isMaximized ? t("shell.restore") : t("shell.maximize")}
              aria-label={isMaximized ? t("shell.restore") : t("shell.maximize")}
            >
              <Maximize2 className="h-3.5 w-3.5" strokeWidth={2.2} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-zinc-500 transition hover:bg-red-500/90 hover:text-white dark:hover:bg-red-600/90"
              title={t("shell.close")}
              aria-label={t("shell.close")}
            >
              <X className="h-3.5 w-3.5" strokeWidth={2.25} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
