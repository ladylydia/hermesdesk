import { Store } from "lucide-react";
import { PlatformPage } from "./PlatformPage";
import { Section } from "../../components/ui/Section";
import { DingTalkSettingsBlock } from "../../components/DingTalkSettingsBlock";
import { useI18n } from "../../lib/i18n";
import { GatewayChannelSettingsPanel } from "../GatewayChannelSettingsPanel";

export function DingTalkPage() {
  const { t } = useI18n();
  return (
    <PlatformPage title={t("settings.dingtalkTitle")} desc={t("settings.dingtalkLead")}>
      <Section icon={Store} title={t("settings.dingtalkTitle")}>
        <DingTalkSettingsBlock />
      </Section>
      <GatewayChannelSettingsPanel platform="dingtalk" />
    </PlatformPage>
  );
}
