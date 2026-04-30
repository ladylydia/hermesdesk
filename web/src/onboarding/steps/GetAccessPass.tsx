import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { findProvider, type ProviderId } from "../../lib/providers";
import { useI18n } from "../../lib/i18n";
import { validateKey, validateCustomEndpoint, normalizeOpenAiBaseUrl } from "../../lib/validate";
import { updateDraft, useDraft } from "../../lib/store";
import { clearAllowChatWithoutApi, setAllowChatWithoutApi } from "../../lib/apiKeyGate";
import { getNextPathAfterPass } from "../flowConfig";
import {
  WizardFooter,
  WizardFooterActions,
  WizardFooterHint,
  WizardPrimaryButton,
  WizardSecondaryButton,
} from "../wizard-ui";

type LlmConfigPreview = {
  hasSecret: boolean;
  provider: string | null;
  host: string | null;
  model: string | null;
  apiBaseUrl: string | null;
};

function providerDisplayLabel(id: string | null | undefined): string {
  if (!id) return "";
  try {
    return findProvider(id as ProviderId).label;
  } catch {
    return id;
  }
}

export function GetAccessPass() {
  const { t } = useI18n();
  const nav = useNavigate();
  const draft = useDraft();
  const [key, setKey] = useState(draft.apiKey);
  const [baseUrl, setBaseUrl] = useState(draft.customBaseUrl ?? "");
  const [modelId, setModelId] = useState(draft.customModel ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<LlmConfigPreview | null>(null);

  useEffect(() => {
    invoke<LlmConfigPreview>("cmd_llm_config_preview")
      .then(setPreview)
      .catch(() =>
        setPreview({
          hasSecret: false,
          provider: null,
          host: null,
          model: null,
          apiBaseUrl: null,
        })
      );
  }, []);

  useEffect(() => {
    if (!draft.setupMode) {
      nav("/onboarding/mode", { replace: true });
    }
  }, [draft.setupMode, nav]);

  if (!draft.setupMode) {
    return null;
  }

  if (!draft.providerId) {
    nav("/onboarding/brain", { replace: true });
    return null;
  }
  const provider = findProvider(draft.providerId);

  const isCustom = provider.id === "custom";

  useEffect(() => {
    if (!preview?.hasSecret || !isCustom) return;
    setBaseUrl((u) => (u.trim() ? u : preview.apiBaseUrl?.trim() ?? ""));
    setModelId((m) => (m.trim() ? m : preview.model?.trim() ?? ""));
  }, [preview, isCustom]);

  async function openSignup() {
    if (!provider.signupUrl) return;
    try {
      await openUrl(provider.signupUrl);
    } catch (e) {
      console.error(e);
    }
  }

  async function onSave() {
    const mode = draft.setupMode;
    if (!mode) return;
    setBusy(true);
    setError(null);
    try {
      if (preview?.hasSecret && !key.trim()) {
        try {
          await invoke("cmd_set_personality", { name: draft.personality });
        } catch {
          /* best-effort */
        }
        clearAllowChatWithoutApi();
        nav(getNextPathAfterPass(mode), { replace: true });
        return;
      }
      if (isCustom) {
        const mid = modelId.trim();
        if (!mid) {
          setError(t("pass.errModel"));
          return;
        }
        const r = await validateCustomEndpoint(baseUrl, key);
        if (!r.ok) {
          setError(r.message ?? t("pass.errGeneric"));
          return;
        }
        const normalized = normalizeOpenAiBaseUrl(baseUrl);
        await invoke("cmd_save_secret", {
          cfg: {
            provider: "custom",
            host: "",
            model: mid,
            api_base_url: normalized,
          },
          secret: key.trim(),
        });
        updateDraft({ apiKey: "", customBaseUrl: normalized, customModel: mid });
      } else {
        const r = await validateKey(provider.id, key);
        if (!r.ok) {
          setError(r.message ?? t("pass.errGeneric"));
          return;
        }
        await invoke("cmd_save_secret", {
          cfg: { provider: provider.id, host: provider.host, model: null, api_base_url: null },
          secret: key.trim(),
        });
        updateDraft({ apiKey: "" });
      }
      try {
        await invoke("cmd_set_personality", { name: draft.personality });
      } catch {
        /* best-effort */
      }
      clearAllowChatWithoutApi();
      nav(getNextPathAfterPass(mode), { replace: true });
    } catch (e: unknown) {
      setError(typeof e === "string" ? e : (e as Error)?.message ?? t("pass.errSave"));
    } finally {
      setBusy(false);
    }
  }

  function onSkip() {
    const mode = draft.setupMode;
    if (!mode) return;
    void invoke("cmd_set_personality", { name: draft.personality }).catch(() => {});
    setAllowChatWithoutApi();
    nav(getNextPathAfterPass(mode), { replace: true });
  }

  const continuingWithSaved = Boolean(preview?.hasSecret && !key.trim());
  const canSubmit = continuingWithSaved
    ? true
    : isCustom
      ? Boolean(key.trim() && baseUrl.trim() && modelId.trim())
      : Boolean(key.trim());

  const fieldClass =
    "w-full rounded-[var(--radius-shell)] border border-zinc-300/90 bg-white/90 px-4 py-3 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <h1 className="hd-page-title">{t("pass.title")}</h1>
        <p className="hd-lead max-w-prose">
          {isCustom ? t("pass.customLead1") : t("pass.providerLead", { label: provider.label })}
        </p>
      </div>

      {preview?.hasSecret ? (
        <div className="hd-glass-subtle space-y-2 rounded-[var(--radius-shell)] border border-emerald-200/90 bg-emerald-50/70 px-4 py-3 text-sm leading-relaxed text-emerald-950 dark:border-emerald-800/80 dark:bg-emerald-950/35 dark:text-emerald-100">
          <p className="font-medium">{t("pass.savedBanner")}</p>
          <ul className="list-inside list-disc space-y-1 pl-0.5 text-xs opacity-95">
            {preview.provider ? (
              <li>
                {t("pass.savedProviderLine", {
                  label: providerDisplayLabel(preview.provider),
                  id: preview.provider,
                })}
              </li>
            ) : null}
            {preview.host ? <li>{t("pass.savedHostLine", { host: preview.host })}</li> : null}
            {preview.model ? <li>{t("pass.savedModelLine", { model: preview.model })}</li> : null}
            {preview.apiBaseUrl ? (
              <li className="break-all">{t("pass.savedBaseUrlLine", { url: preview.apiBaseUrl })}</li>
            ) : null}
          </ul>
        </div>
      ) : null}

      {!isCustom && (
        <ol className="hd-glass-subtle list-decimal space-y-2.5 pl-6 pr-4 py-4 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
          <li>{t("pass.steps.s1", { label: provider.label })}</li>
          <li>{t("pass.steps.s2")}</li>
          <li>{t("pass.steps.s3")}</li>
        </ol>
      )}

      {isCustom && <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{t("pass.customHint")}</p>}

      {!isCustom && (
        <button
          type="button"
          onClick={openSignup}
          className="w-full rounded-[var(--radius-shell-lg)] border border-zinc-300/90 px-4 py-3 transition hover:bg-zinc-100/80 dark:border-zinc-700 dark:hover:bg-zinc-900/80"
        >
          {t("pass.openVendor", { label: provider.label })}
        </button>
      )}

      {isCustom && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{t("pass.labelApiUrl")}</label>
          <input
            type="url"
            autoComplete="off"
            spellCheck={false}
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              updateDraft({ customBaseUrl: e.target.value });
            }}
            placeholder={t("pass.phApiUrl")}
            className={fieldClass}
          />
        </div>
      )}

      {isCustom && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{t("pass.labelModel")}</label>
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={modelId}
            onChange={(e) => {
              setModelId(e.target.value);
              updateDraft({ customModel: e.target.value });
            }}
            placeholder={t("pass.phModel")}
            className={fieldClass}
          />
        </div>
      )}

      <div className="space-y-2">
        <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          {isCustom ? t("pass.labelKeyCustom") : t("pass.labelKey")}
        </label>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={
            preview?.hasSecret
              ? t("pass.keyPlaceholderSaved")
              : provider.keyPrefixHint
                ? `${provider.keyPrefixHint}\u2026`
                : t("pass.phKey")
          }
          className={fieldClass}
        />
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      <WizardFooter>
        <WizardFooterActions>
          <WizardSecondaryButton onClick={onSkip} disabled={busy}>
            {t("pass.skipCta")}
          </WizardSecondaryButton>
          <WizardPrimaryButton onClick={() => void onSave()} disabled={busy || !canSubmit}>
            {busy ? t("pass.checkWait") : preview?.hasSecret && !key.trim() ? t("pass.continueCta") : t("pass.cta")}
          </WizardPrimaryButton>
        </WizardFooterActions>
        <WizardFooterHint>{t("pass.skipHint")}</WizardFooterHint>
      </WizardFooter>
    </div>
  );
}
