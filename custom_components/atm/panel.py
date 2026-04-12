"""Panel registration for the ATM admin UI."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_URL = "/local/atm"
_JS_URL = f"{_PANEL_URL}/atm-panel.js"
_PANEL_KEY = "atm"

_panel_registered: bool = False


async def async_register_atm_panel(hass: HomeAssistant) -> None:
    """Register the static frontend bundle and the Lovelace panel.

    Safe to call on re-setup: removes any stale panel entry before registering.
    Static path registration is skipped silently if already registered.
    """
    global _panel_registered

    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                url_path=_PANEL_URL,
                path=str(_FRONTEND_DIR),
                cache_headers=False,
            )
        ])
    except RuntimeError:
        pass

    if _panel_registered:
        async_remove_panel(hass, _PANEL_KEY)

    async_register_built_in_panel(
        hass=hass,
        component_name="custom",
        sidebar_title="ATM",
        sidebar_icon="mdi:key-variant",
        frontend_url_path=_PANEL_KEY,
        require_admin=True,
        config={
            "_panel_custom": {
                "name": "atm-panel",
                "js_url": _JS_URL,
            }
        },
    )
    _panel_registered = True


def remove_atm_panel(hass: HomeAssistant) -> None:
    """Remove the panel if it was registered in this session.

    Silently skips if the panel was never registered (e.g. unload before setup
    completed, or HA restarted with the kill switch enabled).
    """
    global _panel_registered

    if _panel_registered:
        async_remove_panel(hass, _PANEL_KEY)
        _panel_registered = False
