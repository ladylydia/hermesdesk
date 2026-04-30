import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type FeishuQrProgress = {
  phase?: string;
  qr_url?: string | null;
  message?: string | null;
};

export type FeishuQrResult = {
  ok?: boolean;
  app_id?: string;
  domain?: string;
  open_id?: string | null;
  bot_name?: string | null;
  error?: string;
};

export type FeishuQrStatusPayload = {
  running: boolean;
  progress: FeishuQrProgress | null;
  result: FeishuQrResult | null;
};

export type FeishuEnvSnapshot = {
  configured: boolean;
  hasAppId?: boolean;
  hasAppSecret?: boolean;
  appIdHint?: string | null;
};

type Props = {
  className?: string;
  onSuccess?: (payload: { appId: string }) => void;
  onHermesRunningChange?: (running: boolean) => void;
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

function ipcErr(e: unknown): string {
  if (typeof e === "string") return e;
  if (e && typeof e === "object" && "message" in e) return String((e as Error).message);
  return String(e);
}

export function FeishuQrRouteBlock({ className, onSuccess, onHermesRunningChange }: Props) {
  const { t } = useI18n();
  const [feishuEnv, setFeishuEnv] = useState<FeishuEnvSnapshot | null>(null);
  const [polling, setPolling] = useState(false);
  const [view, setView] = useState<FeishuQrStatusPayload | null>(null);
  const [restarted, setRestarted] = useState(false);
  const [inlineErr, setInlineErr] = useState<string | null>(null);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartErr, setRestartErr] = useState<string | null>(null);
  const exitStreak = useRef(0);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const onHermesRef = useRef(onHermesRunningChange);
  onHermesRef.current = onHermesRunningChange;

  const refreshFeishuEnv = useCallback(async () => {
    try {
      const snap = await invoke<FeishuEnvSnapshot>("cmd_feishu_env_status");
      setFeishuEnv(snap);
    } catch {
      setFeishuEnv(null);
    }
  }, []);

  useEffect(() => {
    void refreshFeishuEnv();
  }, [refreshFeishuEnv]);

  useEffect(() => {
    if (!polling) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const s = await invoke<FeishuQrStatusPayload>("cmd_feishu_qr_status");
        if (cancelled) return;
        setView(s);
        if (s.running) {
          exitStreak.current = 0;
          return;
        }
        const r = s.result;
        if (r && typeof r.ok === "boolean") {
          exitStreak.current = 0;
          setPolling(false);
          if (r.ok) {
            if (r.app_id) {
              onSuccessRef.current?.({ appId: String(r.app_id) });
            }
            setRestartErr(null);
            try {
              await invoke<number>("cmd_restart_embedded_hermes");
              if (!cancelled) {
                setRestarted(true);
                const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
                onHermesRef.current?.(pyStat.running);
                void refreshFeishuEnv();
              }
            } catch (e) {
              console.error(e);
              if (!cancelled) {
                setRestarted(false);
                setRestartErr(t("settings.feishuRestartFailed", { msg: ipcErr(e) }));
              }
            }
          }
          return;
        }
        exitStreak.current += 1;
        if (exitStreak.current >= 8) {
          setPolling(false);
          setInlineErr(
            t("settings.feishuError", { msg: "process exited without result file" })
          );
        }
      } catch (e) {
        console.error(e);
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [polling, t, refreshFeishuEnv]);

  const phaseLabel = useCallback(
    (phase: string | undefined) => {
      switch (phase) {
        case "starting":
          return t("settings.feishuPhaseStarting");
        case "connecting":
          return t("settings.feishuPhaseConnecting");
        case "waiting_scan":
          return t("settings.feishuPhaseWaiting");
        case "done":
          return t("settings.feishuPhaseDone");
        case "error":
          return t("settings.feishuPhaseError");
        default:
          return phase ?? "…";
      }
    },
    [t]
  );

  async function startFeishuQr() {
    setInlineErr(null);
    setRestartErr(null);
    setRestarted(false);
    setView(null);
    exitStreak.current = 0;
    try {
      await invoke("cmd_feishu_qr_start");
      setPolling(true);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setInlineErr(
        raw.includes("feishu_qr_worker.py")
          ? t("settings.feishuWorkerMissing")
          : t("settings.feishuError", { msg: raw })
      );
    }
  }

  async function cancelFeishuQr() {
    try {
      await invoke("cmd_feishu_qr_cancel");
    } catch (e) {
      console.error(e);
    }
    setPolling(false);
    exitStreak.current = 0;
  }

  async function manualRestartHermes() {
    setRestartErr(null);
    setRestartBusy(true);
    try {
      await invoke<number>("cmd_restart_embedded_hermes");
      setRestarted(true);
      const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
      onHermesRunningChange?.(pyStat.running);
      void refreshFeishuEnv();
    } catch (e) {
      console.error(e);
      setRestartErr(t("settings.feishuRestartFailed", { msg: ipcErr(e) }));
    } finally {
      setRestartBusy(false);
    }
  }

  const partial =
    feishuEnv &&
    !feishuEnv.configured &&
    ((feishuEnv.hasAppId ?? false) || (feishuEnv.hasAppSecret ?? false));
  const partialMissing: string[] = [];
  if (partial && feishuEnv) {
    if (!(feishuEnv.hasAppId ?? false)) partialMissing.push("FEISHU_APP_ID");
    if (!(feishuEnv.hasAppSecret ?? false)) partialMissing.push("FEISHU_APP_SECRET");
  }

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {feishuEnv?.configured ? (
        <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
          <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.feishuAlreadyTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-emerald-900/85 dark:text-emerald-100/85">
            {t("settings.feishuAlreadyLead")}
          </p>
          {feishuEnv.appIdHint ? (
            <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
              {t("settings.feishuAppIdHint", { hint: feishuEnv.appIdHint })}
            </p>
          ) : null}
          {view?.result?.bot_name ? (
            <p className="mt-1 text-xs text-emerald-900/85 dark:text-emerald-100/85">
              {t("settings.feishuBotName", { name: view.result.bot_name })}
            </p>
          ) : null}
        </div>
      ) : null}
      {partial && feishuEnv ? (
        <div className="rounded-lg border border-amber-200/90 bg-amber-50/70 px-3 py-2.5 text-sm dark:border-amber-900/55 dark:bg-amber-950/30">
          <p className="font-medium text-amber-950 dark:text-amber-100">{t("settings.feishuPartialTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-950/90 dark:text-amber-100/85">
            {t("settings.feishuPartialLead", { missing: partialMissing.join("、") })}
          </p>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnClass} onClick={() => void startFeishuQr()} disabled={polling}>
          {feishuEnv?.configured ? t("settings.feishuRescan") : t("settings.feishuStart")}
        </button>
        <button type="button" className={btnClass} onClick={() => void cancelFeishuQr()} disabled={!polling}>
          {t("settings.feishuCancel")}
        </button>
      </div>
      {inlineErr ? (
        <p className="text-sm text-red-600 dark:text-red-400">{inlineErr}</p>
      ) : null}
      {view?.progress?.phase ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-300">{phaseLabel(view.progress.phase)}</p>
      ) : null}
      {view?.progress?.qr_url ? (
        <div className="space-y-1">
          <a
            href={view.progress.qr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block max-w-full break-all text-sm font-medium text-sky-600 underline-offset-2 hover:underline dark:text-sky-400"
          >
            {t("settings.feishuOpenLink")}
          </a>
          <p className="break-all font-mono text-xs text-zinc-500 dark:text-zinc-500">
            {view.progress.qr_url}
          </p>
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{t("settings.feishuAfterScanHint")}</p>
        </div>
      ) : null}
      {view?.progress?.message ? (
        <p className="text-sm text-red-600 dark:text-red-400">{view.progress.message}</p>
      ) : null}
      {view?.result?.ok === true ? (
        <div className="space-y-2 text-sm text-zinc-600 dark:text-zinc-300">
          <p>{restarted ? t("settings.feishuSuccessDone") : t("settings.feishuSuccess")}</p>
          {view.result.app_id ? (
            <p className="font-mono text-xs text-zinc-500">App ID: {view.result.app_id}</p>
          ) : null}
          {!restarted ? (
            <button
              type="button"
              className={btnClass}
              disabled={restartBusy}
              onClick={() => void manualRestartHermes()}
            >
              {restartBusy ? t("settings.feishuRestartBusy") : t("settings.feishuRestart")}
            </button>
          ) : null}
          {restartErr ? <p className="text-sm text-red-600 dark:text-red-400">{restartErr}</p> : null}
        </div>
      ) : null}
      {view?.result && view.result.ok === false ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {t("settings.feishuError", { msg: view.result.error ?? "unknown" })}
        </p>
      ) : null}
    </div>
  );
}
