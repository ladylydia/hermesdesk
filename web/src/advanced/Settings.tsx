import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ask } from "@tauri-apps/plugin-dialog";

interface Status {
  workspace: string;
  hasSecret: boolean;
  pythonRunning: boolean;
}

export function Settings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [powerUser, setPowerUser] = useState(false);
  const [showRecipeMarket, setShowRecipeMarket] = useState(false);

  useEffect(() => {
    (async () => {
      const [workspace, hasSecret, pyStat] = await Promise.all([
        invoke<string>("cmd_workspace_path"),
        invoke<boolean>("cmd_has_secret"),
        invoke<{ running: boolean }>("cmd_python_status"),
      ]);
      setStatus({ workspace, hasSecret, pythonRunning: pyStat.running });
      try {
        const v = await invoke<boolean>("cmd_get_power_user");
        setPowerUser(!!v);
      } catch { /* command not implemented yet */ }
      try {
        const m = await invoke<boolean>("cmd_get_show_recipe_market");
        setShowRecipeMarket(!!m);
      } catch { /* older build */ }
    })().catch(console.error);
  }, []);

  async function toggleRecipeMarket(next: boolean) {
    try {
      await invoke("cmd_set_show_recipe_market", { enabled: next });
      setShowRecipeMarket(next);
    } catch (e) {
      console.error(e);
    }
  }

  async function togglePowerUser(next: boolean) {
    if (next) {
      const ok = await ask(
        "Power user mode lets HermesDesk run shell commands, browser automation, and code on your PC.\n\n" +
        "Each command still asks your permission, but mistakes can damage your system.\n\nTurn it on?",
        { title: "Enable power user mode?", kind: "warning" }
      );
      if (!ok) return;
    }
    try {
      await invoke("cmd_set_power_user", { enabled: next });
      setPowerUser(next);
    } catch (e) { console.error(e); }
  }

  async function clearKey() {
    const ok = await ask("This signs you out of your AI provider. You'll need to paste your access pass again.", {
      title: "Sign out?", kind: "warning"
    });
    if (!ok) return;
    await invoke("cmd_clear_secret");
    setStatus((s) => s ? { ...s, hasSecret: false } : s);
  }

  return (
    <div className="h-full bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 overflow-y-auto">
      <div className="mx-auto max-w-2xl px-6 py-10 space-y-8">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

        <Section title="Workspace" desc="HermesDesk can only touch files inside this folder.">
          <code className="text-xs break-all">{status?.workspace ?? "\u2026"}</code>
          <Button onClick={() => invoke("cmd_open_workspace")}>Open folder</Button>
        </Section>

        <Section title="Access pass" desc={status?.hasSecret ? "Saved in Windows Credential Manager." : "Not set."}>
          <Button onClick={clearKey} disabled={!status?.hasSecret}>Sign out</Button>
        </Section>

        <Section title="Power user mode"
          desc="Unlocks shell commands, code execution, browser automation, MCP servers, and cron. Off by default. Each action still asks permission.">
          <Toggle value={powerUser} onChange={togglePowerUser} />
        </Section>

        <Section title="Recipe market banner"
          desc="When enabled, the Hermes Skills page shows a short preview banner (no downloads yet). The embedded server reads this from your app data folder.">
          <Toggle value={showRecipeMarket} onChange={toggleRecipeMarket} />
        </Section>

        <Section title="Status">
          <ul className="text-sm space-y-1 text-zinc-600 dark:text-zinc-400">
            <li>Helper running: {status?.pythonRunning ? "yes" : "no"}</li>
            <li>Access pass saved: {status?.hasSecret ? "yes" : "no"}</li>
          </ul>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-zinc-200 dark:border-zinc-800 p-5 space-y-3">
      <div>
        <h2 className="font-medium">{title}</h2>
        {desc && <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{desc}</p>}
      </div>
      <div className="flex items-center gap-3 flex-wrap">{children}</div>
    </section>
  );
}

function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...props}
      className="rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-900 disabled:opacity-50" />
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button onClick={() => onChange(!value)}
      className={"relative inline-flex h-6 w-11 items-center rounded-full transition " +
        (value ? "bg-emerald-600" : "bg-zinc-300 dark:bg-zinc-700")}>
      <span className={"inline-block h-4 w-4 transform rounded-full bg-white transition " +
        (value ? "translate-x-6" : "translate-x-1")} />
    </button>
  );
}
