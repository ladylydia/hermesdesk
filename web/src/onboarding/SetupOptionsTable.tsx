import { useState, useEffect } from "react";
import { ShellModal } from "../components/ShellModal";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";
import { getDraftSnapshot, updateDraft, useDraft, type SectionSelection } from "../lib/store";
import { WeixinQrRouteCBlock, type WeixinEnvSnapshot } from "../components/WeixinQrRouteCBlock";
import { QqbotQrRouteBlock, type QqEnvSnapshot } from "../components/QqbotQrRouteBlock";
import { FeishuQrRouteBlock, type FeishuEnvSnapshot } from "../components/FeishuQrRouteBlock";
import { WeComSettingsBlock, type WeComEnvSnapshot } from "../components/WeComSettingsBlock";
import type {
  LocaleKey,
  Localized,
  OptionConfigField,
  PostPassSectionId,
  SetupCatalogOption,
} from "./setupCatalog/optionTypes";
import {
  getInitialSectionSelection,
  SECTION_SELECTION_MODE,
  type PostPassSelectionMode,
} from "./sectionSelection";

function pick(loc: Localized, locale: LocaleKey): string {
  return loc[locale] || loc.zh;
}

type Props = {
  section: string;
  items: SetupCatalogOption[];
  className?: string;
  modalSize?: "md" | "lg";
  /** Omitted = infer from `section` if tts/terminal/… else `none`. */
  selectionMode?: PostPassSelectionMode;
  /** `false` for rosters that are only informational. */
  showSkipRow?: boolean;
  /** When `section` is a post-pass id, use this until `wizardSelection[section]` is persisted. */
  defaultSelection?: import("../lib/store").SectionSelection;
};

function getSlice(
  wizard: Record<string, Record<string, Record<string, string>>> | undefined,
  section: string,
  optionId: string
): Record<string, string> {
  return { ...(wizard?.[section]?.[optionId] ?? {}) };
}

function inferMode(section: string, explicit?: PostPassSelectionMode): PostPassSelectionMode {
  if (explicit) return explicit;
  if (section in SECTION_SELECTION_MODE) {
    return SECTION_SELECTION_MODE[section as PostPassSectionId];
  }
  return "none";
}

/**
 * Roster: optional skip (keep defaults), then single- or multi-select, default/recommended badging, and per-row configure modals.
 */
