import type { PostPassSectionId } from "./setupCatalog/optionTypes";
import type { SetupCatalogOption } from "./setupCatalog/optionTypes";
import { CATALOG_BY_SECTION } from "./setupCatalog/optionData";
import type { SectionSelection } from "../lib/store";

export type PostPassSelectionMode = "none" | "single" | "multi";

/** Per post-pass section: how the roster behaves in the UI. */
export const SECTION_SELECTION_MODE: Record<PostPassSectionId, PostPassSelectionMode> = {
  tts: "single",
  terminal: "single",
  gateway: "multi",
  tools: "multi",
  agent: "single",
};

export function findRecommendedSingleId(items: SetupCatalogOption[]): string | null {
  const d = items.find((x) => x.isDefault);
  return d?.id ?? items[0]?.id ?? null;
}

export function findRecommendedMultiIds(items: SetupCatalogOption[]): string[] {
  return items.filter((x) => x.isDefault).map((x) => x.id);
}

/** Default selection on first open (enables “下一步” without extra clicks; user can change). */
export function getInitialSectionSelection(
  section: PostPassSectionId
): SectionSelection {
  if (section === "gateway") {
    return { kind: "skip" };
  }
  const items = CATALOG_BY_SECTION[section];
  if (section === "tts" || section === "terminal" || section === "agent") {
    const id = findRecommendedSingleId(items);
    if (id) return { kind: "single", optionId: id };
  }
  if (section === "tools") {
    const ids = findRecommendedMultiIds(items);
    if (ids.length) return { kind: "multi", optionIds: [...ids] };
  }
  return { kind: "skip" };
}

export function selectionSatisfied(sel: SectionSelection | undefined, mode: PostPassSelectionMode): boolean {
  if (mode === "none") return true;
  if (!sel) return false;
  if (sel.kind === "skip") return true;
  if (sel.kind === "single") return Boolean(sel.optionId?.trim());
  if (sel.kind === "multi") return (sel.optionIds?.length ?? 0) > 0;
  return false;
}

