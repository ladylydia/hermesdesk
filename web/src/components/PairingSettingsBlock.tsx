import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

export type PendingInfo = {
  platform: string;
  code: string;
  userId: string;
  userName: string;
  ageMinutes: number;
};

export type ApprovedInfo = {
  platform: string;
  userId: string;
  userName: string;
};

export type PairingSnapshot = {
  pending: PendingInfo[];
  approved: ApprovedInfo[];
};

const btnClass =
  "rounded-lg border border-zinc-300/90 bg-white px-3 py-1.5 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

const btnSmallClass =
  "rounded-md border border-zinc-300/90 bg-white px-2 py-1 text-xs font-medium text-zinc-700 transition hover:bg-zinc-50 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90";

export function PairingSettingsBlock({
  platform,
  className,
}: {
  platform: string;
  className?: string;
}) {
  const { t } = useI18n();
  const [snapshot, setSnapshot] = useState<PairingSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snap = await invoke<PairingSnapshot>("cmd_pairing_list", {
        platform: platform || null,
      });
      setSnapshot(snap);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [platform]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleApprove(code: string) {
    setError(null);
    setResult(null);
    try {
      const msg = await invoke<string>("cmd_pairing_approve", {
        platform,
        code,
      });
      setResult(msg);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRevoke(userId: string) {
    setError(null);
    setResult(null);
    try {
      const msg = await invoke<string>("cmd_pairing_revoke", {
        platform,
        userId,
      });
      setResult(msg);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const hasData =
    (snapshot?.pending.length ?? 0) > 0 ||
    (snapshot?.approved.length ?? 0) > 0;

  return (
    <div className={cn("w-full min-w-0 space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnClass} onClick={load} disabled={loading}>
          {loading ? "…" : t("settings.telegramPairingRefresh")}
        </button>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {t("settings.telegramPairingError", { msg: error })}
        </p>
      ) : null}

      {result ? (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          {result}
        </p>
      ) : null}

      {!hasData && !loading ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {t("settings.telegramPairingNone")}
        </p>
      ) : null}

      {(snapshot?.pending.length ?? 0) > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">
            {t("settings.telegramPairingPendingHeader")}
          </p>
          <div className="space-y-1.5">
            {snapshot!.pending.map((p) => (
              <div
                key={`${p.platform}-${p.code}`}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200/80 bg-amber-50/50 px-3 py-2 dark:border-amber-800/50 dark:bg-amber-950/20"
              >
                <code className="text-sm font-mono text-amber-900 dark:text-amber-100">
                  {p.code}
                </code>
                <span className="text-xs text-zinc-600 dark:text-zinc-400">
                  {p.userName || p.userId}
                </span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  {p.ageMinutes}m ago
                </span>
                <button
                  type="button"
                  className={cn(btnSmallClass, "ml-auto")}
                  onClick={() => handleApprove(p.code)}
                >
                  {t("settings.telegramPairingApprove")}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(snapshot?.approved.length ?? 0) > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">
            {t("settings.telegramPairingApprovedHeader")}
          </p>
          <div className="space-y-1.5">
            {snapshot!.approved.map((a) => (
              <div
                key={`${a.platform}-${a.userId}`}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200/80 bg-emerald-50/50 px-3 py-2 dark:border-emerald-800/50 dark:bg-emerald-950/20"
              >
                <span className="text-sm text-emerald-900 dark:text-emerald-100">
                  {a.userName || a.userId}
                </span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500 font-mono">
                  {a.userId}
                </span>
                <button
                  type="button"
                  className={cn(btnSmallClass, "ml-auto")}
                  onClick={() => handleRevoke(a.userId)}
                >
                  {t("settings.telegramPairingRevoke")}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