export function SetupOptionsTable({
  section,
  items,
  className,
  modalSize = "md",
  selectionMode: selectionModeProp,
  showSkipRow = true,
  defaultSelection: defaultSelectionProp,
}: Props) {
  const { t, locale } = useI18n();
  const loc = (locale === "en" ? "en" : "zh") as LocaleKey;
  const draft = useDraft();
  const wizard = draft.wizardConfig ?? {};
  const selectionMode = inferMode(section, selectionModeProp);
  const defaultSelection: SectionSelection | undefined =
    defaultSelectionProp ??
    (section in SECTION_SELECTION_MODE ? getInitialSectionSelection(section as PostPassSectionId) : undefined);

  const [editing, setEditing] = useState<SetupCatalogOption | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [weixinEnv, setWeixinEnv] = useState<WeixinEnvSnapshot | null>(null);
  const [qqEnv, setQqEnv] = useState<QqEnvSnapshot | null>(null);
  const [feishuEnv, setFeishuEnv] = useState<FeishuEnvSnapshot | null>(null);
  const [wecomEnv, setWecomEnv] = useState<WeComEnvSnapshot | null>(null);

  useEffect(() => {
    if (items.some((r) => r.configUi === "weixin_route_c")) {
      invoke<WeixinEnvSnapshot>("cmd_weixin_env_status").then(setWeixinEnv).catch(() => setWeixinEnv(null));
    }
  }, [items]);
  useEffect(() => {
    if (items.some((r) => r.configUi === "qqbot_route_c")) {
      invoke<QqEnvSnapshot>("cmd_qq_env_status").then(setQqEnv).catch(() => setQqEnv(null));
    }
  }, [items]);
  useEffect(() => {
    if (items.some((r) => r.configUi === "feishu_route_c")) {
      invoke<FeishuEnvSnapshot>("cmd_feishu_env_status").then(setFeishuEnv).catch(() => setFeishuEnv(null));
    }
  }, [items]);

  useEffect(() => {
    if (items.some((r) => r.configUi === "wecom_route_c")) {
      invoke<WeComEnvSnapshot>("cmd_wecom_env_status").then(setWecomEnv).catch(() => setWecomEnv(null));
    }
  }, [items]);

  const selRaw = draft.wizardSelection?.[section];
  const sel: SectionSelection | undefined =
    selRaw ?? (selectionMode !== "none" && defaultSelection ? defaultSelection : undefined);
  const isSkip = sel?.kind === "skip";
  const singleId = sel?.kind === "single" ? sel.optionId : null;
  const multiSet = new Set(sel?.kind === "multi" ? sel.optionIds : []);

  function setSelection(next: SectionSelection) {
    const prev = draft.wizardSelection ?? {};
    updateDraft({ wizardSelection: { ...prev, [section]: next } });
  }

  function openConfig(row: SetupCatalogOption) {
    if (!rowAllowsConfig(row)) return;
    setForm(getSlice(wizard, section, row.id));
    setEditing(row);
  }

  function rowAllowsConfig(row: SetupCatalogOption): boolean {
    const hasModal = (row.configFields?.length ?? 0) > 0 || row.configUi === "weixin_route_c" || row.configUi === "qqbot_route_c" || row.configUi === "feishu_route_c" || row.configUi === "wecom_route_c";
    if (!hasModal) return false;
    if (isSkip) return false;
    if (selectionMode === "single") return singleId === row.id;
    if (selectionMode === "multi") return multiSet.has(row.id);
    return true;
  }

  function hasAnyValue(optionId: string): boolean {
    const slice = getSlice(wizard, section, optionId);
    return Object.values(slice).some((v) => v.trim().length > 0);
  }

  function isEnvConfigured(row: SetupCatalogOption): boolean {
    if (row.configUi === "weixin_route_c") return weixinEnv?.configured ?? false;
    if (row.configUi === "qqbot_route_c") return qqEnv?.configured ?? false;
    if (row.configUi === "feishu_route_c") return feishuEnv?.configured ?? false;
    if (row.configUi === "wecom_route_c") return wecomEnv?.configured ?? false;
    return false;
  }

  function persistForm(option: SetupCatalogOption, next: Record<string, string>) {
    const prevSec = wizard[section] ?? {};
    updateDraft({
      wizardConfig: {
        ...wizard,
        [section]: {
          ...prevSec,
          [option.id]: next,
        },
      },
    });
  }

  const fieldClass =
    "w-full rounded-[var(--radius-shell)] border border-zinc-300/90 bg-white/90 px-3 py-2.5 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90";

  const hasChoiceUi = selectionMode === "single" || selectionMode === "multi";
  const showSkip = showSkipRow && hasChoiceUi;

  return (
    <div className={cn("space-y-3", className)}>
      {showSkip ? (
        <div className="mb-3 space-y-1.5 rounded-[var(--radius-shell)] border border-amber-200/80 bg-amber-50/60 px-4 py-3 dark:border-amber-800/50 dark:bg-amber-950/30">
          <label className="flex cursor-pointer items-start gap-3 text-sm text-zinc-800 dark:text-zinc-200">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-zinc-400"
              checked={isSkip}
              onChange={(e) => {
                if (e.target.checked) {
                  setSelection({ kind: "skip" });
                } else {
                  if (selectionMode === "single") {
                    const firstD = items.find((x) => x.isDefault)?.id ?? items[0]?.id;
                    if (firstD) setSelection({ kind: "single", optionId: firstD });
                  } else {
                    setSelection({ kind: "multi", optionIds: [] });
                  }
                }
              }}
            />
            <span>
              <span className="font-medium">{t("setupOptions.skipKeepTitle")}</span>
              <span className="mt-1 block text-xs font-normal text-zinc-600 dark:text-zinc-400">
                {t("setupOptions.skipKeepBody")}
              </span>
            </span>
          </label>
        </div>
      ) : null}

      <div
        className={cn(
          "hd-glass-subtle overflow-x-auto rounded-[var(--radius-shell)] p-0",
          isSkip && hasChoiceUi && "pointer-events-none opacity-45"
        )}
      >
        <table className="w-full min-w-[min(100%,480px)] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-200/80 dark:border-zinc-700/80">
              {hasChoiceUi && !isSkip ? (
                <th className="w-10 px-2 py-2.5 text-center font-medium text-zinc-800 dark:text-zinc-200">
                  {t("setupOptions.colPick")}
                </th>
              ) : null}
              <th className="px-4 py-2.5 font-medium text-zinc-800 dark:text-zinc-200">{t("setupOptions.colOption")}</th>
              <th className="px-4 py-2.5 font-medium text-zinc-800 dark:text-zinc-200">
                {t("setupOptions.colDefault")}
              </th>
              <th className="w-0 whitespace-nowrap px-4 py-2.5 text-right font-medium text-zinc-800 dark:text-zinc-200">
                {t("setupOptions.colConfigure")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => {
              const hasFields =
                (row.configFields?.length ?? 0) > 0 || row.configUi === "weixin_route_c" || row.configUi === "qqbot_route_c" || row.configUi === "feishu_route_c" || row.configUi === "wecom_route_c";
              const envOk = isEnvConfigured(row);
              return (
                <tr
                  key={row.id}
                  className="border-b border-zinc-100/90 last:border-0 dark:border-zinc-800/80"
                >
                  {hasChoiceUi && !isSkip ? (
                    <td className="px-2 py-2.5 text-center align-top">
                      {selectionMode === "single" ? (
                        <input
                          type="radio"
                          name={`wizard-${section}`}
                          className="h-4 w-4"
                          checked={singleId === row.id}
                          onChange={() => setSelection({ kind: "single", optionId: row.id })}
                        />
                      ) : (
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded"
                          checked={multiSet.has(row.id)}
                          onChange={(e) => {
                            const next = new Set(sel?.kind === "multi" ? sel.optionIds : []);
                            if (e.target.checked) {
                              next.add(row.id);
                            } else {
                              next.delete(row.id);
                            }
                            setSelection({ kind: "multi", optionIds: [...next] });
                          }}
                        />
                      )}
                    </td>
                  ) : null}
                  <td className="px-4 py-2.5 align-top text-zinc-800 dark:text-zinc-200">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span>{pick(row.name, loc)}</span>
                      {row.isDefault ? (
                        <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[0.7rem] font-medium text-violet-800 dark:text-violet-200">
                          {t("setupOptions.recommendedBadge")}
                        </span>
                      ) : null}
                      {hasAnyValue(row.id) ? (
                        <span className="text-[0.7rem] text-sky-700 dark:text-sky-400">{t("setupOptions.hasPrefill")}</span>
                      ) : null}
                      {envOk ? (
                        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[0.7rem] font-medium text-emerald-800 dark:text-emerald-200">
                          {t("setupOptions.configured")}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 align-top text-zinc-600 dark:text-zinc-400">
                    {pick(row.defaultHint, loc)}
                  </td>
                  <td className="px-4 py-2.5 align-top text-right">
                    {hasFields ? (
                      <button
                        type="button"
                        disabled={!rowAllowsConfig(row)}
                        onClick={() => openConfig(row)}
                        className={cn(
                          "whitespace-nowrap",
                          rowAllowsConfig(row)
                            ? "text-sky-700 underline-offset-2 hover:underline dark:text-sky-400"
                            : "cursor-not-allowed text-zinc-300 dark:text-zinc-600"
                        )}
                      >
                        {t("setupOptions.configure")}
                      </button>
                    ) : (
                      <span className="text-zinc-300 dark:text-zinc-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ShellModal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing ? pick(editing.name, loc) : ""}
        size={modalSize}
      >
        {editing?.configUi === "weixin_route_c" ? (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">{t("settings.weixinLead")}</p>
            <WeixinQrRouteCBlock
              key={editing.id}
              onSuccess={({ accountId }) => {
                const d = getDraftSnapshot();
                const w = d.wizardConfig ?? {};
                const prevSec = w[section] ?? {};
                const slice = getSlice(w, section, editing.id);
                updateDraft({
                  wizardConfig: {
                    ...w,
                    [section]: {
                      ...prevSec,
                      [editing.id]: { ...slice, WEIXIN_ACCOUNT_ID: accountId },
                    },
                  },
                });
              }}
            />
            <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800/80">
              <button
                type="button"
                className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
                onClick={() => setEditing(null)}
              >
                {t("setupOptions.cancelConfig")}
              </button>
            </div>
          </div>
        ) : editing?.configUi === "qqbot_route_c" ? (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">{t("settings.qqLead")}</p>
            <QqbotQrRouteBlock
              key={editing.id}
              onSuccess={({ appId }) => {
                const d = getDraftSnapshot();
                const w = d.wizardConfig ?? {};
                const prevSec = w[section] ?? {};
                const slice = getSlice(w, section, editing.id);
                updateDraft({
                  wizardConfig: {
                    ...w,
                    [section]: {
                      ...prevSec,
                      [editing.id]: { ...slice, QQ_APP_ID: appId },
                    },
                  },
                });
              }}
            />
            <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800/80">
              <button
                type="button"
                className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
                onClick={() => setEditing(null)}
              >
                {t("setupOptions.cancelConfig")}
              </button>
            </div>
          </div>
        ) : editing?.configUi === "feishu_route_c" ? (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">{t("settings.feishuLead")}</p>
            <FeishuQrRouteBlock
              key={editing.id}
              onSuccess={({ appId }) => {
                const d = getDraftSnapshot();
                const w = d.wizardConfig ?? {};
                const prevSec = w[section] ?? {};
                const slice = getSlice(w, section, editing.id);
                updateDraft({
                  wizardConfig: {
                    ...w,
                    [section]: {
                      ...prevSec,
                      [editing.id]: { ...slice, FEISHU_APP_ID: appId },
                    },
                  },
                });
              }}
            />
            <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800/80">
              <button
                type="button"
                className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
                onClick={() => setEditing(null)}
              >
                {t("setupOptions.cancelConfig")}
              </button>
            </div>
          </div>
        ) : editing?.configUi === "wecom_route_c" ? (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">{t("settings.wecomLead")}</p>
            <WeComSettingsBlock key={editing.id} />
            <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800/80">
              <button
                type="button"
                className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
                onClick={() => setEditing(null)}
              >
                {t("setupOptions.cancelConfig")}
              </button>
            </div>
          </div>
        ) : editing?.configFields?.length ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (editing) persistForm(editing, form);
              setEditing(null);
            }}
          >
            <p className="text-xs text-zinc-500 dark:text-zinc-500">{t("setupOptions.configLead")}</p>
            {editing.configFields.map((fld: OptionConfigField) => (
              <div key={fld.id} className="space-y-1.5">
                <label className="flex flex-wrap items-baseline gap-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  <span>{pick(fld.label, loc)}</span>
                  {fld.optional ? (
                    <span className="text-xs font-normal text-zinc-500">({t("setupOptions.optional")})</span>
                  ) : null}
                </label>
                <p className="text-[0.7rem] font-mono text-zinc-500">{fld.id}</p>
                <input
                  className={fieldClass}
                  type={fld.kind === "password" ? "password" : fld.kind === "url" ? "url" : "text"}
                  name={fld.id}
                  value={form[fld.id] ?? ""}
                  placeholder={pick(fld.placeholder, loc)}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => setForm((prev) => ({ ...prev, [fld.id]: e.target.value }))}
                />
              </div>
            ))}
            <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-200/80 pt-4 dark:border-zinc-800/80">
              <button
                type="button"
                className="rounded-lg border border-zinc-300/90 px-4 py-2 text-sm dark:border-zinc-600"
                onClick={() => setEditing(null)}
              >
                {t("setupOptions.cancelConfig")}
              </button>
              <button
                type="submit"
                className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900"
              >
                {t("setupOptions.saveConfig")}
              </button>
            </div>
          </form>
        ) : null}
      </ShellModal>
    </div>
  );
}
