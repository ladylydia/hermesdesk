import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ask } from "@tauri-apps/plugin-dialog";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type WeComEnvSnapshot = {
  configured: boolean;
  hasBotId?: boolean;
  hasSecret?: boolean;
  botIdHint?: string | null;
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

const inputClass =
  "w-full rounded-lg border border-zinc-300/90 bg-white/90 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

export function WeComSettingsBlock({ className }: { className?: string }) {
  const { t } = useI18n();
  const [env, setEnv] = useState<WeComEnvSnapshot | null>(null);
  const [botId, setBotId] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [removing, setRemoving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const snap = await invoke<WeComEnvSnapshot>("cmd_wecom_env_status");
      setEnv(snap);
    } catch {
      setEnv(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function saveConfig() {
    const bid = botId.trim();
    const sec = secret.trim();
    if (!bid || !sec) return;
    setSaving(true);
    setError(null);
    try {
      await invoke("cmd_wecom_save_config", { botId: bid, secret: sec });
      await invoke<number>("cmd_restart_embedded_hermes");
      setShowForm(false);
      setBotId("");
      setSecret("");
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove() {
    const ok = await ask(t("settings.removeConfigAsk"), {
      title: t("settings.removeConfigAskTitle"),
      kind: "warning",
    });
    if (!ok) return;
    setRemoving(true);
    try {
      await invoke("cmd_wecom_env_remove");
      await invoke<number>("cmd_restart_embedded_hermes");
      setShowForm(false);
      void refresh();
    } catch {
      void refresh();
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {!env?.configured && !showForm ? (
        <>
          <div className="rounded-lg border border-zinc-200/80 bg-zinc-50/70 px-3 py-2.5 text-sm dark:border-zinc-700/80 dark:bg-zinc-900/40">
            <p className="text-zinc-600 dark:text-zinc-400">{t("settings.wecomNotConfigured")}</p>
          </div>
          <button type="button" className={btnClass} onClick={() => setShowForm(true)}>
            {t("settings.wecomSetup")}
          </button>
        </>
      ) : null}

      {env?.configured && !showForm ? (
        <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
          <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.wecomAlreadyTitle")}</p>
          {env.botIdHint ? (
            <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
              {t("settings.wecomBotIdHint", { hint: env.botIdHint })}
            </p>
          ) : null}
        </div>
      ) : null}

      {env?.configured && !showForm ? (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={btnClass} onClick={() => setShowForm(true)}>
            {t("settings.wecomReconfigure")}
          </button>
          <button type="button" className={btnClass} onClick={() => void handleRemove()} disabled={removing}>
            {removing ? "…" : t("settings.telegramRemoveConfig")}
          </button>
        </div>
      ) : null}

      {showForm ? (
        <div className="space-y-3 rounded-lg border border-sky-200/80 bg-sky-50/50 px-3 py-3 dark:border-sky-800/50 dark:bg-sky-950/25">
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
            {t("settings.wecomFormLead")}
          </p>
          <input
            className={inputClass}
            type="text"
            value={botId}
            placeholder={t("settings.wecomBotIdPlaceholder")}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setBotId(e.target.value)}
          />
          <input
            className={inputClass}
            type="password"
            value={secret}
            placeholder={t("settings.wecomSecretPlaceholder")}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setSecret(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void saveConfig();
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnClass} onClick={() => void saveConfig()} disabled={saving || !botId.trim() || !secret.trim()}>
              {saving ? "…" : t("settings.wecomFormSave")}
            </button>
            <button type="button" className={btnClass} onClick={() => { setShowForm(false); setError(null); setBotId(""); setSecret(""); }}>
              {t("settings.wecomFormCancel")}
            </button>
          </div>
          {error ? (
            <p className="text-sm text-red-600 dark:text-red-400">{t("settings.wecomFormError", { msg: error })}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
