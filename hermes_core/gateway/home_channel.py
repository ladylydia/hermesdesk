"""Home-channel helpers for messaging gateway platforms."""

import logging
import os
from typing import Callable, Optional

from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig
from gateway.session import SessionSource

logger = logging.getLogger(__name__)


_AUTO_HOME_EXCLUDED_PLATFORMS = {
    Platform.LOCAL,
    Platform.API_SERVER,
    Platform.WEBHOOK,
}


def home_channel_env_key(platform: Platform) -> str:
    """Return the environment variable used for a platform home channel."""
    return f"{platform.value.upper().replace('-', '_')}_HOME_CHANNEL"


def _ensure_platform_config(
    config: GatewayConfig,
    platform: Platform,
) -> PlatformConfig:
    platform_config = config.platforms.get(platform)
    if platform_config is None:
        platform_config = PlatformConfig(enabled=True)
        config.platforms[platform] = platform_config
    return platform_config


def _home_name_for_source(source: SessionSource) -> str:
    return source.chat_name or source.user_name or source.chat_id or "Home"


def maybe_auto_set_home_channel(
    config: GatewayConfig,
    source: SessionSource,
    *,
    save_env_value: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Auto-set the first authorized DM as the platform home channel.

    Groups/channels/threads are never auto-selected, and any existing home
    channel is preserved. Explicit ``/sethome`` remains the only way for a
    group chat to become home.
    """
    platform = source.platform
    if platform is None or platform in _AUTO_HOME_EXCLUDED_PLATFORMS:
        return False
    if source.chat_type != "dm" or not source.chat_id:
        return False

    env_key = home_channel_env_key(platform)
    platform_config = _ensure_platform_config(config, platform)

    existing_home = (os.getenv(env_key) or "").strip()
    if existing_home:
        if platform_config.home_channel is None:
            platform_config.home_channel = HomeChannel(
                platform=platform,
                chat_id=existing_home,
                name=os.getenv(f"{env_key}_NAME", "Home"),
            )
        return False
    if platform_config.home_channel:
        return False

    chat_id = str(source.chat_id)
    if save_env_value is None:
        from hermes_cli.config import save_env_value as _save_env_value

        save_env_value = _save_env_value

    save_env_value(env_key, chat_id)
    os.environ[env_key] = chat_id
    platform_config.home_channel = HomeChannel(
        platform=platform,
        chat_id=chat_id,
        name=_home_name_for_source(source),
    )
    logger.info(
        "Auto-set home channel for %s to DM %s",
        platform.value,
        chat_id,
    )
    return True
