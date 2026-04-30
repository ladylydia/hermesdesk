import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

const btnRow =
  "flex flex-col gap-3 sm:flex-row sm:items-stretch sm:justify-end sm:gap-3";

/** Sticks to the bottom of the shell scroll area so long wizard steps keep actions reachable. */
export function WizardFooter({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "sticky bottom-0 z-20 -mx-[var(--hd-page-pad-x)] border-t border-zinc-200/70 bg-white/90 px-[var(--hd-page-pad-x)] pt-4 backdrop-blur-md dark:border-zinc-800/70 dark:bg-zinc-950/90 sm:mx-0",
        "pb-[max(1rem,env(safe-area-inset-bottom,0px))]",
        className
      )}
    >
      {children}
    </div>
  );
}

export function WizardFooterActions({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn(btnRow, className)}>{children}</div>;
}

const primaryBase =
  "inline-flex w-full min-h-[3rem] items-center justify-center rounded-[var(--radius-shell-lg)] px-6 py-3.5 text-base font-medium transition sm:w-auto sm:min-w-[12rem]";

export function WizardPrimaryButton({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        primaryBase,
        "bg-zinc-900 text-white hover:opacity-90 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900",
        className
      )}
      {...props}
    />
  );
}

const secondaryBase =
  "inline-flex w-full min-h-[3rem] items-center justify-center rounded-[var(--radius-shell-lg)] border border-zinc-300/90 px-6 py-3.5 text-base font-medium transition sm:w-auto sm:min-w-[12rem]";

export function WizardSecondaryButton({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        secondaryBase,
        "text-zinc-800 hover:bg-zinc-100/80 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:text-zinc-100 dark:hover:bg-zinc-800/80",
        className
      )}
      {...props}
    />
  );
}

export function WizardFooterHint({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cn(
        "mt-3 text-center text-xs leading-relaxed text-zinc-500 dark:text-zinc-500 sm:text-left",
        className
      )}
    >
      {children}
    </p>
  );
}
