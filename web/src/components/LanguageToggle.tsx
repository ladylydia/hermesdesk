import { useEffect, useRef, useState } from "react";
import type { Locale } from "../lib/i18n-core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

/** 点击「语言」后在下方展开两行：中文、English。 */
export function LanguageToggle({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (l: Locale) => {
    setLocale(l);
    setOpen(false);
  };

  const rows: { locale: Locale; label: string }[] = [
    { locale: "zh", label: t("lang.zh") },
    { locale: "en", label: t("lang.en") },
  ];

  return (
    <div ref={rootRef} className={cn("relative inline-block text-left", className)}>
      <button
        type="button"
        className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls="hermesdesk-lang-menu"
        id="hermesdesk-lang-trigger"
      >
        {t("lang.label")}
      </button>

      {open ? (
        <div
          id="hermesdesk-lang-menu"
          role="menu"
          aria-labelledby="hermesdesk-lang-trigger"
          className={cn(
            "absolute left-0 top-full z-[100] mt-0.5 min-w-[7rem] py-0.5",
            "border border-zinc-200 bg-white shadow-sm dark:border-zinc-600 dark:bg-zinc-900"
          )}
        >
          {rows.map((row, i) => (
            <button
              key={row.locale}
              type="button"
              role="menuitem"
              onClick={() => pick(row.locale)}
              className={cn(
                "flex w-full items-center px-2.5 py-1.5 text-left text-sm",
                "text-zinc-800 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800",
                locale === row.locale && "bg-zinc-50 font-medium dark:bg-zinc-800/80",
                i > 0 && "border-t border-zinc-100 dark:border-zinc-700/80"
              )}
            >
              {row.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
