import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { findProvider } from "../../lib/providers";
import { validateKey, validateCustomEndpoint, normalizeOpenAiBaseUrl } from "../../lib/validate";
import { updateDraft, useDraft } from "../../lib/store";

export function GetAccessPass() {
  const nav = useNavigate();
  const draft = useDraft();
  const [key, setKey] = useState(draft.apiKey);
  const [baseUrl, setBaseUrl] = useState(draft.customBaseUrl ?? "");
  const [modelId, setModelId] = useState(draft.customModel ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!draft.providerId) {
    nav("/onboarding/brain", { replace: true });
    return null;
  }
  const provider = findProvider(draft.providerId);

  const isCustom = provider.id === "custom";

  async function openSignup() {
    if (!provider.signupUrl) return;
    try {
      await openUrl(provider.signupUrl);
    } catch (e) {
      console.error(e);
    }
  }

  async function onSave() {
    setBusy(true);
    setError(null);
    try {
      if (isCustom) {
        const mid = modelId.trim();
        if (!mid) {
          setError("Please enter the model name your vendor expects (for example gpt-4o-mini).");
          return;
        }
        const r = await validateCustomEndpoint(baseUrl, key);
        if (!r.ok) {
          setError(r.message ?? "That didn't work.");
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
          setError(r.message ?? "That didn't work.");
          return;
        }
        await invoke("cmd_save_secret", {
          cfg: { provider: provider.id, host: provider.host, model: null, api_base_url: null },
          secret: key.trim(),
        });
        updateDraft({ apiKey: "" });
      }
      nav("/onboarding/vibe");
    } catch (e: unknown) {
      setError(typeof e === "string" ? e : (e as Error)?.message ?? "Couldn't save the pass.");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = isCustom
    ? Boolean(key.trim() && baseUrl.trim() && modelId.trim())
    : Boolean(key.trim());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Get your access pass</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {isCustom ? (
            <>
              Paste the web address of your model API (OpenAI-style) and the access pass your vendor gave you.
              We keep the pass in Windows&apos; built-in vault &mdash; never written to a file.
            </>
          ) : (
            <>
              {provider.label} gives you a long string of letters and numbers that lets HermesDesk
              talk to its brain. We&apos;ll keep it locked in Windows&apos; built-in vault &mdash; never written to a file.
            </>
          )}
        </p>
      </div>

      {!isCustom && (
        <ol className="space-y-3 text-sm text-zinc-700 dark:text-zinc-300 list-decimal pl-5">
          <li>Click the button below. It opens {provider.label} in your browser.</li>
          <li>Sign up or sign in. Click &quot;Create key&quot; (or similar).</li>
          <li>Copy the long string. Come back here and paste it.</li>
        </ol>
      )}

      {isCustom && (
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          The address usually looks like <span className="font-mono text-xs">https://something.example/v1</span>.
          If you are not sure, copy it from your vendor&apos;s dashboard.
        </p>
      )}

      {!isCustom && (
        <button
          onClick={openSignup}
          className="w-full rounded-2xl border border-zinc-300 dark:border-zinc-700 px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-900 transition"
        >
          Open {provider.label} in browser
        </button>
      )}

      {isCustom && (
        <div className="space-y-2">
          <label className="text-sm font-medium">API address (base URL)</label>
          <input
            type="url"
            autoComplete="off"
            spellCheck={false}
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              updateDraft({ customBaseUrl: e.target.value });
            }}
            placeholder="https://your-vendor.example/v1"
            className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 font-mono text-sm"
          />
        </div>
      )}

      {isCustom && (
        <div className="space-y-2">
          <label className="text-sm font-medium">Model name</label>
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={modelId}
            onChange={(e) => {
              setModelId(e.target.value);
              updateDraft({ customModel: e.target.value });
            }}
            placeholder="e.g. gpt-4o-mini or your vendor's model id"
            className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 font-mono text-sm"
          />
        </div>
      )}

      <div className="space-y-2">
        <label className="text-sm font-medium">
          {isCustom ? "Paste your access pass" : "Paste the long string here"}
        </label>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={
            provider.keyPrefixHint ? `${provider.keyPrefixHint}\u2026` : "paste your access pass"
          }
          className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 font-mono text-sm"
        />
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      <button
        onClick={onSave}
        disabled={busy || !canSubmit}
        className="w-full rounded-2xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-6 py-4 text-lg font-medium disabled:opacity-50 hover:opacity-90 transition"
      >
        {busy ? "Checking\u2026" : "Save and continue"}
      </button>
    </div>
  );
}
