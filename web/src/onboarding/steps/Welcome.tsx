import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../lib/i18n";
import { useDraft } from "../../lib/store";
import { WizardFooter, WizardPrimaryButton } from "../wizard-ui";

export function Welcome() {
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

  const modeLabel = draft.setupMode === "quick" ? t("setupMode.quickTitle") : t("setupMode.fullTitle");

  return (
    <div className="space-y-10">
      <div className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-wide text-sky-700/90 dark:text-sky-300/90">
          {t("welcome.modePicked")}: {modeLabel}
        </p>
        <h1 className="hd-page-title">{t("welcome.title")}</h1>
        <p className="hd-lead max-w-prose">{t("welcome.lead")}</p>
      </div>

      <ul className="hd-glass-subtle space-y-3.5 p-5 text-zinc-700 dark:text-zinc-300">
        <li className="flex gap-3">
          <Bullet />
          <span className="text-[0.95rem] leading-relaxed">{t("welcome.li1")}</span>
        </li>
        <li className="flex gap-3">
          <Bullet />
          <span className="text-[0.95rem] leading-relaxed">{t("welcome.li2")}</span>
        </li>
        <li className="flex gap-3">
          <Bullet />
          <span className="text-[0.95rem] leading-relaxed">{t("welcome.li3")}</span>
        </li>
      </ul>

      <WizardFooter>
        <div className="flex justify-end">
          <WizardPrimaryButton onClick={() => nav("/onboarding/brain")}>{t("welcome.cta")}</WizardPrimaryButton>
        </div>
      </WizardFooter>
    </div>
  );
}

function Bullet() {
  return (
    <span aria-hidden className="mt-1 inline-block h-2 w-2 rounded-full bg-zinc-400 dark:bg-zinc-600" />
  );
}
