export type PostPassSectionId = "tts" | "terminal" | "gateway" | "tools" | "agent";

export type LocaleKey = "zh" | "en";

export type Localized = Record<LocaleKey, string>;

/**
 * A single user-editable value under a catalog row (env name / config key is usually `id`).
 * Empty string = “leave to Hermes / default / not set in this session”.
 */
export type OptionConfigField = {
  id: string;
  label: Localized;
  placeholder: Localized;
  kind: "text" | "password" | "url";
  /** If true, UI may leave blank; still saved as "". */
  optional: boolean;
};

export type SetupCatalogOption = {
  id: string;
  name: Localized;
  defaultHint: Localized;
  isDefault?: boolean;
  /**
   * When present, the row has a "配置" action that opens a form for these fields.
   * (User-facing "子流程" = concrete configuration, not a help pop-up.)
   */
  configFields?: OptionConfigField[];
  /**
   * Custom modal body instead of generic env fields (e.g. Weixin iLink route C).
   * If set, `configFields` may be omitted.
   */
  configUi?: "weixin_route_c" | "qqbot_route_c" | "feishu_route_c";
};
