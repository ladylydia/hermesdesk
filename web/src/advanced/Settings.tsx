import { useCallback, useEffect, useRef, useState } from "react";

type GatewayStatusResponse = {
  running: boolean;
  eligible: boolean;
  embeddedGatewayStartupSurvival?: boolean;
  diskGatewayState?: string | null;
  diskExitReason?: string | null;
};

type ProxyStatusResponse = {
  system: { url: string | null; enabled: boolean };
  settings: { useSystem: boolean; customUrl: string | null };
  effectiveUrl: string | null;
};
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { ask } from "@tauri-apps/plugin-dialog";
import {
  Activity,
  Bot,
  Building2,
  FolderOpen,
  Globe,
  KeyRound,
  type LucideIcon,
  LayoutDashboard,
  MessageCircle,
  QrCode,
  Send,
  Shield,
  Store,
  Type,
} from "lucide-react";
import { AppScaffold } from "../components/AppScaffold";
import { FeishuQrRouteBlock } from "../components/FeishuQrRouteBlock";
import { PairingSettingsBlock } from "../components/PairingSettingsBlock";
import { TelegramSettingsBlock } from "../components/TelegramSettingsBlock";
import { QqbotQrRouteBlock } from "../components/QqbotQrRouteBlock";
import { WeixinQrRouteCBlock } from "../components/WeixinQrRouteCBlock";
import { getLocale } from "../lib/i18n-core";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/cn";
import { cmdGetHermesPort } from "../chat/chat-api";
import { type FontSizeOption, getStoredFontSize, setFontSize } from "../lib/ui-prefs";
import { clearAllowChatWithoutApi } from "../lib/apiKeyGate";

interface Status {
  workspace: string;
  hasSecret: boolean;
  pythonRunning: boolean;
}

