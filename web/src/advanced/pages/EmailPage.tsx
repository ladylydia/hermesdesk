import { Mail } from "lucide-react";
import { PlatformPage } from "./PlatformPage";
import { Section } from "../../components/ui/Section";
import { SettingsEmailBlock } from "../settings/SettingsEmail";
import { useI18n } from "../../lib/i18n";
import { GatewayChannelSettingsPanel } from "../GatewayChannelSettingsPanel";

export function EmailPage() {
  const { t } = useI18n();
  return (
    <PlatformPage title={t("settings.emailTitle")} desc={t("settings.emailLead")}>
      <Section icon={Mail} title={t("settings.emailTitle")}>
        <SettingsEmailBlock />
      </Section>
      <GatewayChannelSettingsPanel platform="email" />
    </PlatformPage>
  );
}
