import { Store } from "lucide-react";
import { PlatformPage } from "./PlatformPage";
import { Section } from "../../components/ui/Section";
import { WeComSettingsBlock } from "../../components/WeComSettingsBlock";
import { useI18n } from "../../lib/i18n";
import { GatewayChannelSettingsPanel } from "../GatewayChannelSettingsPanel";

export function WeComPage() {
  const { t } = useI18n();
  return (
    <PlatformPage title={t("settings.wecomTitle")} desc={t("settings.wecomLead")}>
      <Section icon={Store} title={t("settings.wecomTitle")}>
        <WeComSettingsBlock />
      </Section>
      <GatewayChannelSettingsPanel platform="wecom" />
    </PlatformPage>
  );
}