export function Settings() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [status, setStatus] = useState<Status | null>(null);
  const [powerUser, setPowerUser] = useState(false);
  const [showRecipeMarket, setShowRecipeMarket] = useState(false);
  const [fontSize, setFontSizeState] = useState<FontSizeOption>(() => getStoredFontSize());
  const [autoStartGateway, setAutoStartGateway] = useState(true);
  const [gatewayRunning, setGatewayRunning] = useState(false);
  const [gatewayEligible, setGatewayEligible] = useState(false);
  const [gatewayDiskState, setGatewayDiskState] = useState<string | null>(null);
  const [gatewayDiskExit, setGatewayDiskExit] = useState<string | null>(null);
  const [gatewayEmbedSurvival, setGatewayEmbedSurvival] = useState(true);
  const [gatewayStartError, setGatewayStartError] = useState<string | null>(null);
  const [gatewayStarting, setGatewayStarting] = useState(false);
  const gatewayStartInFlight = useRef(false);

  // Proxy settings
  const [proxyDetected, setProxyDetected] = useState<string | null>(null);
  const [proxyUseSystem, setProxyUseSystem] = useState(false);
  const [proxyCustom, setProxyCustom] = useState("");
  const [proxySaving, setProxySaving] = useState(false);

  const refreshGatewayStatus = useCallback(async () => {
    try {
      const gs = await invoke<GatewayStatusResponse>("cmd_gateway_status");
      setGatewayRunning(!!gs.running);
      setGatewayEligible(!!gs.eligible);
      setGatewayDiskState(gs.diskGatewayState ?? null);
      setGatewayDiskExit(gs.diskExitReason ?? null);
      setGatewayEmbedSurvival(gs.embeddedGatewayStartupSurvival === true);
    } catch {
      /* optional */
    }
  }, []);

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
      } catch {
        /* optional */
      }
      try {
        const m = await invoke<boolean>("cmd_get_show_recipe_market");
        setShowRecipeMarket(!!m);
      } catch {
        /* optional */
      }
      try {
        const ag = await invoke<boolean>("cmd_get_auto_start_gateway");
        setAutoStartGateway(!!ag);
      } catch {
        /* optional */
      }
      try {
        const gs = await invoke<GatewayStatusResponse>("cmd_gateway_status");
        setGatewayRunning(!!gs.running);
        setGatewayEligible(!!gs.eligible);
        setGatewayDiskState(gs.diskGatewayState ?? null);
        setGatewayDiskExit(gs.diskExitReason ?? null);
        setGatewayEmbedSurvival(gs.embeddedGatewayStartupSurvival === true);
      } catch {
        /* optional */
      }
      try {
        const ps = await invoke<ProxyStatusResponse>("cmd_proxy_status");
        setProxyDetected(ps.system.url);
        setProxyUseSystem(!!ps.settings.useSystem);
        setProxyCustom(ps.settings.customUrl ?? "");
      } catch {
        /* optional */
      }
    })().catch(console.error);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshGatewayStatus();
    }, 4000);
    return () => clearInterval(id);
  }, [refreshGatewayStatus]);

  async function toggleAutoStartGateway(next: boolean) {
    try {
      await invoke("cmd_set_auto_start_gateway", { enabled: next });
      setAutoStartGateway(next);
    } catch (e) {
      console.error(e);
    }
  }

  const startGateway = useCallback(async () => {
    if (gatewayStartInFlight.current) return;
    gatewayStartInFlight.current = true;
    setGatewayStarting(true);
    setGatewayStartError(null);
    try {
      await invoke("cmd_gateway_start");
      setGatewayStartError(null);
      await refreshGatewayStatus();
    } catch (e) {
      console.error(e);
      const msg = e instanceof Error ? e.message : String(e);
      setGatewayStartError(msg);
      await refreshGatewayStatus();
    } finally {
      gatewayStartInFlight.current = false;
      setGatewayStarting(false);
    }
  }, [refreshGatewayStatus]);

  const stopGateway = useCallback(async () => {
    if (gatewayStartInFlight.current) return;
    try {
      await invoke("cmd_gateway_stop");
      await refreshGatewayStatus();
    } catch (e) {
      console.error(e);
    }
  }, [refreshGatewayStatus]);

  const saveProxy = useCallback(async () => {
    setProxySaving(true);
    try {
      const custom = proxyCustom.trim();
      await invoke("cmd_proxy_save", {
        useSystem: proxyUseSystem,
        customUrl: custom || null,
      });
    } catch (e) {
      console.error(e);
    } finally {
      setProxySaving(false);
    }
  }, [proxyUseSystem, proxyCustom]);

  const openHermesConsole = useCallback(async (subPath?: string | null) => {
    const loc = getLocale();
    const path =
      subPath && subPath.trim() && subPath.trim() !== "/"
        ? subPath.trim().startsWith("/")
          ? subPath.trim()
          : `/${subPath.trim()}`
        : null;
    try {
      await invoke("cmd_open_hermes_dashboard", { shellLocale: loc, path });
    } catch (e) {
      console.error(e);
      try {
        const port = await cmdGetHermesPort();
        if (port) {
          const u = new URL(`http://127.0.0.1:${port}/`);
          if (path) {
            u.pathname = path;
          }
          if (loc === "en" || loc === "zh") {
            u.searchParams.set("hermesdesk_lang", loc);
          }
          window.open(u.toString(), "_blank", "noopener,noreferrer");
        }
      } catch {
        /* ignore */
      }
    }
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
      const ok = await ask(t("settings.powerAsk"), {
        title: t("settings.powerAskTitle"),
        kind: "warning",
      });
      if (!ok) return;
    }
    try {
      await invoke("cmd_set_power_user", { enabled: next });
      setPowerUser(next);
    } catch (e) {
      console.error(e);
    }
  }

  async function clearKey() {
    const ok = await ask(t("settings.signOutAsk"), {
      title: t("settings.signOutTitle"),
      kind: "warning",
    });
    if (!ok) return;
    await invoke("cmd_clear_secret");
    clearAllowChatWithoutApi();
    setStatus((s) => (s ? { ...s, hasSecret: false } : s));
  }

  const hermesPaths = ["/", "/config", "/env", "/sessions"] as const;

  return (
    <AppScaffold className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl space-y-6 px-[var(--hd-page-pad-x)] py-10 sm:py-12">
        <div>
          <button
            type="button"
            onClick={() => nav("/chat")}
            className="mb-3 text-sm text-zinc-500 underline-offset-4 transition hover:text-zinc-800 active:scale-[0.99] dark:text-zinc-500 dark:hover:text-zinc-200"
          >
            {t("settings.back")}
          </button>
          <h1 className="hd-page-title">{t("settings.title")}</h1>
          <p className="mt-2 max-w-xl text-sm leading-[1.57] text-zinc-500 dark:text-zinc-400">
            {t("settings.pageLead")}
          </p>
        </div>

        <aside
          className="hd-glass-subtle p-5 sm:p-5"
          aria-label={t("settings.hermesTitle")}
        >
          <div className="flex gap-3 sm:gap-4">
            <div
              className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800/80"
              aria-hidden
            >
              <Globe className="h-5 w-5 text-sky-600 dark:text-sky-400" strokeWidth={2} />
            </div>
            <div className="min-w-0 space-y-3">
              <h2 className="text-base font-semibold leading-6 text-zinc-900 dark:text-zinc-100">
                {t("settings.hermesTitle")}
              </h2>
              <div>
                <button
                  type="button"
                  onClick={() => void openHermesConsole(null)}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 px-3.5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:opacity-95 active:scale-[0.99] sm:w-auto dark:bg-sky-500"
                >
                  <LayoutDashboard className="h-4 w-4 shrink-0 opacity-95" aria-hidden />
                  {t("settings.openConsole")}
                </button>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">
                  {t("settings.openConsoleHint")}
                </p>
              </div>
              <p className="text-sm leading-[1.57] text-zinc-600 dark:text-zinc-300">
                {t("settings.hermesDesc")}
              </p>
              <ul className="list-inside list-disc space-y-1.5 pl-0.5 text-sm leading-[1.57] text-zinc-600 dark:text-zinc-300">
                <li>{t("settings.hermesBullet1")}</li>
                <li>{t("settings.hermesBullet2")}</li>
                <li>{t("settings.hermesBullet3")}</li>
              </ul>
              <div className="space-y-2 border-t border-zinc-200/80 pt-3 dark:border-zinc-700/80">
                <p className="text-xs font-medium text-zinc-500 dark:text-zinc-500">
                  {t("settings.hermesPathLabel")}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {hermesPaths.map((p) => (
                    <code key={p} className="hd-inline-code">
                      {p}
                    </code>
                  ))}
                </div>
                <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">
                  {t("settings.hermesPathNote")}
                </p>
              </div>
            </div>
          </div>
        </aside>

        <Section icon={Globe} title={t("settings.proxyTitle")} desc={t("settings.proxyLead")}>
          <div className="w-full min-w-0 space-y-3">
            <div className="text-sm text-zinc-600 dark:text-zinc-400">
              {proxyDetected
                ? t("settings.proxyDetected", { url: proxyDetected })
                : t("settings.proxyNone")}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-zinc-700 dark:text-zinc-200">{t("settings.proxyUseSystem")}</span>
              <Toggle value={proxyUseSystem} onChange={(v) => setProxyUseSystem(v)} />
            </div>
            <div className="space-y-1">
              <span className="text-sm text-zinc-700 dark:text-zinc-200">{t("settings.proxyCustom")}</span>
              <input
                className="w-full rounded-lg border border-zinc-300/90 bg-white/90 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900/90"
                type="text"
                value={proxyCustom}
                placeholder="http://127.0.0.1:7890"
                onChange={(e) => setProxyCustom(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" onClick={() => void saveProxy()} disabled={proxySaving}>
                {proxySaving ? t("settings.proxySaving") : t("settings.proxySave")}
              </Button>
              <Button
                type="button"
                onClick={() => {
                  setProxyUseSystem(false);
                  setProxyCustom("");
                  void saveProxy();
                }}
              >
                {t("settings.proxyClear")}
              </Button>
            </div>
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">
              {t("settings.proxyRestartHint")}
            </p>
          </div>
        </Section>

        <Section icon={MessageCircle} title={t("settings.gatewayTitle")} desc={t("settings.gatewayLead")}>
          <div className="w-full min-w-0 space-y-3">
            <div>
              <Button type="button" onClick={() => void openHermesConsole("/env")}>
                {t("settings.gatewayOpenKeys")}
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-zinc-700 dark:text-zinc-200">{t("settings.gatewayAuto")}</span>
              <Toggle value={autoStartGateway} onChange={toggleAutoStartGateway} />
            </div>
            {!gatewayEligible ? (
              <p className="text-xs leading-relaxed text-amber-700/90 dark:text-amber-400/90">
                {t("settings.gatewayNotEligible")}
              </p>
            ) : null}
            {gatewayEligible && !gatewayEmbedSurvival ? (
              <p className="text-xs leading-relaxed text-amber-800/95 dark:text-amber-300/95">
                {t("settings.gatewayEmbedStale")}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                onClick={() => void startGateway()}
                disabled={!gatewayEligible || gatewayStarting}
              >
                {gatewayStarting ? t("settings.gatewayStarting") : t("settings.gatewayStart")}
              </Button>
              <Button type="button" onClick={() => void stopGateway()} disabled={gatewayStarting}>
                {t("settings.gatewayStop")}
              </Button>
              <span className="text-sm text-zinc-600 dark:text-zinc-300">
                {gatewayStarting
                  ? t("settings.gatewayStatusChecking")
                  : gatewayRunning
                    ? t("settings.gatewayStatusRunning")
                    : t("settings.gatewayStatusStopped")}
              </span>
            </div>
            {gatewayEligible && gatewayStarting ? (
              <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                {t("settings.gatewayStartingHint")}
              </p>
            ) : null}
            {gatewayStartError ? (
              <p className="text-xs leading-relaxed text-red-700 dark:text-red-400">
                {t("settings.gatewayStartFailed", { msg: gatewayStartError })}
              </p>
            ) : null}
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">
              {t("settings.gatewayAutoRefresh")}
            </p>
            {gatewayEligible ? (
              <>
                <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {t("settings.gatewayTroubleshootTelegram")}
                </p>
                <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {t("settings.gatewayTroubleshootFeishu")}
                </p>
                <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {t("settings.gatewayTroubleshootQq")}
                </p>
                <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {t("settings.gatewayTroubleshootWeixin")}
                </p>
              </>
            ) : null}
            {gatewayDiskState || gatewayDiskExit ? (
              <div className="rounded-md border border-zinc-200/90 bg-zinc-50/80 px-3 py-2 text-xs dark:border-zinc-700 dark:bg-zinc-900/40">
                <p className="font-medium text-zinc-700 dark:text-zinc-200">{t("settings.gatewayDiskRecord")}</p>
                {gatewayDiskState ? (
                  <p className="mt-1 font-mono text-[0.7rem] text-zinc-600 dark:text-zinc-300">
                    {t("settings.gatewayStateLine", { state: gatewayDiskState })}
                  </p>
                ) : null}
                {gatewayDiskExit ? (
                  <p className="mt-1 font-mono text-[0.7rem] text-zinc-600 dark:text-zinc-300">
                    {t("settings.gatewayExitLine", { detail: gatewayDiskExit })}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </Section>

        <Section icon={Send} title={t("settings.telegramTitle")} desc={t("settings.telegramLead")}>
          <TelegramSettingsBlock />
          <div className="mt-4 border-t border-zinc-200/80 pt-3 dark:border-zinc-700/80">
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-500 mb-2">
              {t("settings.telegramPairingTitle")}
            </p>
            <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-500 mb-3">
              {t("settings.telegramPairingLead")}
            </p>
            <PairingSettingsBlock platform="telegram" />
          </div>
        </Section>

        <Section icon={Building2} title={t("settings.feishuTitle")} desc={t("settings.feishuLead")}>
          <FeishuQrRouteBlock
            onHermesRunningChange={(running) =>
              setStatus((st) => (st ? { ...st, pythonRunning: running } : st))
            }
          />
        </Section>

        <Section icon={Bot} title={t("settings.qqTitle")} desc={t("settings.qqLead")}>
          <QqbotQrRouteBlock
            onHermesRunningChange={(running) =>
              setStatus((st) => (st ? { ...st, pythonRunning: running } : st))
            }
          />
        </Section>

        <Section icon={QrCode} title={t("settings.weixinTitle")} desc={t("settings.weixinLead")}>
          <WeixinQrRouteCBlock
            onHermesRunningChange={(running) =>
              setStatus((st) => (st ? { ...st, pythonRunning: running } : st))
            }
          />
        </Section>

        <Section icon={Type} title={t("settings.fontTitle")} desc={t("settings.fontDesc")}>
          <div className="inline-flex w-full max-w-md rounded-lg border border-zinc-200 bg-zinc-100/50 p-0.5 dark:border-zinc-700 dark:bg-zinc-800/50 sm:w-auto">
            {(
              [
                { id: "small" as const, label: t("settings.fontSmall") },
                { id: "medium" as const, label: t("settings.fontMedium") },
                { id: "large" as const, label: t("settings.fontLarge") },
              ] as const
            ).map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setFontSize(id);
                  setFontSizeState(id);
                }}
                className={cn(
                  "min-h-[2.25rem] flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition sm:flex-initial",
                  "active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
                  fontSize === id
                    ? "hd-btn-segment-active shadow-sm"
                    : "hd-btn-segment-idle"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </Section>

        <Section
          icon={FolderOpen}
          title={t("settings.secWorkspace")}
          desc={powerUser ? t("settings.secWorkspaceDescPower") : t("settings.secWorkspaceDescSimple")}
        >
          {powerUser ? (
            <>
              <p className="w-full break-all font-mono text-xs leading-relaxed text-zinc-800 dark:text-zinc-200">
                <span className="inline-block max-w-full rounded-md bg-zinc-100 px-2 py-1.5 dark:bg-zinc-800/90">
                  {status?.workspace ?? "…"}
                </span>
              </p>
              <Button onClick={() => invoke("cmd_open_workspace")}>{t("settings.openFolder")}</Button>
            </>
          ) : null}
        </Section>

        <Section
          icon={KeyRound}
          title={t("settings.secPass")}
          desc={status?.hasSecret ? t("settings.passOn") : t("settings.passOff")}
        >
          <Button onClick={clearKey} disabled={!status?.hasSecret}>
            {t("settings.signOut")}
          </Button>
        </Section>

        <Section icon={Shield} title={t("settings.powerTitle")} desc={t("settings.powerDesc")}>
          <Toggle value={powerUser} onChange={togglePowerUser} />
        </Section>

        <Section icon={Store} title={t("settings.recipeTitle")} desc={t("settings.recipeDesc")}>
          <Toggle value={showRecipeMarket} onChange={toggleRecipeMarket} />
        </Section>

        <Section icon={Activity} title={t("settings.status")}>
          <ul className="w-full space-y-2 text-sm leading-[1.57] text-zinc-600 dark:text-zinc-300">
            <li>
              {t("settings.pyRunning")}: {status?.pythonRunning ? t("settings.yes") : t("settings.no")}
            </li>
            <li>
              {t("settings.hasPass")}: {status?.hasSecret ? t("settings.yes") : t("settings.no")}
            </li>
            <li>
              {t("settings.gatewayShort")}: {gatewayRunning ? t("settings.yes") : t("settings.no")}
            </li>
          </ul>
        </Section>
      </div>
    </AppScaffold>
  );
}

function Section({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "hd-glass p-5 sm:p-5",
        Icon ? "space-y-0" : "space-y-3"
      )}
    >
      {Icon ? (
        <div className="flex gap-3 sm:gap-4">
          <div
            className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-800/80"
            aria-hidden
          >
            <Icon className="h-5 w-5 text-sky-600 dark:text-sky-400" strokeWidth={2} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-6 text-zinc-900 dark:text-zinc-100">
              {title}
            </h2>
            {desc ? (
              <p className="mt-2 text-sm leading-[1.57] text-zinc-600 dark:text-zinc-300">{desc}</p>
            ) : null}
            <div className="mt-3 flex min-w-0 flex-wrap items-center gap-3">{children}</div>
          </div>
        </div>
      ) : (
        <>
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
          {desc ? (
            <p className="mt-2 text-sm leading-[1.57] text-zinc-600 dark:text-zinc-300">{desc}</p>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-center gap-3">{children}</div>
        </>
      )}
    </section>
  );
}

function Button({ className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={cn(
        "rounded-lg border border-zinc-300/90 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-800",
        "transition hover:bg-zinc-50 active:scale-[0.98] active:bg-zinc-100/80",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "dark:border-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-200 dark:hover:bg-zinc-800/90",
        className
      )}
    />
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={cn(
        "relative inline-flex h-7 w-12 items-center rounded-full border border-transparent transition",
        "active:scale-[0.98]",
        value
          ? "bg-emerald-600 shadow-sm dark:bg-emerald-500"
          : "bg-zinc-300 dark:bg-zinc-600"
      )}
      role="switch"
      aria-checked={value}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition",
          value ? "translate-x-7" : "translate-x-1.5"
        )}
      />
    </button>
  );
}
