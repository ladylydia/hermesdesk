import { Building2 } from "lucide-react";
import { PlatformPage } from "./PlatformPage";
import { Section } from "../../components/ui/Section";
import { FeishuQrRouteBlock } from "../../components/FeishuQrRouteBlock";
import { useI18n } from "../../lib/i18n";
import { GatewayChannelSettingsPanel } from "../GatewayChannelSettingsPanel";

export function FeishuPage() {
  const { t } = useI18n();
  return (
    <PlatformPage title={t("settings.feishuTitle")} desc={t("settings.feishuLead")}>
      <Section icon={Building2} title={t("settings.feishuTitle")}>
        <FeishuQrRouteBlock />
      </Section>
      <GatewayChannelSettingsPanel platform="feishu" />
    </PlatformPage>
  );
}
