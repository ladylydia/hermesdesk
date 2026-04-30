import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type TelegramEnvSnapshot = {
  configured: boolean;
  hasBotToken?: boolean;
  orphanTelegramConfig?: boolean;
  tokenHint?: string | null;
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

const inputClass =
  "w-full rounded-lg border border-zinc-300/90 bg-white/90 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

export function TelegramSettingsBlock({ className }: { className?: string }) {
  const { t } = useI18n();
  const [env, setEnv] = useState<TelegramEnvSnapshot | null>(null);
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const snap = await invoke<TelegramEnvSnapshot>("cmd_telegram_env_status");
      setEnv(snap);
    } catch {
      setEnv(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function saveToken() {
    const val = token.trim();
    if (!val) return;
    setSaving(true);
    setError(null);
    try {
      await invoke("cmd_telegram_save_token", { token: val });
      await invoke<number>("cmd_restart_embedded_hermes");
      setShowForm(false);
      setToken("");
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const partial = env && !env.configured && (env.orphanTelegramConfig ?? false);

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {!env?.configured && !showForm ? (
        <>
          <div className="rounded-lg border border-zinc-200/80 bg-zinc-50/70 px-3 py-2.5 text-sm dark:border-zinc-700/80 dark:bg-zinc-900/40">
            <p className="text-zinc-600 dark:text-zinc-400">{t("settings.telegramNotConfigured")}</p>
          </div>
          <button type="button" className={btnClass} onClick={() => setShowForm(true)}>
            {t("settings.telegramSetup")}
          </button>
        </>
      ) : null}

      {partial && !showForm ? (
        <div className="rounded-lg border border-amber-200/90 bg-amber-50/70 px-3 py-2.5 text-sm dark:border-amber-900/55 dark:bg-amber-950/30">
          <p className="font-medium text-amber-950 dark:text-amber-100">{t("settings.telegramPartialTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-950/90 dark:text-amber-100/85">
            {t("settings.telegramPartialLead")}
          </p>
        </div>
      ) : null}

      {env?.configured && !showForm ? (
        <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
          <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.telegramAlreadyTitle")}</p>
          {env.tokenHint ? (
            <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
              {t("settings.telegramTokenHint", { hint: env.tokenHint })}
            </p>
          ) : null}
        </div>
      ) : null}

      {env?.configured && !showForm ? (
        <button type="button" className={btnClass} onClick={() => setShowForm(true)}>
          {t("settings.telegramReconfigure")}
        </button>
      ) : null}

      {showForm ? (
        <div className="space-y-3 rounded-lg border border-sky-200/80 bg-sky-50/50 px-3 py-3 dark:border-sky-800/50 dark:bg-sky-950/25">
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
            {t("settings.telegramFormLead")}
          </p>
          <input
            className={inputClass}
            type="password"
            value={token}
            placeholder={t("settings.telegramFormPlaceholder")}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void saveToken();
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnClass} onClick={() => void saveToken()} disabled={saving || !token.trim()}>
              {saving ? t("settings.telegramFormSaving") : t("settings.telegramFormSave")}
            </button>
            <button type="button" className={btnClass} onClick={() => { setShowForm(false); setError(null); setToken(""); }}>
              {t("settings.telegramFormCancel")}
            </button>
          </div>
          {error ? (
            <p className="text-sm text-red-600 dark:text-red-400">{t("settings.telegramFormError", { msg: error })}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
