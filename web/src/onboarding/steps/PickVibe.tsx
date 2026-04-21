import { useNavigate } from "react-router-dom";
import { updateDraft, useDraft, type Personality } from "../../lib/store";

const VIBES: { id: Personality; title: string; body: string }[] = [
  { id: "helpful",  title: "Helpful",  body: "Neutral, clear, gets things done. The default." },
  { id: "friendly", title: "Friendly", body: "Warmer and more conversational. Says hi back." },
  { id: "concise",  title: "Concise",  body: "Short answers. No fluff. Cuts to the chase." },
];

export function PickVibe() {
  const nav = useNavigate();
  const draft = useDraft();

  function pick(p: Personality) {
    updateDraft({ personality: p });
    nav("/onboarding/done");
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pick a vibe</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">How should HermesDesk talk to you? You can change this later.</p>
      </div>
      <div className="space-y-3">
        {VIBES.map((v) => (
          <button key={v.id} onClick={() => pick(v.id)}
            className={"w-full text-left rounded-2xl border p-5 transition hover:border-zinc-400 dark:hover:border-zinc-500 " +
              (draft.personality === v.id
                ? "border-zinc-900 dark:border-zinc-200 ring-1 ring-zinc-900/10 dark:ring-zinc-100/10"
                : "border-zinc-200 dark:border-zinc-800")}>
            <div className="font-medium">{v.title}</div>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{v.body}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
