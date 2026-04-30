import { useLayoutEffect, useMemo } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useI18n } from "../../lib/i18n";
import { clearDraft, updateDraft, useDraft } from "../../lib/store";
import { CHAT_FROM_ONBOARDING_STATE } from "../../lib/chatLocationState";
import { CATALOG_BY_SECTION } from "../setupCatalog/optionData";
import { SetupOptionsTable } from "../SetupOptionsTable";
import { getNextPath, getRedirectForInvalidUrlStep, isLastStep, stepToPath } from "../flowConfig";
import type { PostPassSectionId } from "../setupCatalog/optionTypes";
import {
  getInitialSectionSelection,
  SECTION_SELECTION_MODE,
  selectionSatisfied,
} from "../sectionSelection";
import { WizardFooter, WizardFooterActions, WizardPrimaryButton } from "../wizard-ui";

export type { PostPassSectionId };

export function SectionPlaceholderStep({ id }: { id: PostPassSectionId }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const draft = useDraft();
  const mode = draft.setupMode;

  if (!mode) {
    return <Navigate to={stepToPath("mode")} replace />;
  }
  const redirect = getRedirectForInvalidUrlStep(id, mode);
  if (redirect) {
    return <Navigate to={redirect} replace />;
  }

  const next = getNextPath(id, mode);
  const last = isLastStep(id, mode);
  const catalog = CATALOG_BY_SECTION[id];
  const selMode = SECTION_SELECTION_MODE[id];
  const initialSel = useMemo(() => getInitialSectionSelection(id), [id]);
  const rowSel = draft.wizardSelection?.[id] ?? initialSel;

  useLayoutEffect(() => {
    if (draft.wizardSelection?.[id] != null) return;
    updateDraft({
      wizardSelection: {
        ...(draft.wizardSelection ?? {}),
        [id]: initialSel,
      },
    });
  }, [id, initialSel, draft.wizardSelection]);

  const canProceed = useMemo(() => selectionSatisfied(rowSel, selMode), [rowSel, selMode]);

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <h1 className="hd-page-title">{t(`setupSection.${id}.title`)}</h1>
        <p className="hd-lead max-w-prose">{t(`setupSection.${id}.lead`)}</p>
      </div>
      <div className="space-y-2">
        <SetupOptionsTable
          section={id}
          items={catalog}
          selectionMode={selMode}
          defaultSelection={initialSel}
          modalSize={id === "gateway" ? "lg" : "md"}
        />
        {!canProceed ? (
          <p className="text-sm text-amber-800 dark:text-amber-200" role="status">
            {t("setupOptions.mustChoose")}
          </p>
        ) : null}
      </div>
      <WizardFooter>
        <WizardFooterActions>
          {last ? (
            <WizardPrimaryButton
              disabled={!canProceed}
              onClick={() => {
                if (!canProceed) return;
                clearDraft();
                nav("/chat", { replace: true, state: CHAT_FROM_ONBOARDING_STATE });
              }}
            >
              {t("onboarding.finishToChat")}
            </WizardPrimaryButton>
          ) : (
            <WizardPrimaryButton
              disabled={!canProceed}
              onClick={() => {
                if (!canProceed || next === "complete") return;
                nav(next, { replace: true });
              }}
            >
              {t("onboarding.next")}
            </WizardPrimaryButton>
          )}
        </WizardFooterActions>
      </WizardFooter>
    </div>
  );
}
