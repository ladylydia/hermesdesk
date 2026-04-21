import { useNavigate } from "react-router-dom";

export function Welcome() {
  const nav = useNavigate();
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Hi there.</h1>
        <p className="mt-3 text-lg text-zinc-600 dark:text-zinc-400 leading-relaxed">
          HermesDesk is a friendly AI helper that lives on your PC.
          Let's get you set up — it takes about two minutes.
        </p>
      </div>

      <ul className="space-y-3 text-zinc-700 dark:text-zinc-300">
        <li className="flex gap-3"><Bullet /> No accounts to make with us.</li>
        <li className="flex gap-3"><Bullet /> No subscription, no monthly fee from us.</li>
        <li className="flex gap-3"><Bullet /> Stays on your PC. Files never leave a folder you choose.</li>
      </ul>

      <div className="pt-4">
        <button
          onClick={() => nav("/onboarding/brain")}
          className="w-full rounded-2xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-6 py-4 text-lg font-medium hover:opacity-90 transition"
        >
          Let's get started
        </button>
      </div>
    </div>
  );
}

function Bullet() {
  return (
    <span aria-hidden className="mt-1 inline-block h-2 w-2 rounded-full bg-zinc-400 dark:bg-zinc-600" />
  );
}
