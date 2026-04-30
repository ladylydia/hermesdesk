import { cn } from "../lib/cn";

type Props = {
  children: React.ReactNode;
  className?: string;
  /** Narrow column for forms / onboarding (max-width + horizontal padding) */
  variant?: "full" | "narrow";
  /** Chat shell: flat white canvas (Kimi-style) instead of gradient. */
  surface?: "default" | "chat";
};

const narrowInner = "mx-auto w-full max-w-[var(--hd-content-max)] px-[var(--hd-page-pad-x)] py-[var(--hd-page-pad-y)]";

export function AppScaffold({ children, className, variant = "full", surface = "default" }: Props) {
  return (
    <div
      className={cn(
        "min-h-full w-full text-zinc-900 dark:text-zinc-100",
        surface === "chat"
          ? "bg-zinc-50 dark:bg-[#0F172A]"
          : "bg-gradient-to-br from-zinc-100/90 via-white to-zinc-50/85 dark:from-zinc-950 dark:via-[#0F172A] dark:to-zinc-950",
        variant === "narrow" && "flex flex-col",
        className
      )}
    >
      {variant === "narrow" ? <div className={cn(narrowInner, "flex-1")}>{children}</div> : children}
    </div>
  );
}
