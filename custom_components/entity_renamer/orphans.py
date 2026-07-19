"""Find and remove registry entries left behind by integrations that are gone.

An "orphan" is a registry entry that no integration is currently providing: the
entity ID is reserved and clutters every picker, but nothing will ever give it a
state. Home Assistant shows these as "restored".

Detection is deliberately conservative. A disabled entity has no state by
design, and during startup nothing has a state yet -- both would otherwise look
like orphans, so both are excluded.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

_LOGGER = logging.getLogger(__name__)

REASON_ENTRY_GONE = "Its integration entry no longer exists"
REASON_ENTRY_NOT_LOADED = "Its integration is not loaded"
REASON_NO_PROVIDER = "No integration is providing it"


def _reason(hass: HomeAssistant, entry: er.RegistryEntry) -> str:
    if entry.config_entry_id is None:
        # Typically a YAML platform that has been removed from configuration.
        return REASON_NO_PROVIDER

    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry is None:
        return REASON_ENTRY_GONE

    if config_entry.state is not ConfigEntryState.LOADED:
        return f"{REASON_ENTRY_NOT_LOADED} ({config_entry.title})"

    return REASON_NO_PROVIDER


def is_orphan(hass: HomeAssistant, entry: er.RegistryEntry) -> bool:
    """True when nothing is providing this entity and nothing will.

    This is the single source of truth for orphan status. The removal path
    re-runs it per entity rather than trusting the caller's list.

    Note the `restored` check. Home Assistant writes an `unavailable` state with
    `restored: True` for every registry entry no platform is backing, so a
    simple "has no state" test would find nothing at all. An integration that is
    merely offline still writes a real state, which is exactly the distinction
    that keeps working devices off this list.
    """
    if entry.disabled_by is not None:
        # Disabled entities have no state on purpose; removing them here would
        # be a nasty surprise for anyone who disabled an entity deliberately.
        return False

    state = hass.states.get(entry.entity_id)
    if state is None:
        return True
    return bool(state.attributes.get("restored"))


def find_orphans(hass: HomeAssistant) -> tuple[list[dict[str, Any]], list[str]]:
    """List every orphaned registry entry, with a reason for each."""
    warnings: list[str] = []

    if hass.state is not CoreState.running:
        # Before startup completes almost nothing has a state, so every entity
        # would look orphaned. Refuse rather than show a terrifying list.
        return [], [
            "Home Assistant is still starting up, so orphaned entities cannot be "
            "identified yet. Try again in a minute."
        ]

    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[dict[str, Any]] = []

    for entry in registry.entities.values():
        if not is_orphan(hass, entry):
            continue

        device_name = ""
        if entry.device_id and (device := devices.async_get(entry.device_id)):
            device_name = device.name_by_user or device.name or ""

        found.append(
            {
                "entity_id": entry.entity_id,
                "name": entry.name or entry.original_name or "",
                "platform": entry.platform,
                "device_name": device_name,
                "reason": _reason(hass, entry),
            }
        )

    found.sort(key=lambda item: (item["platform"], item["entity_id"]))
    return found, warnings


def remove_orphans(
    hass: HomeAssistant, entity_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Remove the given entities, but only if they are still orphaned.

    Returns (removed, errors). Re-checking here is the safety net: the panel's
    list may be seconds out of date, and an entity that came back to life in the
    meantime must not be deleted.
    """
    registry = er.async_get(hass)
    removed: list[str] = []
    errors: list[str] = []

    if hass.state is not CoreState.running:
        return [], ["Home Assistant is still starting up; refusing to remove entities."]

    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry is None:
            errors.append(f"'{entity_id}' is no longer in the registry.")
            continue

        if not is_orphan(hass, entry):
            errors.append(
                f"'{entity_id}' is being provided again and was NOT removed."
            )
            continue

        try:
            registry.async_remove(entity_id)
        except (KeyError, ValueError) as err:
            errors.append(f"Could not remove '{entity_id}': {err}")
            continue

        removed.append(entity_id)

    return removed, errors
