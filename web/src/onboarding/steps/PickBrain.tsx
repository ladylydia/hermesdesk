import { useNavigate } from "react-router-dom";
import { PROVIDERS, type ProviderId } from "../../lib/providers";
import { updateDraft, useDraft } from "../../lib/store";

interface CardCfg {
  id: "starter" | "best" | "own";
  title: string;
  price: string;
  body: string;
  recommended?: boolean;
  pickProvider: ProviderId;
}

const CARDS: CardCfg[] = [
  { id: "starter", title: "Free starter", price: "$0 / chat",
    body: "Slower and rate-limited, but free forever. Good for trying things out.",
    pickProvider: "openrouter" },
  { id: "best", title: "Best quality", price: "Pennies per chat",
    body: "Top models. You pay your provider directly \u2014 usually a few dollars a month.",
    recommended: true, pickProvider: "openrouter" },
  { id: "own", title: "My own API", price: "\u2014",
    body: "Use any OpenAI-compatible address and access pass (your vendor, your keys).",
    pickProvider: "custom" },
];

export function PickBrain() {
  const nav = useNavigate();
  const draft = useDraft();

  function pick(card: CardCfg) {
    if (card.pickProvider === "custom") {
      updateDraft({ providerId: "custom", customBaseUrl: "", customModel: "" });
    } else {
      updateDraft({ providerId: card.pickProvider });
    }
    nav("/onboarding/pass");
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pick a brain</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          HermesDesk borrows its smarts from one of these. You can change your mind anytime in Settings.
        </p>
      </div>
      <div className="space-y-3">
        {CARDS.map((c) => (
          <button key={c.id} onClick={() => pick(c)}
            className={"w-full text-left rounded-2xl border p-5 transition hover:border-zinc-400 dark:hover:border-zinc-500 " +
              (c.recommended
                ? "border-zinc-900 dark:border-zinc-200 ring-1 ring-zinc-900/10 dark:ring-zinc-100/10"
                : "border-zinc-200 dark:border-zinc-800")}>
            <div className="flex items-baseline justify-between gap-3">
              <div className="font-medium">
                {c.title}
                {c.recommended && <span className="ml-2 text-xs uppercase tracking-wide text-emerald-700 dark:text-emerald-400">Recommended</span>}
              </div>
              <div className="text-sm text-zinc-500 dark:text-zinc-400">{c.price}</div>
            </div>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{c.body}</p>
          </button>
        ))}
      </div>
      {draft.providerId && (
        <div className="text-xs text-zinc-500 text-center">
          {PROVIDERS.find((p) => p.id === draft.providerId)?.label} selected.
        </div>
      )}
    </div>
  );
}
