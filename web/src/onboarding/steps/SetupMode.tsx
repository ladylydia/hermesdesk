import { useNavigate } from "react-router-dom";
import { useI18n } from "../../lib/i18n";
import { updateDraft, useDraft } from "../../lib/store";
import { WizardFooter, WizardFooterActions, WizardPrimaryButton, WizardSecondaryButton } from "../wizard-ui";

/** Quick vs full setup path — copy stays non-technical for first-time users. */
export function SetupMode() {
  const { t } = useI18n();
  const nav = useNavigate();
  const draft = useDraft();

  function chooseQuick() {
    updateDraft({ setupMode: "quick", useRecommendedDefaults: true });
    nav("/onboarding/welcome");
  }

  function chooseFull() {
    updateDraft({ setupMode: "full", useRecommendedDefaults: false });
    nav("/onboarding/welcome");
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <h1 className="hd-page-title">{t("setupMode.title")}</h1>
        <p className="hd-lead max-w-prose">{t("setupMode.lead")}</p>
      </div>

      {draft.setupMode ? (
        <p className="text-sm text-amber-800/90 dark:text-amber-200/90">{t("setupMode.againHint")}</p>
      ) : null}

      <div className="space-y-4">
        <div className="hd-glass-subtle space-y-2 rounded-[var(--radius-shell-lg)] p-5">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            {t("setupMode.quickTitle")}
          </h2>
          <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{t("setupMode.quickBody")}</p>
        </div>
        <div className="hd-glass-subtle space-y-2 rounded-[var(--radius-shell-lg)] p-5">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            {t("setupMode.fullTitle")}
          </h2>
          <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{t("setupMode.fullBody")}</p>
        </div>
      </div>

      <WizardFooter>
        <WizardFooterActions>
          <WizardSecondaryButton onClick={chooseFull}>
            {t("setupMode.chooseFullCta")}
          </WizardSecondaryButton>
          <WizardPrimaryButton onClick={chooseQuick}>
            {t("setupMode.chooseQuickCta")}
          </WizardPrimaryButton>
        </WizardFooterActions>
      </WizardFooter>
    </div>
  );
}
