import { cn } from "../../lib/cn";

type Props = {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
};

export function Toggle({ value, onChange, disabled, "aria-label": ariaLabel }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={ariaLabel}
      aria-checked={value}
      disabled={disabled}
      onClick={() => onChange(!value)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 dark:focus-visible:ring-sky-500",
        "disabled:cursor-not-allowed disabled:opacity-50",
        value ? "bg-sky-600 dark:bg-sky-500" : "bg-zinc-300 dark:bg-zinc-700",
      )}
    >
      <span
        className={cn(
          "pointer-events-none block h-5 w-5 translate-y-0 rounded-full bg-white shadow-sm ring-0 transition-transform dark:bg-zinc-900",
          value ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}
