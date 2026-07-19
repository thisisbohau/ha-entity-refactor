"""Websocket commands backing the Entity Renamer panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .engine import async_apply, async_scan

_LOGGER = logging.getLogger(__name__)

# An item may carry a rename, metadata edits, or both. Everything except the
# entity being edited is optional, so a metadata-only batch is valid.
_RENAME_SCHEMA = vol.Schema(
    {
        vol.Required("old_entity_id"): str,
        vol.Optional("new_entity_id"): vol.Any(str, None),
        vol.Optional("new_name"): vol.Any(str, None),
        vol.Optional("new_labels"): [str],
        vol.Optional("new_categories"): {str: vol.Any(str, None)},
    }
)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the panel's websocket commands."""
    websocket_api.async_register_command(hass, ws_preview)
    websocket_api.async_register_command(hass, ws_apply)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/preview",
        vol.Required("renames"): [_RENAME_SCHEMA],
        vol.Optional("dashboards", default=dict): dict,
    }
)
@websocket_api.async_response
async def ws_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Dry run -- report every change that an apply would make."""
    try:
        result = await async_scan(hass, msg["renames"], msg.get("dashboards"))
    except Exception as err:  # noqa: BLE001 - surface failures in the panel
        _LOGGER.exception("Entity Renamer preview failed")
        connection.send_error(msg["id"], "preview_failed", str(err))
        return

    connection.send_result(msg["id"], result.as_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/apply",
        vol.Required("renames"): [_RENAME_SCHEMA],
        vol.Optional("dashboards", default=dict): dict,
    }
)
@websocket_api.async_response
async def ws_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Back up, then rename and rewrite every reference."""
    try:
        result = await async_apply(hass, msg["renames"], msg.get("dashboards"))
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Entity Renamer apply failed")
        connection.send_error(msg["id"], "apply_failed", str(err))
        return

    connection.send_result(msg["id"], result.as_dict())
