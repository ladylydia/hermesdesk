import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { PROVIDERS, type ProviderId } from "../../lib/providers";
import { useI18n } from "../../lib/i18n";
import { updateDraft, useDraft } from "../../lib/store";
interface CardCfg {
  id: "starter" | "own";
  i18n: "starter" | "own";
  pickProvider: ProviderId;
}

const CARDS: CardCfg[] = [
  { id: "starter", i18n: "starter", pickProvider: "openrouter" },
  { id: "own", i18n: "own", pickProvider: "custom" },
];

export function PickBrain() {
  const { t } = useI18n();
  const nav = useNavigate();
  const draft = useDraft();

  useEffect(() => {
    if (!draft.setupMode) {
      nav("/onboarding/mode", { replace: true });
    }
  }, [draft.setupMode, nav]);

  if (!draft.setupMode) {
    return null;
  }

  function pick(card: CardCfg) {
    if (card.pickProvider === "custom") {
      updateDraft({ providerId: "custom", customBaseUrl: "", customModel: "" });
    } else {
      updateDraft({ providerId: card.pickProvider });
    }
    nav("/onboarding/pass");
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <h1 className="hd-page-title">{t("brain.title")}</h1>
        <p className="hd-lead max-w-prose">{t("brain.lead")}</p>
      </div>
      <div className="space-y-3">
        {CARDS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => pick(c)}
            className="hd-glass-subtle w-full rounded-[var(--radius-shell-lg)] p-5 text-left transition hover:border-zinc-300/90 dark:hover:border-zinc-600"
          >
            <div className="flex items-baseline justify-between gap-3">
              <div className="font-medium">{t(`brain.${c.i18n}.title`)}</div>
              <div className="text-sm text-zinc-500 dark:text-zinc-400">{t(`brain.${c.i18n}.price`)}</div>
            </div>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{t(`brain.${c.i18n}.body`)}</p>
          </button>
        ))}
      </div>

      {draft.providerId && (
        <div className="text-xs text-zinc-500 text-center">
          {t("brain.selected", {
            name: PROVIDERS.find((p) => p.id === draft.providerId)?.label ?? "",
          })}
        </div>
      )}
    </div>
  );
}
