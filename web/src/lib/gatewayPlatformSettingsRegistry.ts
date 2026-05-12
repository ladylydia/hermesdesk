/**
 * Registry of gateway channel settings shown in Kabuqina Settings (not Wizard).
 * Keys must match Hermes `load_gateway_config` / adapters — see hermes_cli/gateway.py.
 * i18n: `settings.channelEnv.*` in locales/strings.ts
 */

export type EnvFieldType = "string" | "secret" | "enum" | "bool";

export type EnvFieldDef = {
  envKey: string;
  labelKey: string;
  descriptionKey?: string;
  type: EnvFieldType;
  enumValues?: string[];
  placeholder?: string;
  recommended?: string;
  advanced?: boolean;
};

export type GatewayPlatformSection = {
  id: "connection" | "dm" | "groups" | "home" | "advanced";
  titleKey: string;
  fields: EnvFieldDef[];
  footnoteKey?: string;
};

export type GatewayPlatformRegistryEntry = {
  platform: string;
  sections: GatewayPlatformSection[];
};

export const HOST_ENV_PREFIXES: Record<string, string[]> = {
  feishu: ["FEISHU_"],
  qqbot: ["QQ_", "QQBOT_"],
  weixin: ["WEIXIN_"],
  wecom: ["WECOM_"],
  dingtalk: ["DINGTALK_"],
  telegram: ["TELEGRAM_"],
  email: ["EMAIL_", "SMS_"],
};

const GW = "settings.channelEnv";

