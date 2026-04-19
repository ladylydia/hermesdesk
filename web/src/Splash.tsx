import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";

/**
 * Initial route. Decides:
 *   - has secret? -> redirect to chat (Hermes localhost server)
 *   - else        -> /onboarding
 */
export function Splash() {
  const nav = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const has = await invoke<boolean>("cmd_has_secret");
        if (has) {
          // Tauri shell will replace the URL with the Hermes port once
          // the Python child is ready. Until then, show the splash.
          return;
        }
        nav("/onboarding/welcome", { replace: true });
      } catch (e) {
        console.error(e);
        nav("/onboarding/welcome", { replace: true });
      }
    })();
  }, [nav]);

  return (
    <div className="h-full w-full flex flex-col items-center justify-center bg-zinc-50 dark:bg-zinc-950">
      <div className="text-2xl font-semibold tracking-tight">HermesDesk</div>
      <div className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
        Waking your assistant...
      </div>
      <div className="mt-8 h-1 w-48 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
        <div className="h-full w-1/3 animate-pulse bg-zinc-400 dark:bg-zinc-600" />
      </div>
    </div>
  );
}
