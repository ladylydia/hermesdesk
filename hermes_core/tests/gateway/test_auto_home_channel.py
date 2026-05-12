"""Tests for automatic gateway home-channel designation."""

from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig
from gateway.home_channel import maybe_auto_set_home_channel
from gateway.session import SessionSource


def _config(
    platform: Platform = Platform.TELEGRAM,
    home_channel: HomeChannel | None = None,
) -> GatewayConfig:
    return GatewayConfig(
        platforms={
            platform: PlatformConfig(
                enabled=True,
                token="token",
                home_channel=home_channel,
            )
        }
    )


def _source(
    *,
    platform: Platform = Platform.TELEGRAM,
    chat_id: str = "dm-123",
    chat_type: str = "dm",
) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_name="Alice" if chat_type == "dm" else "Project Room",
        chat_type=chat_type,
        user_id="user-1",
        user_name="Alice",
    )


def test_first_authorized_dm_sets_platform_home_channel(monkeypatch):
    monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)
    saved: dict[str, str] = {}

    changed = maybe_auto_set_home_channel(
        _config(),
        _source(chat_id="dm-123", chat_type="dm"),
        save_env_value=lambda key, value: saved.__setitem__(key, value),
    )

    assert changed is True
    assert saved == {"TELEGRAM_HOME_CHANNEL": "dm-123"}


def test_group_message_does_not_auto_set_home_channel(monkeypatch):
    monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)
    saved: dict[str, str] = {}
    config = _config()

    changed = maybe_auto_set_home_channel(
        config,
        _source(chat_id="group-123", chat_type="group"),
        save_env_value=lambda key, value: saved.__setitem__(key, value),
    )

    assert changed is False
    assert saved == {}
    assert config.platforms[Platform.TELEGRAM].home_channel is None


def test_existing_home_channel_is_never_overwritten_by_auto_sethome(monkeypatch):
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "existing-home")
    existing = HomeChannel(
        platform=Platform.TELEGRAM,
        chat_id="existing-home",
        name="Existing",
    )
    config = _config(home_channel=existing)
    saved: dict[str, str] = {}

    changed = maybe_auto_set_home_channel(
        config,
        _source(chat_id="new-dm", chat_type="dm"),
        save_env_value=lambda key, value: saved.__setitem__(key, value),
    )

    assert changed is False
    assert saved == {}
    assert config.platforms[Platform.TELEGRAM].home_channel == existing

