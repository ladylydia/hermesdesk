import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { SlidersHorizontal } from "lucide-react";
import { Section } from "../components/ui/Section";
import { useI18n } from "../lib/i18n";
import {
  allEnvKeysForPlatform,
  type EnvFieldDef,
  registryForPlatform,
} from "../lib/gatewayPlatformSettingsRegistry";

type Props = { platform: string };

type EnvKv = { key: string; value: string };

export function GatewayChannelSettingsPanel({ platform }: Props) {
  const { t } = useI18n();
  const entry = useMemo(() => registryForPlatform(platform), [platform]);
  const keys = useMemo(() => allEnvKeysForPlatform(platform), [platform]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!entry || keys.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const got = await invoke<Record<string, string>>("cmd_gateway_host_env_get", {
        keys,
      });
      const next: Record<string, string> = {};
      for (const k of keys) {
        const v = got[k];
        if (v !== undefined && v !== "") next[k] = v;
        else next[k] = "";
      }
      setValues(next);
    } catch (e) {
      setError(t("settings.channelEnv.loadErr", { msg: String(e) }));
    } finally {
      setLoading(false);
    }
  }, [entry, keys, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateField = useCallback((envKey: string, v: string) => {
    setValues((prev) => ({ ...prev, [envKey]: v }));
  }, []);

  const save = useCallback(async () => {
    if (!entry) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    const upserts: EnvKv[] = [];
    const removeKeys: string[] = [];

    for (const sec of entry.sections) {
      for (const f of sec.fields) {
        if (f.advanced && !showAdvanced) continue;
        const raw = (values[f.envKey] ?? "").trim();
        if (f.type === "bool") {
          if (raw === "") removeKeys.push(f.envKey);
          else upserts.push({ key: f.envKey, value: raw.toLowerCase() });
        } else if (f.type === "enum") {
          if (raw === "") removeKeys.push(f.envKey);
          else upserts.push({ key: f.envKey, value: raw.toLowerCase() });
        } else {
          if (raw === "") removeKeys.push(f.envKey);
          else upserts.push({ key: f.envKey, value: raw });
        }
      }
    }

    try {
      await invoke("cmd_gateway_host_env_patch", { upserts, removeKeys });
      setMessage(t("settings.channelEnv.saved"));
      await load();
    } catch (e) {
      setError(t("settings.channelEnv.saveErr", { msg: String(e) }));
    } finally {
      setSaving(false);
    }
  }, [entry, showAdvanced, values, load, t]);

  if (!entry) return null;

  return (
    <Section icon={SlidersHorizontal} title={t("settings.channelEnv.panelTitle")}>
      <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 mb-3">
        {t("settings.channelEnv.panelLead")}
      </p>
      <p className="text-[0.7rem] text-zinc-500 dark:text-zinc-500 mb-3">
        {t("settings.channelEnv.clearOptionalHint")}
      </p>

      <button
        type="button"
        className="text-xs text-emerald-700 dark:text-emerald-400 underline-offset-2 hover:underline mb-3"
        onClick={() => setShowAdvanced((v) => !v)}
      >
        {showAdvanced ? t("settings.channelEnv.hideAdvanced") : t("settings.channelEnv.showAdvanced")}
      </button>

      {loading ? (
        <p className="text-sm text-zinc-500">…</p>
      ) : (
        <div className="space-y-6">
          {entry.sections.map((sec) => (
            <div key={sec.id} className="space-y-3 border-t border-zinc-200/80 dark:border-zinc-700/80 pt-4 first:border-t-0 first:pt-0">
              <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                {t(sec.titleKey)}
              </h3>
              {sec.footnoteKey ? (
                <p className="text-[0.7rem] text-zinc-500">{t(sec.footnoteKey)}</p>
              ) : null}
              {sec.fields.map((f) =>
                !f.advanced || showAdvanced ? (
                  <FieldRow
                    key={f.envKey}
                    field={f}
                    value={values[f.envKey] ?? ""}
                    onChange={(v) => updateField(f.envKey, v)}
                    t={t}
                  />
                ) : null,
              )}
            </div>
          ))}
        </div>
      )}

      {error ? <p className="text-xs text-red-600 dark:text-red-400 mt-3">{error}</p> : null}
      {message ? <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-3">{message}</p> : null}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <button
          type="button"
          disabled={saving || loading}
          className="rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          onClick={() => void save()}
        >
          {saving ? "…" : t("settings.channelEnv.save")}
        </button>
        <span className="text-[0.7rem] text-zinc-500">{t("settings.channelEnv.restartHint")}</span>
      </div>
    </Section>
  );
}

function FieldRow({
  field,
  value,
  onChange,
  t,
}: {
  field: EnvFieldDef;
  value: string;
  onChange: (v: string) => void;
  t: (path: string, params?: Record<string, string | number>) => string;
}) {
  const id = `gw-${field.envKey}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-zinc-700 dark:text-zinc-300">
        {t(field.labelKey)}
      </label>
      {field.descriptionKey ? (
        <p className="text-[0.65rem] text-zinc-500 leading-snug">{t(field.descriptionKey)}</p>
      ) : null}
      {field.type === "enum" ? (
        <select
          id={id}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">{t("settings.channelEnv.enumUnset")}</option>
          {(field.enumValues ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : field.type === "bool" ? (
        <select
          id={id}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">{t("settings.channelEnv.enumUnset")}</option>
          <option value="true">{t("settings.channelEnv.boolTrue")}</option>
          <option value="false">{t("settings.channelEnv.boolFalse")}</option>
        </select>
      ) : (
        <input
          id={id}
          type={field.type === "secret" ? "password" : "text"}
          autoComplete="off"
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm font-mono dark:border-zinc-600 dark:bg-zinc-900"
          value={value}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
