import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type QqbotQrProgress = {
  phase?: string;
  qr_url?: string | null;
  message?: string | null;
};

export type QqbotQrResult = {
  ok?: boolean;
  app_id?: string;
  user_openid?: string | null;
  error?: string;
};

export type QqbotQrStatusPayload = {
  running: boolean;
  progress: QqbotQrProgress | null;
  result: QqbotQrResult | null;
};

export type QqEnvSnapshot = {
  configured: boolean;
  hasAppId?: boolean;
  hasClientSecret?: boolean;
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

export function QqbotQrRouteBlock({ className, onSuccess, onHermesRunningChange }: Props) {
  const { t } = useI18n();
  const [qqEnv, setQqEnv] = useState<QqEnvSnapshot | null>(null);
  const [qqPolling, setQqPolling] = useState(false);
  const [qqView, setQqView] = useState<QqbotQrStatusPayload | null>(null);
  const [qqRestarted, setQqRestarted] = useState(false);
  const [qqInlineErr, setQqInlineErr] = useState<string | null>(null);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartErr, setRestartErr] = useState<string | null>(null);
  const qqExitStreak = useRef(0);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const onHermesRef = useRef(onHermesRunningChange);
  onHermesRef.current = onHermesRunningChange;

  const refreshQqEnv = useCallback(async () => {
    try {
      const snap = await invoke<QqEnvSnapshot>("cmd_qq_env_status");
      setQqEnv(snap);
    } catch {
      setQqEnv(null);
    }
  }, []);

  useEffect(() => {
    void refreshQqEnv();
  }, [refreshQqEnv]);

  useEffect(() => {
    if (!qqPolling) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const s = await invoke<QqbotQrStatusPayload>("cmd_qqbot_qr_status");
        if (cancelled) return;
        setQqView(s);
        if (s.running) {
          qqExitStreak.current = 0;
          return;
        }
        const r = s.result;
        if (r && typeof r.ok === "boolean") {
          qqExitStreak.current = 0;
          setQqPolling(false);
          if (r.ok) {
            if (r.app_id) {
              onSuccessRef.current?.({ appId: String(r.app_id) });
            }
            setRestartErr(null);
            try {
              await invoke<number>("cmd_restart_embedded_hermes");
              if (!cancelled) {
                setQqRestarted(true);
                const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
                onHermesRef.current?.(pyStat.running);
                void refreshQqEnv();
              }
            } catch (e) {
              console.error(e);
              if (!cancelled) {
                setQqRestarted(false);
                setRestartErr(t("settings.qqRestartFailed", { msg: ipcErr(e) }));
              }
            }
          }
          return;
        }
        qqExitStreak.current += 1;
        if (qqExitStreak.current >= 30) {
          setQqPolling(false);
          setQqInlineErr(
            t("settings.qqError", { msg: "process exited without result file" })
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
  }, [qqPolling, t, refreshQqEnv]);

  const qqPhaseLabel = useCallback(
    (phase: string | undefined) => {
      switch (phase) {
        case "starting":
          return t("settings.qqPhaseStarting");
        case "connecting":
          return t("settings.qqPhaseConnecting");
        case "waiting_scan":
          return t("settings.qqPhaseWaiting");
        case "scanned":
          return t("settings.qqPhaseScanned");
        case "done":
          return t("settings.qqPhaseDone");
        case "error":
          return t("settings.qqPhaseError");
        default:
          return phase ?? "…";
      }
    },
    [t]
  );

  async function startQqbotQr() {
    setQqInlineErr(null);
    setRestartErr(null);
    setQqRestarted(false);
    setQqView(null);
    qqExitStreak.current = 0;
    try {
      await invoke("cmd_qqbot_qr_start");
      setQqPolling(true);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setQqInlineErr(
        raw.includes("qqbot_qr_worker.py")
          ? t("settings.qqWorkerMissing")
          : t("settings.qqError", { msg: raw })
      );
    }
  }

  async function cancelQqbotQr() {
    try {
      await invoke("cmd_qqbot_qr_cancel");
    } catch (e) {
      console.error(e);
    }
    setQqPolling(false);
    qqExitStreak.current = 0;
  }

  async function manualRestartHermes() {
    setRestartErr(null);
    setRestartBusy(true);
    try {
      await invoke<number>("cmd_restart_embedded_hermes");
      setQqRestarted(true);
      const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
      onHermesRunningChange?.(pyStat.running);
      void refreshQqEnv();
    } catch (e) {
      console.error(e);
      setRestartErr(t("settings.qqRestartFailed", { msg: ipcErr(e) }));
    } finally {
      setRestartBusy(false);
    }
  }

  const qqPartial =
    qqEnv &&
    !qqEnv.configured &&
    ((qqEnv.hasAppId ?? false) || (qqEnv.hasClientSecret ?? false));
  const qqPartialMissing: string[] = [];
  if (qqPartial && qqEnv) {
    if (!(qqEnv.hasAppId ?? false)) qqPartialMissing.push("QQ_APP_ID");
    if (!(qqEnv.hasClientSecret ?? false)) qqPartialMissing.push("QQ_CLIENT_SECRET");
  }

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {qqEnv?.configured ? (
        <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
          <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.qqAlreadyTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-emerald-900/85 dark:text-emerald-100/85">
            {t("settings.qqAlreadyLead")}
          </p>
          {qqEnv.appIdHint ? (
            <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
              {t("settings.qqAppIdHint", { hint: qqEnv.appIdHint })}
            </p>
          ) : null}
        </div>
      ) : null}
      {qqPartial && qqEnv ? (
        <div className="rounded-lg border border-amber-200/90 bg-amber-50/70 px-3 py-2.5 text-sm dark:border-amber-900/55 dark:bg-amber-950/30">
          <p className="font-medium text-amber-950 dark:text-amber-100">{t("settings.qqPartialTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-950/90 dark:text-amber-100/85">
            {t("settings.qqPartialLead", { missing: qqPartialMissing.join("、") })}
          </p>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnClass} onClick={() => void startQqbotQr()} disabled={qqPolling}>
          {qqEnv?.configured ? t("settings.qqRescan") : t("settings.qqStart")}
        </button>
        <button type="button" className={btnClass} onClick={() => void cancelQqbotQr()} disabled={!qqPolling}>
          {t("settings.qqCancel")}
        </button>
      </div>
      {qqInlineErr ? (
        <p className="text-sm text-red-600 dark:text-red-400">{qqInlineErr}</p>
      ) : null}
      {qqView?.progress?.phase ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-300">{qqPhaseLabel(qqView.progress.phase)}</p>
      ) : null}
      {qqView?.progress?.qr_url ? (
        <div className="space-y-1">
          <a
            href={qqView.progress.qr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block max-w-full break-all text-sm font-medium text-sky-600 underline-offset-2 hover:underline dark:text-sky-400"
          >
            {t("settings.qqOpenLink")}
          </a>
          <p className="break-all font-mono text-xs text-zinc-500 dark:text-zinc-500">
            {qqView.progress.qr_url}
          </p>
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{t("settings.qqAfterScanHint")}</p>
        </div>
      ) : null}
      {qqView?.progress?.message ? (
        <p className="text-sm text-red-600 dark:text-red-400">{qqView.progress.message}</p>
      ) : null}
      {qqView?.result?.ok === true ? (
        <div className="space-y-2 text-sm text-zinc-600 dark:text-zinc-300">
          <p>{qqRestarted ? t("settings.qqSuccessDone") : t("settings.qqSuccess")}</p>
          {qqView.result.app_id ? (
            <p className="font-mono text-xs text-zinc-500">App ID: {qqView.result.app_id}</p>
          ) : null}
          {!qqRestarted ? (
            <button
              type="button"
              className={btnClass}
              disabled={restartBusy}
              onClick={() => void manualRestartHermes()}
            >
              {restartBusy ? t("settings.qqRestartBusy") : t("settings.qqRestart")}
            </button>
          ) : null}
          {restartErr ? <p className="text-sm text-red-600 dark:text-red-400">{restartErr}</p> : null}
        </div>
      ) : null}
      {qqView?.result && qqView.result.ok === false ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {t("settings.qqError", { msg: qqView.result.error ?? "unknown" })}
        </p>
      ) : null}
    </div>
  );
}
