import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getLocale } from "../../lib/i18n-core";
import { useI18n } from "../../lib/i18n";
import { clearDraft, useDraft } from "../../lib/store";

export function Done() {
  const { t } = useI18n();
  const draft = useDraft();

  useEffect(() => {
    invoke("cmd_set_personality", { name: draft.personality }).catch(() => {});
  }, [draft.personality]);

  async function openWorkspace() {
    try {
      await invoke("cmd_open_workspace");
    } catch (e) {
      console.error(e);
    }
  }

  async function openChat() {
    clearDraft();
    const loc = getLocale();
    try {
      await invoke("cmd_open_hermes_dashboard", { shellLocale: loc, path: null });
    } catch (e) {
      console.error(e);
      try {
        const port = await invoke<number | null>("cmd_get_hermes_port");
        if (port) {
          const u = new URL(`http://127.0.0.1:${port}/`);
          if (loc === "en" || loc === "zh") {
            u.searchParams.set("hermesdesk_lang", loc);
          }
          window.open(u.toString(), "_blank", "noopener,noreferrer");
        } else {
          window.location.replace("/");
        }
      } catch {
        window.location.replace("/");
      }
    }
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="text-4xl">{"\u{1F44B}"}</div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("done.title")}</h1>
        <p className="text-zinc-600 dark:text-zinc-400 leading-relaxed">{t("done.lead")}</p>
      </div>

      <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 p-5 space-y-2">
        <div className="text-sm font-medium">{t("done.workspaceTitle")}</div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{t("done.workspaceBody")}</p>
        <button
          onClick={openWorkspace}
          className="text-sm underline underline-offset-4 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          {t("done.openFolder")}
        </button>
      </div>

      <button
        onClick={() => void openChat()}
        className="w-full rounded-2xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-6 py-4 text-lg font-medium hover:opacity-90 transition"
      >
        {t("done.cta")}
      </button>
    </div>
  );
}
