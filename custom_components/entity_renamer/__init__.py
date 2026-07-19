"""Entity ID Renamer -- rename entity IDs and every reference to them."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_ICON,
    PANEL_NAME,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
)
from .websocket_api import async_register

_LOGGER = logging.getLogger(__name__)


async def _async_register_static(hass: HomeAssistant) -> None:
    """Serve the panel bundle, using whichever http API this core version has.

    A static route can only be added once per aiohttp app, so reloading the
    integration must not try again.
    """
    if hass.data[DOMAIN].get("static_registered"):
        return
    hass.data[DOMAIN]["static_registered"] = True

    source = Path(__file__).parent / "frontend"

    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(source), False)]
        )
    except ImportError:  # core < 2024.7
        hass.http.register_static_path(STATIC_URL, str(source), False)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the panel and its websocket commands."""
    hass.data.setdefault(DOMAIN, {})

    async_register(hass)
    await _async_register_static(hass)

    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        require_admin=True,
        # Idempotent: re-registering an existing panel would otherwise raise.
        update=True,
        config={
            "_panel_custom": {
                "name": PANEL_NAME,
                "embed_iframe": False,
                "trust_external": False,
                # Version query busts the browser cache on upgrade.
                "module_url": f"{STATIC_URL}/{PANEL_NAME}.js?v={VERSION}",
            }
        },
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the sidebar panel."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    # The static-path flag deliberately survives: the route itself cannot be
    # removed from aiohttp, so a re-setup must not try to register it again.
    return True
