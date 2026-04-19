import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { findProvider } from "../../lib/providers";
import { validateKey } from "../../lib/validate";
import { updateDraft, useDraft } from "../../lib/store";

export function GetAccessPass() {
  const nav = useNavigate();
  const draft = useDraft();
  const provider = draft.providerId ? findProvider(draft.providerId) : null;
  const [key, setKey] = useState(draft.apiKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!provider) {
    nav("/onboarding/brain", { replace: true });
    return null;
  }

  async function openSignup() {
    try { await openUrl(provider!.signupUrl); }
    catch (e) { console.error(e); }
  }

  async function onSave() {
    setBusy(true); setError(null);
    try {
      const r = await validateKey(provider!.id, key);
      if (!r.ok) { setError(r.message ?? "That didn't work."); return; }
      await invoke("cmd_save_secret", {
        cfg: { provider: provider!.id, host: provider!.host, model: null },
        secret: key.trim(),
      });
      updateDraft({ apiKey: "" });
      nav("/onboarding/vibe");
    } catch (e: any) {
      setError(typeof e === "string" ? e : (e?.message ?? "Couldn't save the pass."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Get your access pass</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {provider.label} gives you a long string of letters and numbers that lets HermesDesk
          talk to its brain. We'll keep it locked in Windows' built-in vault &mdash; never written to a file.
        </p>
      </div>

      <ol className="space-y-3 text-sm text-zinc-700 dark:text-zinc-300 list-decimal pl-5">
        <li>Click the button below. It opens {provider.label} in your browser.</li>
        <li>Sign up or sign in. Click "Create key" (or similar).</li>
        <li>Copy the long string. Come back here and paste it.</li>
      </ol>

      <button onClick={openSignup}
        className="w-full rounded-2xl border border-zinc-300 dark:border-zinc-700 px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-900 transition">
        Open {provider.label} in browser
      </button>

      <div className="space-y-2">
        <label className="text-sm font-medium">Paste the long string here</label>
        <input type="password" autoComplete="off" spellCheck={false}
          value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={provider.keyPrefixHint ? `${provider.keyPrefixHint}\u2026` : "paste your access pass"}
          className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-3 font-mono text-sm" />
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      <button onClick={onSave} disabled={busy || !key.trim()}
        className="w-full rounded-2xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-6 py-4 text-lg font-medium disabled:opacity-50 hover:opacity-90 transition">
        {busy ? "Checking\u2026" : "Save and continue"}
      </button>
    </div>
  );
}
