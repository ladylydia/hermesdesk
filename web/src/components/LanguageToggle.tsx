import type { Locale } from "../lib/i18n-core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";

/** 分段按钮形式的语言切换器。 */
export function LanguageToggle({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  const items: { key: Locale; label: string }[] = [
    { key: "zh", label: t("lang.zh") },
    { key: "en", label: t("lang.en") },
  ];

  return (
    <div
      className={cn(
        "inline-flex rounded-lg border border-zinc-200 bg-zinc-100/50 p-0.5 dark:border-zinc-700 dark:bg-zinc-800/50",
        className
      )}
    >
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => setLocale(item.key)}
          className={cn(
            "min-h-[2.25rem] rounded-md px-3 py-1.5 text-sm font-medium transition",
            "active:scale-[0.98]",
            locale === item.key
              ? "hd-btn-segment-active shadow-sm"
              : "hd-btn-segment-idle"
          )}
          aria-pressed={locale === item.key}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
