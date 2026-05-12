import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { findProvider, type ProviderId } from "../../lib/providers";
import { useI18n } from "../../lib/i18n";
import { validateKey, validateCustomEndpoint, normalizeOpenAiBaseUrl } from "../../lib/validate";
import { updateDraft, useDraft } from "../../lib/store";
import { clearAllowChatWithoutApi } from "../../lib/apiKeyGate";
import { getBackPath, getNextPathAfterPass } from "../flowConfig";
import { cn } from "../../lib/cn";
import { Check, Loader2 } from "lucide-react";
import {
  WizardFooter, WizardFooterActions,
  WizardPrimaryButton,
} from "../wizard-ui";

type LlmConfigPreview = {
  hasSecret: boolean; provider: string | null; host: string | null;
  model: string | null; apiBaseUrl: string | null;
};

function providerDisplayLabel(id: string | null | undefined): string {
  if (!id) return "";
  try { return findProvider(id as ProviderId).label; } catch { return id; }
}

const DROPDOWN_PROVIDERS: (ProviderId | "custom")[] = ["deepseek", "openai", "anthropic", "groq", "mistral", "openrouter", "custom"];

const PROVIDER_PRESETS: Record<string, { host: string; model: string }> = {
  deepseek: { host: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  openai: { host: "https://api.openai.com/v1", model: "gpt-4o" },
  anthropic: { host: "https://api.anthropic.com/v1", model: "claude-sonnet-4-20250514" },
  groq: { host: "https://api.groq.com/openai/v1", model: "qwen-2.5-32b" },
  mistral: { host: "https://api.mistral.ai/v1", model: "mistral-medium" },
  openrouter: { host: "https://openrouter.ai/api/v1", model: "deepseek/deepseek-v4-flash" },
};

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
  const [dropdownProvider, setDropdownProvider] = useState<ProviderId | "">("");
  const [validationStatus, setValidationStatus] = useState<"idle" | "validating" | "valid" | "invalid">("idle");
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  useEffect(() => {
    invoke<LlmConfigPreview>("cmd_llm_config_preview").then(setPreview)
      .catch(() => setPreview({ hasSecret: false, provider: null, host: null, model: null, apiBaseUrl: null }));
  }, []);

  // Debounced auto-validation of the API key
  useEffect(() => {
    const pid = draft.providerId;
    const trimmed = key.trim();
    if (!trimmed || !pid) {
      setValidationStatus("idle");
      setValidationMessage(null);
      return;
    }
    if (preview?.hasSecret && !trimmed) {
      setValidationStatus("valid");
      setValidationMessage(null);
      return;
    }
    const timer = setTimeout(async () => {
      setValidationStatus("validating");
      try {
        const result = pid === "custom"
          ? await validateCustomEndpoint(baseUrl, key)
          : await validateKey(pid, key);
        setValidationStatus(result.ok ? "valid" : "invalid");
        setValidationMessage(result.message ?? null);
      } catch {
        setValidationStatus("invalid");
        setValidationMessage(t("pass.errGeneric"));
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [key, baseUrl, draft.providerId, preview?.hasSecret, t]);

  useEffect(() => {
    if (!draft.setupMode) nav("/onboarding/mode", { replace: true });
  }, [draft.setupMode, nav]);

  useEffect(() => {
    if (draft.setupMode && !draft.providerId) nav("/onboarding/brain", { replace: true });
  }, [draft.providerId, draft.setupMode, nav]);

  const provider = draft.providerId ? findProvider(draft.providerId) : null;
  const isCustom = provider?.id === "custom";

  // Pre-fill from saved preview
  useEffect(() => {
    if (!preview?.hasSecret || !isCustom) return;
    setBaseUrl((u) => (u.trim() ? u : preview.apiBaseUrl?.trim() ?? ""));
    setModelId((m) => (m.trim() ? m : preview.model?.trim() ?? ""));
  }, [preview, isCustom]);

  const effectiveProvider = useMemo(() => {
    if (!provider) return null;
    if (!isCustom) return provider;
    if (dropdownProvider && dropdownProvider !== "custom") return findProvider(dropdownProvider);
    return null;
  }, [isCustom, provider, dropdownProvider]);

  if (!draft.setupMode || !provider) return null;

  async function openSignup() {
    if (!effectiveProvider?.signupUrl) return;
    try { await openUrl(effectiveProvider.signupUrl); } catch (e) { console.error(e); }
  }

  async function onSave() {
    const mode = draft.setupMode; if (!mode || !provider) return;
    setBusy(true); setError(null);
    try {
      if (preview?.hasSecret && !key.trim()) {
        try { await invoke("cmd_set_personality", { name: draft.personality }); } catch {
          /* optional */
        }
        clearAllowChatWithoutApi(); nav(getNextPathAfterPass(mode), { replace: true }); return;
      }
      if (isCustom) {
        const dp = dropdownProvider && dropdownProvider !== "custom" ? dropdownProvider : "custom";
        const mid = dp !== "custom" ? (PROVIDER_PRESETS[dp]?.model ?? modelId.trim()) : modelId.trim();
        if (!mid) { setError(t("pass.errModel")); return; }
        const url = baseUrl.trim();
        const r = await validateCustomEndpoint(url, key);
        if (!r.ok) { setError(r.message ?? t("pass.errGeneric")); return; }
        await invoke("cmd_save_secret", {
          cfg: { provider: dp, host: effectiveProvider?.host ?? "", model: mid, api_base_url: normalizeOpenAiBaseUrl(url) },
          secret: key.trim(),
        });
        updateDraft({ apiKey: "", customBaseUrl: url, customModel: mid });
      } else {
        const r = await validateKey(provider.id, key);
        if (!r.ok) { setError(r.message ?? t("pass.errGeneric")); return; }
        const isDeepseek = provider.id === "deepseek";
        const dsPreset = isDeepseek ? PROVIDER_PRESETS.deepseek : null;
        await invoke("cmd_save_secret", {
          cfg: {
            provider: provider.id,
            host: provider.host,
            model: dsPreset ? dsPreset.model : null,
            api_base_url: isDeepseek
              ? normalizeOpenAiBaseUrl(`https://${provider.host}/v1`)
              : null,
          },
          secret: key.trim(),
        });
        updateDraft({ apiKey: "" });
      }
      try { await invoke("cmd_set_personality", { name: draft.personality }); } catch {
        /* optional */
      }
      clearAllowChatWithoutApi(); nav(getNextPathAfterPass(mode), { replace: true });
    } catch (e: unknown) {
      setError(typeof e === "string" ? e : (e as Error)?.message ?? t("pass.errSave"));
    } finally { setBusy(false); }
  }

  const continuingWithSaved = Boolean(preview?.hasSecret && !key.trim());
  const canSubmit = continuingWithSaved ? true : isCustom ? Boolean(key.trim() && baseUrl.trim() && modelId.trim()) : Boolean(key.trim());
  const f = "w-full rounded-[var(--radius-shell)] border border-zinc-300/90 bg-white/90 px-4 py-3 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

  return (<div className="space-y-8">
    <div className="space-y-3">
      <h1 className="hd-page-title">{t("pass.title")}</h1>
      <p className="hd-lead max-w-prose">{isCustom ? t("pass.customLead1") : t("pass.providerLead", { label: provider.label })}</p>
    </div>

    {preview?.hasSecret && (<div className="hd-glass-subtle space-y-2 rounded-[var(--radius-shell)] border border-emerald-200/90 bg-emerald-50/70 px-4 py-3 text-sm leading-relaxed text-emerald-950 dark:border-emerald-800/80 dark:bg-emerald-950/35 dark:text-emerald-100">
      <p className="font-medium">{t("pass.savedBanner")}</p>
      <ul className="list-inside list-disc space-y-1 pl-0.5 text-xs opacity-95">
        {preview.provider ? <li>{t("pass.savedProviderLine", { label: providerDisplayLabel(preview.provider), id: preview.provider })}</li> : null}
        {preview.host ? <li>{t("pass.savedHostLine", { host: preview.host })}</li> : null}
        {preview.model ? <li>{t("pass.savedModelLine", { model: preview.model })}</li> : null}
        {preview.apiBaseUrl ? <li className="break-all">{t("pass.savedBaseUrlLine", { url: preview.apiBaseUrl })}</li> : null}
      </ul>
    </div>)}

    {!isCustom && (<ol className="hd-glass-subtle list-decimal space-y-2.5 pl-6 pr-4 py-4 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
      <li>{t("pass.steps.s1", { label: provider.label })}</li>
      <li>{t("pass.steps.s2")}</li>
      <li>{t("pass.steps.s3")}</li>
    </ol>)}

    {isCustom && (<div className="space-y-2">
      <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{t("pass.labelProvider")}</label>
      <select value={dropdownProvider} onChange={(e) => {
        const v = e.target.value as typeof dropdownProvider;
        setDropdownProvider(v);
        if (v && v !== "custom" && PROVIDER_PRESETS[v]) {
          setBaseUrl(PROVIDER_PRESETS[v].host);
          setModelId(PROVIDER_PRESETS[v].model);
          updateDraft({ customBaseUrl: PROVIDER_PRESETS[v].host, customModel: PROVIDER_PRESETS[v].model });
        } else if (v === "custom") {
          setBaseUrl("");
          setModelId("");
          updateDraft({ customBaseUrl: "", customModel: "" });
        }
      }} className="w-full rounded-[var(--radius-shell)] border border-zinc-300/90 bg-white/90 px-4 py-3 text-sm dark:border-zinc-700 dark:bg-zinc-900/90">
        <option value="">{t("pass.selectProvider")}</option>
        {DROPDOWN_PROVIDERS.filter((pid) => pid !== "custom").map((pid) => <option key={pid} value={pid}>{findProvider(pid).label}</option>)}
        <option disabled>──</option>
        <option value="custom">{t("pass.providerCustomLabel")}</option>
      </select>
    </div>)}

    {isCustom && (<div className="space-y-2">
      <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{t("pass.labelApiUrl")}</label>
      <input type="url" autoComplete="off" spellCheck={false} value={baseUrl}
        onChange={(e) => { setBaseUrl(e.target.value); updateDraft({ customBaseUrl: e.target.value }); }}
        placeholder={t("pass.phApiUrl")} className={f} />
    </div>)}

    {isCustom && (<div className="space-y-2">
      <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{t("pass.labelModel")}</label>
      <input type="text" autoComplete="off" spellCheck={false} value={modelId}
        onChange={(e) => { setModelId(e.target.value); updateDraft({ customModel: e.target.value }); }}
        placeholder={t("pass.phModel")} className={f} />
    </div>)}

    <div className="space-y-2">
      <label className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{isCustom ? t("pass.labelKeyCustom") : t("pass.labelKey")}</label>
      <div className="relative">
        <input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={preview?.hasSecret ? t("pass.keyPlaceholderSaved") : effectiveProvider?.keyPrefixHint ? `${effectiveProvider.keyPrefixHint}\u2026` : t("pass.phKey")}
          className={cn(
            f,
            "pr-10",
            validationStatus === "valid" && "border-emerald-400 dark:border-emerald-600",
            validationStatus === "invalid" && "border-red-400 dark:border-red-600",
          )} />
        {validationStatus === "validating" && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
            <Loader2 className="h-4 w-4 animate-spin text-zinc-400" />
          </span>
        )}
        {validationStatus === "valid" && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-emerald-500">
            <Check className="h-4 w-4" strokeWidth={3} />
          </span>
        )}
      </div>
      {validationStatus === "invalid" && validationMessage && (
        <p className="text-sm text-red-600 dark:text-red-400">{validationMessage}</p>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>

    {!isCustom && (<button type="button" onClick={openSignup}
      className="w-full rounded-[var(--radius-shell-lg)] border border-zinc-300/90 px-4 py-3 transition hover:bg-zinc-100/80 dark:border-zinc-700 dark:hover:bg-zinc-900/80">
      {t("pass.openVendor", { label: provider.label })}</button>)}

    <WizardFooter>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <WizardPrimaryButton onClick={() => nav(getBackPath("pass", draft.setupMode!)!)}>
          {t("onboarding.back")}
        </WizardPrimaryButton>
        <WizardFooterActions>
          <WizardPrimaryButton onClick={() => void onSave()} disabled={busy || !canSubmit}>
            {busy ? t("pass.checkWait") : preview?.hasSecret && !key.trim() ? t("pass.continueCta") : t("pass.cta")}
          </WizardPrimaryButton>
        </WizardFooterActions>
      </div>
    </WizardFooter>
  </div>);
}
