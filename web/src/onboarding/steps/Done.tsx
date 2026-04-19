import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { clearDraft, useDraft } from "../../lib/store";

export function Done() {
  const draft = useDraft();

  useEffect(() => {
    invoke("cmd_set_personality", { name: draft.personality }).catch(() => {});
  }, [draft.personality]);

  async function openWorkspace() {
    try { await invoke("cmd_open_workspace"); }
    catch (e) { console.error(e); }
  }

  function openChat() {
    clearDraft();
    window.location.replace("/");
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="text-4xl">{"\u{1F44B}"}</div>
        <h1 className="text-3xl font-semibold tracking-tight">You're set.</h1>
        <p className="text-zinc-600 dark:text-zinc-400 leading-relaxed">
          HermesDesk is ready. Try asking it to write something, plan your week,
          or summarize a file you drop into your workspace folder.
        </p>
      </div>

      <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 p-5 space-y-2">
        <div className="text-sm font-medium">Your workspace</div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          HermesDesk can only read and write files inside this folder. Drop things in here for it to work on.
        </p>
        <button onClick={openWorkspace}
          className="text-sm underline underline-offset-4 hover:text-zinc-900 dark:hover:text-zinc-100">
          Open workspace folder
        </button>
      </div>

      <button onClick={openChat}
        className="w-full rounded-2xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-6 py-4 text-lg font-medium hover:opacity-90 transition">
        Start chatting
      </button>
    </div>
  );
}
