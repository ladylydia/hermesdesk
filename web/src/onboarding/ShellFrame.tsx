import { ReactNode } from "react";
import { useLocation } from "react-router-dom";

const STEPS = ["welcome", "brain", "pass", "vibe", "done"] as const;

export function ShellFrame({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const current = loc.pathname.split("/").pop() || "welcome";
  const idx = Math.max(0, STEPS.indexOf(current as (typeof STEPS)[number]));

  return (
    <div className="h-full w-full bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex flex-col">
      <header className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold tracking-tight">
          <span aria-hidden>☤</span>
          <span>HermesDesk</span>
        </div>
        <ProgressDots index={idx} total={STEPS.length} />
      </header>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-xl px-6 py-10">{children}</div>
      </main>
    </div>
  );
}

function ProgressDots({ index, total }: { index: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          aria-hidden
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
