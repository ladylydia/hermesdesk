import { useEffect, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { ask } from "@tauri-apps/plugin-dialog";
import { AppScaffold } from "../../components/AppScaffold";
import { BackButton } from "../../components/ui/BackButton";
import { Button } from "../../components/ui/Button";
import { Toggle } from "../../components/ui/Toggle";
import { useI18n } from "../../lib/i18n";

interface CronJobEntry {
  id: string;
  name: string;
  schedule: string;
  prompt: string;
  deliver: string;
  paused: boolean;
  nextRunAt: string | null;
  lastRunAt: string | null;
  state: string;
  completedAt: string | null;
  lastStatus: string | null;
}

interface CronJobListResponse {
  jobs: CronJobEntry[];
  completed: CronJobEntry[];
  hasAny: boolean;
}

function cronBackTarget(state: unknown): string | null {
  if (typeof state !== "object" || state === null) return null;
  const raw = (state as { cronBackTo?: unknown }).cronBackTo;
  return typeof raw === "string" && raw ? raw : null;
}

export function ScheduledTasksPage() {
  const nav = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const cronBackTo = cronBackTarget(location.state);
  const backPath = cronBackTo === "/chat" ? "/chat" : "/settings";
  const backLabel = cronBackTo === "/chat" ? t("onboarding.backToChat") : t("settings.backToSettings");
  const [jobs, setJobs] = useState<CronJobEntry[]>([]);
  const [completed, setCompleted] = useState<CronJobEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await invoke<CronJobListResponse>("cmd_cron_list");
      setJobs(res.jobs || []);
      setCompleted(res.completed || []);
    } catch (e) {
      console.error("cmd_cron_list failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const refresh = window.setInterval(() => {
      void fetchJobs();
    }, 5000);
    const unlisten = listen("desktop-delivery", () => {
      void fetchJobs();
    });
    return () => {
      window.clearInterval(refresh);
      unlisten.then((fn) => fn());
    };
  }, [fetchJobs]);

  const handleToggle = async (jobId: string, currentPaused: boolean) => {
    try {
      await invoke("cmd_cron_toggle", { jobId });
      setJobs((prev) =>
        prev.map((j) =>
          j.id === jobId ? { ...j, paused: !currentPaused } : j,
        ),
      );
    } catch (e) {
      console.error("cmd_cron_toggle failed:", e);
    }
  };

  const handleDelete = async (jobId: string, jobName: string, fromCompleted: boolean) => {
    const ok = await ask(t("cron.deleteAsk", { name: jobName }), {
      title: t("cron.deleteTitle"),
      kind: "warning",
    });
    if (!ok) return;
    try {
      await invoke("cmd_cron_delete", { jobId });
      if (fromCompleted) {
        setCompleted((prev) => prev.filter((j) => j.id !== jobId));
      } else {
        setJobs((prev) => prev.filter((j) => j.id !== jobId));
      }
    } catch (e) {
      console.error("cmd_cron_delete failed:", e);
    }
  };

  const renderActiveCard = (job: CronJobEntry) => (
    <div
      key={job.id}
      className="rounded-xl border border-zinc-200 bg-white px-5 py-4 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {job.name || job.id.slice(0, 8)}
            </h3>
            {job.paused && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                {t("cron.paused")}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            <span className="font-medium">{t("cron.schedule")}:</span>{" "}
            {job.schedule}
          </p>
          {job.prompt && (
            <p className="mt-0.5 text-xs text-zinc-400 truncate">
              {job.prompt.slice(0, 120)}
            </p>
          )}
          <p className="mt-0.5 text-xs text-zinc-400">
            <span className="font-medium">{t("cron.deliver")}:</span>{" "}
            {job.deliver || "desktop"}
          </p>
          {job.nextRunAt && (
            <p className="mt-0.5 text-xs text-zinc-400">
              <span className="font-medium">{t("cron.nextRun")}:</span>{" "}
              {job.nextRunAt}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Toggle
            value={!job.paused}
            onChange={() => handleToggle(job.id, job.paused)}
            aria-label={t("cron.toggleLabel")}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleDelete(job.id, job.name || job.id, false)}
          >
            {t("cron.delete")}
          </Button>
        </div>
      </div>
    </div>
  );

  const renderCompletedCard = (job: CronJobEntry) => {
    const failed = job.lastStatus === "error";
    return (
      <div
        key={job.id}
        className="rounded-xl border border-zinc-200 bg-zinc-50 px-5 py-4 dark:border-zinc-800 dark:bg-zinc-900/50"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 truncate">
                {job.name || job.id.slice(0, 8)}
              </h3>
              {failed && (
                <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700 dark:bg-rose-900/30 dark:text-rose-400">
                  {t("cron.completedFailed")}
                </span>
              )}
            </div>
            {job.prompt && (
              <p className="mt-1 text-xs text-zinc-500 truncate">
                {job.prompt.slice(0, 120)}
              </p>
            )}
            {job.completedAt && (
              <p className="mt-0.5 text-xs text-zinc-400">
                <span className="font-medium">{t("cron.completedAt")}:</span>{" "}
                {job.completedAt}
              </p>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleDelete(job.id, job.name || job.id, true)}
          >
            {t("cron.delete")}
          </Button>
        </div>
      </div>
    );
  };

  return (
    <AppScaffold className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl space-y-5 px-[var(--hd-page-pad-x)] py-8 sm:py-10">
        <div>
          <BackButton onClick={() => nav(backPath)}>{backLabel}</BackButton>
          <h1 className="hd-page-title">{t("cron.title")}</h1>
          <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
            {t("cron.lead")}
          </p>
        </div>

        {loading ? (
          <p className="text-sm text-zinc-400">{t("cron.loading")}</p>
        ) : jobs.length === 0 && completed.length === 0 ? (
          <div className="rounded-xl border border-zinc-200 bg-white px-5 py-8 text-center dark:border-zinc-800 dark:bg-zinc-900">
            <p className="text-sm text-zinc-500">{t("cron.empty")}</p>
            <p className="mt-1 text-xs text-zinc-400">{t("cron.emptyHint")}</p>
          </div>
        ) : (
          <>
            {jobs.length > 0 && (
              <div>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
                  {t("cron.activeSection")}
                </h2>
                <div className="space-y-3">{jobs.map(renderActiveCard)}</div>
              </div>
            )}
            {completed.length > 0 && (
              <div>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
                  {t("cron.completedSection")}
                </h2>
                <p className="mb-2 text-xs text-zinc-400">{t("cron.completedHint")}</p>
                <div className="space-y-3">{completed.map(renderCompletedCard)}</div>
              </div>
            )}
          </>
        )}
      </div>
    </AppScaffold>
  );
}
