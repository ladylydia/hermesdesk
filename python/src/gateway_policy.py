"""GatewayPolicy — platform feature flags and defaults.

Extracted from scattered gateway-patch behavior and
``overlays/strip_shims.py``.

Target replacement: a single policy object that governs:
  - which platforms are enabled (feature flags)
  - per-platform defaults (mention rules, webhook verify, owner default)
  - whether gateway code is loaded at all in the web child
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlatformConfig:
    owner_default: str = "open"        # "open" | "pairing"
    require_mention: bool = True       # require @mention in groups
    webhook_verify: bool = True        # warn if webhook crypto keys missing


@dataclass
class GatewayPolicy:
    """Central policy for the messaging gateway subsystem."""

    enabled: bool = False              # True when gateway child is spawned
    weixin_enabled: bool = True        # product feature flag
    feishu_enabled: bool = True        # product feature flag

    platforms: dict[str, PlatformConfig] = field(default_factory=lambda: {
        "weixin": PlatformConfig(owner_default="open"),
        "feishu": PlatformConfig(owner_default="open"),
        "qqbot": PlatformConfig(owner_default="open"),
        "telegram": PlatformConfig(require_mention=False),
        "dingtalk": PlatformConfig(require_mention=True),
        "wecom": PlatformConfig(owner_default="open"),
    })
