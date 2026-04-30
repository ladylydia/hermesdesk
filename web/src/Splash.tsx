import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { AppScaffold } from "./components/AppScaffold";
import { useI18n } from "./lib/i18n";
import { cn } from "./lib/cn";
import { clearAllowChatWithoutApi, getAllowChatWithoutApi } from "./lib/apiKeyGate";

/**
 * App entry: saved API key → chat. No key but user chose “configure later” on pass step → chat.
 * Otherwise → onboarding.
 */
export function Splash() {
  const { t } = useI18n();
  const nav = useNavigate();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const has = await invoke<boolean>("cmd_has_secret");
        if (cancelled) return;
        if (has) {
          clearAllowChatWithoutApi();
          nav("/chat", { replace: true });
          return;
        }
        const allowLater = getAllowChatWithoutApi();
        if (allowLater) {
          nav("/chat", { replace: true });
          return;
        }
        nav("/onboarding/mode", { replace: true });
      } catch {
        if (!cancelled) nav("/onboarding/mode", { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [nav]);

  return (
    <AppScaffold className="flex h-full min-h-0 flex-col items-center justify-center">
      <div
        className={cn(
          "hd-glass w-full max-w-sm px-8 py-10 text-center",
          "sm:max-w-md sm:px-10"
        )}
      >
        <div className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("brand")}</div>
        <p className="hd-hint mt-3 justify-center">
          <span aria-hidden>✨</span>
          {t("splash.waking")}
        </p>
        <div className="mx-auto mt-8 h-1 w-48 max-w-full overflow-hidden rounded-full bg-zinc-200/90 dark:bg-zinc-800">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-zinc-400/90 dark:bg-zinc-500" />
        </div>
      </div>
    </AppScaffold>
  );
}