export const GATEWAY_PLATFORM_REGISTRY: GatewayPlatformRegistryEntry[] = [
  {
    platform: "feishu",
    sections: [
      {
        id: "connection",
        titleKey: `${GW}.sectionConnection`,
        fields: [
          {
            envKey: "FEISHU_DOMAIN",
            labelKey: `${GW}.feishuDomain`,
            descriptionKey: `${GW}.feishuDomainDesc`,
            type: "enum",
            enumValues: ["feishu", "lark"],
            recommended: "feishu",
          },
          {
            envKey: "FEISHU_CONNECTION_MODE",
            labelKey: `${GW}.feishuConnMode`,
            descriptionKey: `${GW}.feishuConnModeDesc`,
            type: "enum",
            enumValues: ["websocket", "webhook"],
            recommended: "websocket",
          },
          {
            envKey: "FEISHU_ENCRYPT_KEY",
            labelKey: `${GW}.feishuEncryptKey`,
            descriptionKey: `${GW}.feishuEncryptKeyDesc`,
            type: "secret",
            advanced: true,
          },
          {
            envKey: "FEISHU_VERIFICATION_TOKEN",
            labelKey: `${GW}.feishuVerifyToken`,
            descriptionKey: `${GW}.feishuVerifyTokenDesc`,
            type: "secret",
            advanced: true,
          },
        ],
      },
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        footnoteKey: `${GW}.feishuDmFootnote`,
        fields: [
          {
            envKey: "FEISHU_ALLOW_ALL_USERS",
            labelKey: `${GW}.feishuAllowAllDm`,
            descriptionKey: `${GW}.feishuAllowAllDmDesc`,
            type: "bool",
            recommended: "false",
          },
          {
            envKey: "FEISHU_ALLOWED_USERS",
            labelKey: `${GW}.feishuAllowedUsers`,
            descriptionKey: `${GW}.feishuAllowedUsersDesc`,
            type: "string",
          },
        ],
      },
      {
        id: "groups",
        titleKey: `${GW}.sectionGroups`,
        footnoteKey: `${GW}.feishuGroupFootnote`,
        fields: [
          {
            envKey: "FEISHU_GROUP_POLICY",
            labelKey: `${GW}.feishuGroupPolicy`,
            descriptionKey: `${GW}.feishuGroupPolicyDesc`,
            type: "enum",
            enumValues: ["open", "disabled", "allowlist"],
            recommended: "open",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "FEISHU_HOME_CHANNEL",
            labelKey: `${GW}.feishuHome`,
            descriptionKey: `${GW}.feishuHomeDesc`,
            type: "string",
          },
        ],
      },
    ],
  },
  {
    platform: "qqbot",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "QQ_ALLOW_ALL_USERS",
            labelKey: `${GW}.qqAllowAllDm`,
            descriptionKey: `${GW}.qqAllowAllDmDesc`,
            type: "bool",
            recommended: "false",
          },
          {
            envKey: "QQ_ALLOWED_USERS",
            labelKey: `${GW}.qqAllowedUsers`,
            descriptionKey: `${GW}.qqAllowedUsersDesc`,
            type: "string",
          },
        ],
      },
      {
        id: "groups",
        titleKey: `${GW}.sectionGroups`,
        fields: [
          {
            envKey: "QQ_GROUP_POLICY",
            labelKey: `${GW}.qqGroupPolicy`,
            descriptionKey: `${GW}.qqGroupPolicyDesc`,
            type: "enum",
            enumValues: ["open", "allowlist", "disabled"],
            recommended: "open",
          },
          {
            envKey: "QQ_GROUP_ALLOWED_USERS",
            labelKey: `${GW}.qqGroupAllowlist`,
            descriptionKey: `${GW}.qqGroupAllowlistDesc`,
            type: "string",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "QQBOT_HOME_CHANNEL",
            labelKey: `${GW}.qqHome`,
            descriptionKey: `${GW}.qqHomeDesc`,
            type: "string",
          },
        ],
      },
      {
        id: "advanced",
        titleKey: `${GW}.sectionAdvanced`,
        fields: [
          {
            envKey: "QQ_MARKDOWN_SUPPORT",
            labelKey: `${GW}.qqMarkdown`,
            type: "bool",
            advanced: true,
          },
          {
            envKey: "QQ_SANDBOX",
            labelKey: `${GW}.qqSandbox`,
            type: "bool",
            advanced: true,
          },
        ],
      },
    ],
  },
  {
    platform: "weixin",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "WEIXIN_DM_POLICY",
            labelKey: `${GW}.wxDmPolicy`,
            descriptionKey: `${GW}.wxDmPolicyDesc`,
            type: "enum",
            enumValues: ["pairing", "open", "allowlist", "disabled"],
            recommended: "pairing",
          },
          {
            envKey: "WEIXIN_ALLOWED_USERS",
            labelKey: `${GW}.wxAllowedUsers`,
            descriptionKey: `${GW}.wxAllowedUsersDesc`,
            type: "string",
          },
        ],
      },
      {
        id: "groups",
        titleKey: `${GW}.sectionGroups`,
        fields: [
          {
            envKey: "WEIXIN_GROUP_POLICY",
            labelKey: `${GW}.wxGroupPolicy`,
            descriptionKey: `${GW}.wxGroupPolicyDesc`,
            type: "enum",
            enumValues: ["disabled", "open", "allowlist"],
            recommended: "disabled",
          },
          {
            envKey: "WEIXIN_GROUP_ALLOWED_USERS",
            labelKey: `${GW}.wxGroupAllowed`,
            type: "string",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "WEIXIN_HOME_CHANNEL",
            labelKey: `${GW}.wxHome`,
            type: "string",
          },
          {
            envKey: "WEIXIN_CDN_BASE_URL",
            labelKey: `${GW}.wxCdnUrl`,
            type: "string",
            advanced: true,
          },
        ],
      },
    ],
  },
  {
    platform: "wecom",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "WECOM_DM_POLICY",
            labelKey: `${GW}.wecomDmPolicy`,
            descriptionKey: `${GW}.wecomDmPolicyDesc`,
            type: "enum",
            enumValues: ["pairing", "open", "disabled"],
            recommended: "pairing",
          },
          {
            envKey: "WECOM_ALLOW_ALL_USERS",
            labelKey: `${GW}.wecomAllowAll`,
            descriptionKey: `${GW}.wecomAllowAllDesc`,
            type: "bool",
          },
          {
            envKey: "GATEWAY_ALLOW_ALL_USERS",
            labelKey: `${GW}.gatewayAllowAll`,
            descriptionKey: `${GW}.gatewayAllowAllDesc`,
            type: "bool",
            advanced: true,
          },
          {
            envKey: "WECOM_ALLOWED_USERS",
            labelKey: `${GW}.wecomAllowedUsers`,
            type: "string",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "WECOM_HOME_CHANNEL",
            labelKey: `${GW}.wecomHome`,
            type: "string",
          },
        ],
      },
    ],
  },
  {
    platform: "dingtalk",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "DINGTALK_ALLOW_ALL_USERS",
            labelKey: `${GW}.dingAllowAll`,
            descriptionKey: `${GW}.dingAllowAllDesc`,
            type: "bool",
            recommended: "true",
          },
          {
            envKey: "DINGTALK_ALLOWED_USERS",
            labelKey: `${GW}.dingAllowedUsers`,
            type: "string",
            advanced: true,
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "DINGTALK_HOME_CHANNEL",
            labelKey: `${GW}.dingHome`,
            type: "string",
          },
        ],
      },
    ],
  },
  {
    platform: "telegram",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "GATEWAY_ALLOW_ALL_USERS",
            labelKey: `${GW}.tgGatewayAllowAll`,
            descriptionKey: `${GW}.tgGatewayAllowAllDesc`,
            type: "bool",
            advanced: true,
          },
          {
            envKey: "TELEGRAM_ALLOWED_USERS",
            labelKey: `${GW}.tgAllowedUsers`,
            type: "string",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "TELEGRAM_HOME_CHANNEL",
            labelKey: `${GW}.tgHome`,
            type: "string",
          },
        ],
      },
      {
        id: "advanced",
        titleKey: `${GW}.sectionAdvanced`,
        fields: [
          {
            envKey: "TELEGRAM_REPLY_TO_MODE",
            labelKey: `${GW}.tgReplyMode`,
            descriptionKey: `${GW}.tgReplyModeDesc`,
            type: "enum",
            enumValues: ["off", "first", "all"],
            recommended: "first",
          },
        ],
      },
    ],
  },
  {
    platform: "email",
    sections: [
      {
        id: "dm",
        titleKey: `${GW}.sectionDm`,
        fields: [
          {
            envKey: "EMAIL_ALLOWED_USERS",
            labelKey: `${GW}.emailAllowedSenders`,
            type: "string",
          },
        ],
      },
      {
        id: "home",
        titleKey: `${GW}.sectionHome`,
        fields: [
          {
            envKey: "SMS_HOME_CHANNEL",
            labelKey: `${GW}.smsHomeChannel`,
            type: "string",
            advanced: true,
          },
        ],
      },
    ],
  },
];

export function registryForPlatform(
  platform: string,
): GatewayPlatformRegistryEntry | undefined {
  return GATEWAY_PLATFORM_REGISTRY.find((e) => e.platform === platform);
}

export function allEnvKeysForPlatform(platform: string): string[] {
  const entry = registryForPlatform(platform);
  if (!entry) return [];
  const keys: string[] = [];
  for (const s of entry.sections) {
    for (const f of s.fields) keys.push(f.envKey);
  }
  return keys;
}
