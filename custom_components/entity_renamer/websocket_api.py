"""Websocket commands backing the Entity Renamer panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .backup import async_create_backup
from .const import DOMAIN
from .engine import async_apply, async_scan
from .orphans import find_orphans, remove_orphans

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
    websocket_api.async_register_command(hass, ws_orphans)
    websocket_api.async_register_command(hass, ws_remove_orphans)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/preview",
        vol.Required("renames"): [_RENAME_SCHEMA],
        vol.Optional("dashboards", default=dict): dict,
        # Accepted and ignored: the panel sends one payload shape for both
        # commands, and a preview never writes anything either way.
        vol.Optional("skip_references", default=False): bool,
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
        # Registry-only save: write the entity registry and stop there.
        vol.Optional("skip_references", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Back up, then rename and (unless skipped) rewrite every reference."""
    try:
        result = await async_apply(
            hass,
            msg["renames"],
            msg.get("dashboards"),
            skip_references=msg["skip_references"],
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Entity Renamer apply failed")
        connection.send_error(msg["id"], "apply_failed", str(err))
        return

    connection.send_result(msg["id"], result.as_dict())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/orphans"})
@websocket_api.async_response
async def ws_orphans(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List registry entries no integration is providing any more."""
    try:
        found, warnings = find_orphans(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Entity Renamer orphan scan failed")
        connection.send_error(msg["id"], "orphan_scan_failed", str(err))
        return

    connection.send_result(msg["id"], {"orphans": found, "warnings": warnings})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_orphans",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_remove_orphans(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete orphaned registry entries, after re-verifying each one.

    The caller's list is treated as a request, not an instruction: every entity
    is re-checked server-side, so an entity that came back to life since the
    panel listed it is refused rather than deleted.
    """
    entity_ids = msg["entity_ids"]
    if not entity_ids:
        connection.send_result(msg["id"], {"removed": [], "errors": [], "backup": None})
        return

    try:
        # Registry-only change, so .storage alone is enough of a snapshot.
        backup = await async_create_backup(hass, [])
        removed, errors = remove_orphans(hass, entity_ids)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Entity Renamer orphan removal failed")
        connection.send_error(msg["id"], "orphan_removal_failed", str(err))
        return

    connection.send_result(
        msg["id"], {"removed": removed, "errors": errors, "backup": backup}
    )
