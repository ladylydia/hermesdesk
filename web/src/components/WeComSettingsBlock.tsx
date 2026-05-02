import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ask } from "@tauri-apps/plugin-dialog";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type WeComEnvSnapshot = {
  configured: boolean;
  hasBotId?: boolean;
  hasSecret?: boolean;
  botIdHint?: string | null;
  setupMethod?: string | null;
};

export type WeComQrStatusPayload = {
  running: boolean;
  progress: {
    phase?: string;
    message?: string | null;
    url?: string | null;
  } | null;
  result: { ok?: boolean; bot_id?: string; error?: string } | null;
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

const inputClass =
  "w-full rounded-lg border border-zinc-300/90 bg-white/90 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

const ipcErr = (e: unknown): string =>
  e instanceof Error ? e.message : String(e);

const QR_POLL_MS = 2500;

type ViewMode = "choose" | "qr" | "manual" | "configured";

export function WeComSettingsBlock({ className }: { className?: string }) {
  const { t } = useI18n();
  const [env, setEnv] = useState<WeComEnvSnapshot | null>(null);
  const [botId, setBotId] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [openAccess, setOpenAccess] = useState(true);

  // QR scan
  const [qrPolling, setQrPolling] = useState(false);
  const [qrView, setQrView] = useState<WeComQrStatusPayload | null>(null);
  const [qrInlineErr, setQrInlineErr] = useState<string | null>(null);
  const qrExitStreak = useRef(0);

  // View mode — derive from env state
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (env?.configured) return "configured";
    return "choose";
  });

  const refresh = useCallback(async () => {
    try {
      const snap = await invoke<WeComEnvSnapshot>("cmd_wecom_env_status");
      setEnv(snap);
      if (snap.configured) {
        setViewMode("configured");
      } else {
        setViewMode("choose");
      }
    } catch {
      setEnv(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Keep viewMode in sync with env
  useEffect(() => {
    if (env?.configured) {
      setViewMode("configured");
    }
  }, [env]);

  // QR polling
  useEffect(() => {
    if (!qrPolling) return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const s = await invoke<WeComQrStatusPayload>("cmd_wecom_qr_status");
        if (cancelled) return;
        setQrView(s);
        if (s.running) { qrExitStreak.current = 0; return; }
        const r = s.result;
        if (r && typeof r.ok === "boolean") {
          qrExitStreak.current = 0;
          setQrPolling(false);
          if (r.ok) {
            void refresh();
            await invoke<number>("cmd_restart_embedded_hermes").catch(() => {});
          }
          return;
        }
        qrExitStreak.current += 1;
        if (qrExitStreak.current >= 3) {
          setQrPolling(false);
          setQrInlineErr(t("settings.wecomQrError", { msg: "process exited without result" }));
        }
      } catch {
        /* retry */
      }
    };
    tick();
    const iv = setInterval(tick, QR_POLL_MS);
    return () => { cancelled = true; clearInterval(iv); };
  }, [qrPolling, t, refresh]);

  async function startQr() {
    setQrInlineErr(null);
    setQrView(null);
    qrExitStreak.current = 0;
    setViewMode("qr");
    try {
      await invoke("cmd_wecom_qr_start");
      setQrPolling(true);
    } catch (e) {
      setQrInlineErr(ipcErr(e));
    }
  }

  async function cancelQr() {
    try { await invoke("cmd_wecom_qr_cancel"); } catch {}
    setQrPolling(false);
    setQrView(null);
    setViewMode(env?.configured ? "configured" : "choose");
  }

  // Form
  async function saveConfig() {
    const bid = botId.trim();
    const sec = secret.trim();
    if (!bid || !sec) return;
    setSaving(true);
    setError(null);
    try {
      await invoke("cmd_wecom_save_config", { botId: bid, secret: sec, openAccess });
      await invoke<number>("cmd_restart_embedded_hermes");
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
      void refresh();
    } catch {
      void refresh();
    } finally {
      setRemoving(false);
    }
  }

  function handleReconfigure() {
    if (env?.setupMethod === "qr") {
      startQr();
    } else {
      setViewMode("manual");
    }
  }

  const qrPhaseLabel = (phase: string) => {
    const map: Record<string, string> = {
      starting: t("settings.wecomQrPhaseStarting"),
      connecting: t("settings.wecomQrPhaseConnecting"),
      waiting_scan: t("settings.wecomQrPhaseWaitingScan"),
      done: t("settings.wecomQrPhaseDone"),
      error: t("settings.wecomQrPhaseError"),
    };
    return map[phase] || phase;
  };

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {/* ── Configured ── */}
      {viewMode === "configured" ? (
        <>
          <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
            <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.wecomAlreadyTitle")}</p>
            {env?.botIdHint ? (
              <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
                {t("settings.wecomBotIdHint", { hint: env.botIdHint })}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnClass} onClick={handleReconfigure}>
              {t("settings.wecomReconfigure")}
            </button>
            <button type="button" className={btnClass} onClick={() => void handleRemove()} disabled={removing}>
              {removing ? "…" : t("settings.telegramRemoveConfig")}
            </button>
          </div>
        </>
      ) : null}

      {/* ── QR scan section (viewMode = choose | qr) ── */}
      {(viewMode === "choose" || viewMode === "qr") && !env?.configured ? (
        <div className="rounded-lg border border-dashed border-zinc-300/80 px-3 py-2.5 text-sm dark:border-zinc-700/80">
          <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">
            {t("settings.wecomQrTitle")}
          </p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">{t("settings.wecomQrLead")}</p>
          {!qrPolling && !qrView?.progress ? (
            <button type="button" className={btnClass} onClick={() => void startQr()}>
              {t("settings.wecomQrStart")}
            </button>
          ) : null}
        </div>
      ) : null}

      {/* QR progress */}
      {qrPolling && qrView?.progress?.phase ? (
        <div className="rounded-lg border border-sky-200/80 bg-sky-50/50 px-3 py-2.5 text-sm dark:border-sky-800/50 dark:bg-sky-950/25">
          <p className="text-xs text-zinc-600 dark:text-zinc-300">{qrPhaseLabel(qrView.progress.phase)}</p>
          {qrView.progress.message ? (
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{qrView.progress.message}</p>
          ) : null}
          {qrView.progress.url ? (
            <a
              href={qrView.progress.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block break-all text-xs font-medium text-sky-600 underline-offset-2 hover:underline dark:text-sky-400"
            >
              {qrView.progress.url}
            </a>
          ) : null}
        </div>
      ) : null}

      {qrInlineErr ? (
        <p className="text-sm text-red-600 dark:text-red-400">{qrInlineErr}</p>
      ) : null}

      {qrPolling ? (
        <button type="button" className={btnClass} onClick={() => void cancelQr()}>
          {t("settings.wecomQrCancel")}
        </button>
      ) : null}

      {/* ── Divider (only when both QR and manual shown) ── */}
      {viewMode === "choose" && !qrPolling && !qrView?.progress ? (
        <>
          <hr className="border-zinc-200/60 dark:border-zinc-700/60" />
          <div className="text-center">
            <button type="button" className={btnClass} onClick={() => setViewMode("manual")}>
              {t("settings.wecomManualEntry")}
            </button>
          </div>
        </>
      ) : null}

      {/* ── Manual form (viewMode = manual) ── */}
      {viewMode === "manual" ? (
        <div className="space-y-3 rounded-lg border border-sky-200/80 bg-sky-50/50 px-3 py-3 dark:border-sky-800/50 dark:bg-sky-950/25">
          <div className="flex items-center justify-between">
            <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
              {t("settings.wecomFormLead")}
            </p>
            <button type="button" className={cn(btnClass, "text-xs")} onClick={() => setViewMode("choose")}>
              ← {t("settings.wecomBackToQr")}
            </button>
          </div>
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
          <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 cursor-pointer">
            <input
              type="checkbox"
              checked={openAccess}
              onChange={(e) => setOpenAccess(e.target.checked)}
              className="rounded"
            />
            {t("settings.wecomOpenAccess")}
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnClass} onClick={() => void saveConfig()} disabled={saving || !botId.trim() || !secret.trim()}>
              {saving ? "…" : t("settings.wecomFormSave")}
            </button>
            <button type="button" className={btnClass} onClick={() => { setError(null); setBotId(""); setSecret(""); setViewMode(env?.configured ? "configured" : "choose"); }}>
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
