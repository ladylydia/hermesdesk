# Onboarding flow (UX spec)

The non-pro promise is "two minutes from `.msi` to first reply".
Every screen below is calibrated for someone who has never heard
"API key", "model", or "endpoint".

## The five screens

```
1. Welcome      "Hi there. Two minutes."             1 button
2. Pick a brain Three big cards (Free / Best / Mine) 1 click
3. Get a pass   Open browser -> paste -> validate    1 paste + 1 click
4. Pick a vibe  Helpful / Friendly / Concise         1 click
5. Done         Open workspace + Start chatting      1 click
```

Total clicks for the happy path: **5 clicks + 1 paste**.

## Copy rules

- Never use the word "API". Use "access pass" or "long string".
- Never use "model" until the user is in chat. Use "brain".
- Never show a settings dump. If a value has a sensible default,
  hide it; expose under Settings only.
- Never make the user choose between technical providers up front.
  Default to OpenRouter (one key, many models, free tier exists).

## Visual rules

- One H1 per screen, max two paragraphs of body text.
- Primary action is one full-width button. No secondary buttons unless
  navigating back.
- Progress dots top-right show 5 segments; the current segment grows.
- Light + dark mode auto-follow the OS theme; never offer a theme
  picker in onboarding.

## Error wording

| Scenario                   | What we say                                                              |
|----------------------------|--------------------------------------------------------------------------|
| Empty paste box            | "Please paste your access pass."                                         |
| Wrong-shaped key           | "That doesn't look like a {provider} pass. They usually start with X."   |
| 401 / 403                  | "That pass didn't work. Double-check you copied the whole thing."        |
| Network down               | "Couldn't reach {provider}. Check your internet connection."             |
| Provider 5xx               | "{provider} answered 502. Try again in a moment."                        |
| Save succeeded             | (silent — advance immediately)                                           |

## Accessibility

- All buttons reachable by Tab in display order.
- Step heading is the first focusable element on each screen.
- Inputs have explicit `<label>` (in `GetAccessPass.tsx`).
- Color is never the only signal: the recommended card uses both color
  AND a "Recommended" badge.
- Minimum hit target 44px.

## Telemetry

Default-off. If the user opts in (post-launch toggle in Settings), we
record only:

- Step durations (no PII)
- Drop-off step (no PII)
- Provider chosen (no key, no model)

Sent to a single endpoint, batched, opt-out at any time.
