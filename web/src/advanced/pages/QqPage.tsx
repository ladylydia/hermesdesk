import { Bot } from "lucide-react";
import { PlatformPage } from "./PlatformPage";
import { Section } from "../../components/ui/Section";
import { QqbotQrRouteBlock } from "../../components/QqbotQrRouteBlock";
import { useI18n } from "../../lib/i18n";
import { GatewayChannelSettingsPanel } from "../GatewayChannelSettingsPanel";

export function QqPage() {
  const { t } = useI18n();
  return (
    <PlatformPage title={t("settings.qqTitle")} desc={t("settings.qqLead")}>
      <Section icon={Bot} title={t("settings.qqTitle")}>
        <QqbotQrRouteBlock />
      </Section>
      <GatewayChannelSettingsPanel platform="qqbot" />
    </PlatformPage>
  );
}
