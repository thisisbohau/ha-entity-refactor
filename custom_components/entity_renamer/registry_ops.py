"""Entity registry metadata edits: friendly name, labels and category.

Kept apart from :mod:`engine` because these edits are fundamentally different
from an entity ID rename -- nothing outside the registry references them, so
they need no file rewriting. They still travel through the same preview and the
same single Apply, so the user sees one confirmation for the whole batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

NO_VALUE = "—"


@dataclass
class EntityOps:
    """Everything the user changed about one entity."""

    entity_id: str
    new_entity_id: str | None = None
    # kwargs handed straight to `async_update_entity`, minus new_entity_id.
    updates: dict[str, Any] = field(default_factory=dict)
    # Human-readable "before -> after" rows for the preview.
    descriptions: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_metadata(self) -> bool:
        return bool(self.updates)


# ---------------------------------------------------------------------------
# Registry lookups, written defensively: label and category registries are
# newer than the minimum core version some users will be on.
# ---------------------------------------------------------------------------


def _label_names(hass: HomeAssistant, label_ids) -> str:
    try:
        from homeassistant.helpers import label_registry as lr

        registry = lr.async_get(hass)
    except Exception:  # noqa: BLE001
        return ", ".join(sorted(label_ids)) or NO_VALUE

    names = []
    for label_id in sorted(label_ids or []):
        entry = registry.async_get_label(label_id)
        names.append(entry.name if entry else label_id)
    return ", ".join(names) or NO_VALUE


def _category_name(hass: HomeAssistant, categories: dict[str, str]) -> str:
    if not categories:
        return NO_VALUE
    try:
        from homeassistant.helpers import category_registry as cr

        registry = cr.async_get(hass)
    except Exception:  # noqa: BLE001
        registry = None

    parts = []
    for scope, category_id in sorted(categories.items()):
        name = category_id
        if registry is not None:
            entry = registry.async_get_category(scope=scope, category_id=category_id)
            if entry:
                name = entry.name
        parts.append(f"{name} ({scope})")
    return ", ".join(parts)


def _validate_labels(hass: HomeAssistant, label_ids: list[str]) -> list[str]:
    try:
        from homeassistant.helpers import label_registry as lr

        registry = lr.async_get(hass)
    except Exception:  # noqa: BLE001
        return []
    return [lid for lid in label_ids if registry.async_get_label(lid) is None]


def _validate_categories(hass: HomeAssistant, categories: dict[str, str]) -> list[str]:
    try:
        from homeassistant.helpers import category_registry as cr

        registry = cr.async_get(hass)
    except Exception:  # noqa: BLE001
        return []
    return [
        f"{scope}/{category_id}"
        for scope, category_id in categories.items()
        if registry.async_get_category(scope=scope, category_id=category_id) is None
    ]


# ---------------------------------------------------------------------------


def build_ops(
    hass: HomeAssistant, items: list[dict[str, Any]]
) -> tuple[list[EntityOps], list[str]]:
    """Turn the panel payload into validated per-entity operations."""
    registry = er.async_get(hass)
    ops: list[EntityOps] = []
    errors: list[str] = []

    for item in items:
        entity_id = (item.get("old_entity_id") or "").strip()
        if not entity_id:
            continue

        entry = registry.async_get(entity_id)
        if entry is None:
            errors.append(f"'{entity_id}' is not in the entity registry.")
            continue

        op = EntityOps(entity_id=entity_id)

        # --- friendly name -------------------------------------------------
        if "new_name" in item:
            new_name = item["new_name"]
            new_name = new_name.strip() if isinstance(new_name, str) else None
            # An empty box means "clear my override", falling back to the name
            # the integration itself supplied.
            new_name = new_name or None
            current = entry.name
            if new_name != current:
                op.updates["name"] = new_name
                op.descriptions.append(
                    (
                        f"Name: {current or entry.original_name or NO_VALUE}",
                        f"Name: {new_name or entry.original_name or NO_VALUE}",
                    )
                )

        # --- labels --------------------------------------------------------
        if "new_labels" in item:
            new_labels = set(item["new_labels"] or [])
            unknown = _validate_labels(hass, sorted(new_labels))
            if unknown:
                errors.append(
                    f"'{entity_id}' refers to unknown label(s): {', '.join(unknown)}."
                )
            elif new_labels != set(entry.labels or ()):
                op.updates["labels"] = new_labels
                op.descriptions.append(
                    (
                        f"Labels: {_label_names(hass, entry.labels)}",
                        f"Labels: {_label_names(hass, new_labels)}",
                    )
                )

        # --- category ------------------------------------------------------
        if "new_categories" in item:
            new_categories = {
                scope: category_id
                for scope, category_id in (item["new_categories"] or {}).items()
                if category_id
            }
            unknown = _validate_categories(hass, new_categories)
            if unknown:
                errors.append(
                    f"'{entity_id}' refers to unknown categor(y/ies): {', '.join(unknown)}."
                )
            elif new_categories != dict(entry.categories or {}):
                op.updates["categories"] = new_categories
                op.descriptions.append(
                    (
                        f"Category: {_category_name(hass, dict(entry.categories or {}))}",
                        f"Category: {_category_name(hass, new_categories)}",
                    )
                )

        if op.updates:
            ops.append(op)

    return ops, errors


def apply_ops(hass: HomeAssistant, ops: list[EntityOps]) -> list[str]:
    """Write metadata edits to the entity registry. Returns per-entity errors."""
    registry = er.async_get(hass)
    errors: list[str] = []

    for op in ops:
        if not op.updates:
            continue
        try:
            registry.async_update_entity(op.entity_id, **op.updates)
        except (ValueError, KeyError, TypeError) as err:
            errors.append(f"Could not update '{op.entity_id}': {err}")

    return errors
