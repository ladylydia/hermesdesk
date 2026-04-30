import type { SetupMode } from "../lib/store";

/**
 * Shell wizard step ids (same order as post-model sections in
 * `hermes/hermes_cli/setup.py` SETUP_SECTIONS: tts, terminal, gateway, tools, agent),
 * with preamble: mode, welcome, brain, pass.
 */
export const SHELL_WIZARD_STEPS = [
  "mode",
  "welcome",
  "brain",
  "pass",
  "tts",
  "terminal",
  "gateway",
  "tools",
  "agent",
] as const;

export type ShellWizardStepId = (typeof SHELL_WIZARD_STEPS)[number];

const QUICK_STEPS: readonly ShellWizardStepId[] = [
  "mode",
  "welcome",
  "brain",
  "pass",
  "gateway",
] as const;

const FULL_STEPS: readonly ShellWizardStepId[] = SHELL_WIZARD_STEPS;

const LEGACY_INCOMPLETE: readonly ShellWizardStepId[] = [
  "mode",
  "welcome",
  "brain",
  "pass",
] as const;

export function getStepsForMode(setupMode: SetupMode | null): readonly ShellWizardStepId[] {
  if (setupMode === "quick") return QUICK_STEPS;
  if (setupMode === "full") return FULL_STEPS;
  return LEGACY_INCOMPLETE;
}

export function isStepInMode(step: ShellWizardStepId, setupMode: SetupMode | null): boolean {
  return getStepsForMode(setupMode).includes(step);
}

export function stepToPath(id: ShellWizardStepId): string {
  return `/onboarding/${id}`;
}

/**
 * After saving API credentials on `pass`, match CLI: full → tts; quick → gateway (optional) then done.
 */
export function getNextPathAfterPass(setupMode: SetupMode): string {
  return setupMode === "full" ? stepToPath("tts") : stepToPath("gateway");
}

export function getIndexInFlow(step: ShellWizardStepId, setupMode: SetupMode | null): number {
  const list = getStepsForMode(setupMode);
  const i = list.indexOf(step);
  return i >= 0 ? i : 0;
}

export function getBackPath(current: ShellWizardStepId, setupMode: SetupMode | null): string | null {
  if (current === "mode") return "/chat";
  const list = getStepsForMode(setupMode);
  const i = list.indexOf(current);
  if (i <= 0) return null;
  return stepToPath(list[i - 1]!);
}

export function getNextPath(
  current: ShellWizardStepId,
  setupMode: SetupMode | null
): string | "complete" {
  if (!setupMode) return "complete";
  const list = getStepsForMode(setupMode);
  const i = list.indexOf(current);
  if (i < 0 || i >= list.length - 1) return "complete";
  return stepToPath(list[i + 1]!);
}

export function isLastStep(current: ShellWizardStepId, setupMode: SetupMode | null): boolean {
  if (!setupMode) return false;
  const list = getStepsForMode(setupMode);
  return list.length > 0 && list[list.length - 1] === current;
}

export function slugFromPathname(pathname: string): ShellWizardStepId {
  const seg = (pathname.split("/").pop() || "mode") as string;
  if ((SHELL_WIZARD_STEPS as readonly string[]).includes(seg)) {
    return seg as ShellWizardStepId;
  }
  return "mode";
}

/**
 * If URL points at a post-pass section the current mode does not use, send user to a valid step.
 */
export function getRedirectForInvalidUrlStep(
  pathStep: ShellWizardStepId,
  setupMode: SetupMode | null
): string | null {
  if (!setupMode) return null;
  if (isStepInMode(pathStep, setupMode)) return null;
  if (setupMode === "quick" && (pathStep === "tts" || pathStep === "terminal" || pathStep === "tools" || pathStep === "agent")) {
    return stepToPath("gateway");
  }
  return null;
}
