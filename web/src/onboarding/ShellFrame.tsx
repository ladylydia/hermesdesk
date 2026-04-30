import { ReactNode, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppScaffold } from "../components/AppScaffold";
import { useI18n } from "../lib/i18n";
import { useDraft } from "../lib/store";
import { cn } from "../lib/cn";
import { getBackPath, getIndexInFlow, getStepsForMode, slugFromPathname, type ShellWizardStepId } from "./flowConfig";

export function ShellFrame({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const loc = useLocation();
  const nav = useNavigate();
  const draft = useDraft();

  const slug = useMemo((): ShellWizardStepId => slugFromPathname(loc.pathname), [loc.pathname]);
  const stepList = getStepsForMode(draft.setupMode);
  const idx = getIndexInFlow(slug, draft.setupMode);
  const back = getBackPath(slug, draft.setupMode);

  return (
    <AppScaffold className="flex h-full w-full flex-col">
      <header
        className={cn(
          "shrink-0 border-b border-zinc-200/60 bg-white/45 px-[var(--hd-page-pad-x)] py-3.5 backdrop-blur-md",
          "dark:border-zinc-800/60 dark:bg-zinc-950/40"
        )}
      >
        <div className="mx-auto flex max-w-[var(--hd-content-max)] items-center justify-between gap-3">
          <div
            className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3"
            aria-label={t("brand")}
          >
            {back ? (
              <button
                type="button"
                onClick={() => nav(back)}
                className="shrink-0 rounded-md px-2 py-1 text-sm text-zinc-600 transition hover:bg-zinc-200/50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-zinc-100"
              >
                {slug === "mode" ? t("onboarding.backToChat") : t("onboarding.back")}
              </button>
            ) : null}
            <img
              src="/logo.svg"
              alt=""
              width={24}
              height={24}
              className="h-6 w-6 shrink-0 object-contain dark:opacity-95"
              decoding="async"
              aria-hidden
            />
          </div>
          <div className="flex shrink-0 items-center sm:gap-3">
            <ProgressDots index={idx} total={stepList.length} />
          </div>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[var(--hd-content-max)] space-y-[var(--hd-stack-gap)] px-[var(--hd-page-pad-x)] py-10 sm:py-12">
          {children}
        </div>
      </main>
    </AppScaffold>
  );
}

function ProgressDots({ index, total }: { index: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={
            "h-1.5 rounded-full transition-all " +
            (i <= index
              ? "w-6 bg-zinc-800 dark:bg-zinc-200"
              : "w-1.5 bg-zinc-300 dark:bg-zinc-700")
          }
        />
      ))}
    </div>
  );
}
