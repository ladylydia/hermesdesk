import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type WeixinQrProgress = {
  phase?: string;
  liteapp_url?: string | null;
  message?: string | null;
};

export type WeixinQrResult = {
  ok?: boolean;
  account_id?: string;
  user_id?: string | null;
  error?: string;
};

export type WeixinQrStatusPayload = {
  running: boolean;
  progress: WeixinQrProgress | null;
  result: WeixinQrResult | null;
};

export type WeixinEnvSnapshot = {
  configured: boolean;
  /** Non-empty ``WEIXIN_ACCOUNT_ID`` in hermes-home/.env */
  hasAccountId?: boolean;
  /** Non-empty ``WEIXIN_TOKEN`` in hermes-home/.env */
  hasToken?: boolean;
  accountIdHint?: string | null;
};

type Props = {
  className?: string;
  /** After credentials are written to `.env` (restart may still be in progress). */
  onSuccess?: (payload: { accountId: string }) => void;
  /** When embedded Hermes restarts successfully, report new running flag. */
  onHermesRunningChange?: (running: boolean) => void;
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

function ipcErr(e: unknown): string {
  if (typeof e === "string") return e;
  if (e && typeof e === "object" && "message" in e) return String((e as Error).message);
  return String(e);
}

export function WeixinQrRouteCBlock({ className, onSuccess, onHermesRunningChange }: Props) {
  const { t } = useI18n();
  const [weixinEnv, setWeixinEnv] = useState<WeixinEnvSnapshot | null>(null);
  const [weixinPolling, setWeixinPolling] = useState(false);
  const [weixinView, setWeixinView] = useState<WeixinQrStatusPayload | null>(null);
  const [weixinRestarted, setWeixinRestarted] = useState(false);
  const [weixinInlineErr, setWeixinInlineErr] = useState<string | null>(null);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartErr, setRestartErr] = useState<string | null>(null);
  const weixinExitStreak = useRef(0);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const onHermesRef = useRef(onHermesRunningChange);
  onHermesRef.current = onHermesRunningChange;

  const refreshWeixinEnv = useCallback(async () => {
    try {
      const snap = await invoke<WeixinEnvSnapshot>("cmd_weixin_env_status");
      setWeixinEnv(snap);
    } catch {
      setWeixinEnv(null);
    }
  }, []);

  useEffect(() => {
    void refreshWeixinEnv();
  }, [refreshWeixinEnv]);

  useEffect(() => {
    if (!weixinPolling) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const s = await invoke<WeixinQrStatusPayload>("cmd_weixin_qr_status");
        if (cancelled) return;
        setWeixinView(s);
        if (s.running) {
          weixinExitStreak.current = 0;
          return;
        }
        const r = s.result;
        if (r && typeof r.ok === "boolean") {
          weixinExitStreak.current = 0;
          setWeixinPolling(false);
          if (r.ok) {
            if (r.account_id) {
              onSuccessRef.current?.({ accountId: String(r.account_id) });
            }
            setRestartErr(null);
            try {
              await invoke<number>("cmd_restart_embedded_hermes");
              if (!cancelled) {
                setWeixinRestarted(true);
                const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
                onHermesRef.current?.(pyStat.running);
                void refreshWeixinEnv();
              }
            } catch (e) {
              console.error(e);
              if (!cancelled) {
                setWeixinRestarted(false);
                setRestartErr(t("settings.weixinRestartFailed", { msg: ipcErr(e) }));
              }
            }
          }
          return;
        }
        weixinExitStreak.current += 1;
        if (weixinExitStreak.current >= 8) {
          setWeixinPolling(false);
          setWeixinInlineErr(
            t("settings.weixinError", { msg: "process exited without result file" })
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
  }, [weixinPolling, t, refreshWeixinEnv]);

  const weixinPhaseLabel = useCallback(
    (phase: string | undefined) => {
      switch (phase) {
        case "starting":
          return t("settings.weixinPhaseStarting");
        case "connecting":
          return t("settings.weixinPhaseConnecting");
        case "waiting_scan":
          return t("settings.weixinPhaseWaiting");
        case "done":
          return t("settings.weixinPhaseDone");
        case "error":
          return t("settings.weixinPhaseError");
        default:
          return phase ?? "…";
      }
    },
    [t]
  );

  async function startWeixinQr() {
    setWeixinInlineErr(null);
    setRestartErr(null);
    setWeixinRestarted(false);
    setWeixinView(null);
    weixinExitStreak.current = 0;
    try {
      await invoke("cmd_weixin_qr_start");
      setWeixinPolling(true);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setWeixinInlineErr(
        raw.includes("weixin_qr_worker.py")
          ? t("settings.weixinWorkerMissing")
          : t("settings.weixinError", { msg: raw })
      );
    }
  }

  async function cancelWeixinQr() {
    try {
      await invoke("cmd_weixin_qr_cancel");
    } catch (e) {
      console.error(e);
    }
    setWeixinPolling(false);
    weixinExitStreak.current = 0;
  }

  async function manualRestartHermes() {
    setRestartErr(null);
    setRestartBusy(true);
    try {
      await invoke<number>("cmd_restart_embedded_hermes");
      setWeixinRestarted(true);
      const pyStat = await invoke<{ running: boolean }>("cmd_python_status");
      onHermesRunningChange?.(pyStat.running);
      void refreshWeixinEnv();
    } catch (e) {
      console.error(e);
      setRestartErr(t("settings.weixinRestartFailed", { msg: ipcErr(e) }));
    } finally {
      setRestartBusy(false);
    }
  }

  const weixinPartial =
    weixinEnv &&
    !weixinEnv.configured &&
    ((weixinEnv.hasAccountId ?? false) || (weixinEnv.hasToken ?? false));
  const weixinPartialMissing: string[] = [];
  if (weixinPartial && weixinEnv) {
    if (!(weixinEnv.hasAccountId ?? false)) weixinPartialMissing.push("WEIXIN_ACCOUNT_ID");
    if (!(weixinEnv.hasToken ?? false)) weixinPartialMissing.push("WEIXIN_TOKEN");
  }

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      {weixinEnv?.configured ? (
        <div className="rounded-lg border border-emerald-200/90 bg-emerald-50/60 px-3 py-2.5 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/35">
          <p className="font-medium text-emerald-900 dark:text-emerald-100">{t("settings.weixinAlreadyTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-emerald-900/85 dark:text-emerald-100/85">
            {t("settings.weixinAlreadyLead")}
          </p>
          {weixinEnv.accountIdHint ? (
            <p className="mt-1.5 font-mono text-xs text-emerald-950/90 dark:text-emerald-50/90">
              {t("settings.weixinAccountHint", { hint: weixinEnv.accountIdHint })}
            </p>
          ) : null}
        </div>
      ) : null}
      {weixinPartial && weixinEnv ? (
        <div className="rounded-lg border border-amber-200/90 bg-amber-50/70 px-3 py-2.5 text-sm dark:border-amber-900/55 dark:bg-amber-950/30">
          <p className="font-medium text-amber-950 dark:text-amber-100">{t("settings.weixinPartialTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-950/90 dark:text-amber-100/85">
            {t("settings.weixinPartialLead", { missing: weixinPartialMissing.join("、") })}
          </p>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnClass} onClick={() => void startWeixinQr()} disabled={weixinPolling}>
          {weixinEnv?.configured ? t("settings.weixinRescan") : t("settings.weixinStart")}
        </button>
        <button type="button" className={btnClass} onClick={() => void cancelWeixinQr()} disabled={!weixinPolling}>
          {t("settings.weixinCancel")}
        </button>
      </div>
      {weixinInlineErr ? (
        <p className="text-sm text-red-600 dark:text-red-400">{weixinInlineErr}</p>
      ) : null}
      {weixinView?.progress?.phase ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-300">{weixinPhaseLabel(weixinView.progress.phase)}</p>
      ) : null}
      {weixinView?.progress?.liteapp_url ? (
        <div className="space-y-1">
          <a
            href={weixinView.progress.liteapp_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block max-w-full break-all text-sm font-medium text-sky-600 underline-offset-2 hover:underline dark:text-sky-400"
          >
            {t("settings.weixinOpenLink")}
          </a>
          <p className="break-all font-mono text-xs text-zinc-500 dark:text-zinc-500">
            {weixinView.progress.liteapp_url}
          </p>
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{t("settings.weixinAfterScanHint")}</p>
        </div>
      ) : null}
      {weixinView?.progress?.message ? (
        <p className="text-sm text-red-600 dark:text-red-400">{weixinView.progress.message}</p>
      ) : null}
      {weixinView?.result?.ok === true ? (
        <div className="space-y-2 text-sm text-zinc-600 dark:text-zinc-300">
          <p>{weixinRestarted ? t("settings.weixinSuccessDone") : t("settings.weixinSuccess")}</p>
          {weixinView.result.account_id ? (
            <p className="font-mono text-xs text-zinc-500">account_id: {weixinView.result.account_id}</p>
          ) : null}
          {!weixinRestarted ? (
            <button
              type="button"
              className={btnClass}
              disabled={restartBusy}
              onClick={() => void manualRestartHermes()}
            >
              {restartBusy ? t("settings.weixinRestartBusy") : t("settings.weixinRestart")}
            </button>
          ) : null}
          {restartErr ? <p className="text-sm text-red-600 dark:text-red-400">{restartErr}</p> : null}
        </div>
      ) : null}
      {weixinView?.result && weixinView.result.ok === false ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {t("settings.weixinError", { msg: weixinView.result.error ?? "unknown" })}
        </p>
      ) : null}
    </div>
  );
}
