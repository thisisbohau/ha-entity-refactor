"""Scan for, and apply, entity ID renames across every place HA stores them.

Design rule: nothing in here edits a file under `.storage` directly. Those files
are mirrored in memory by HA's `Store` objects and would be silently overwritten
on the next save. Storage-backed targets are updated through their public APIs
instead; only `/config/**.yaml` is rewritten as text, where doing so preserves
the user's comments and formatting.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, valid_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .backup import async_create_backup
from .const import (
    DEFAULT_DASHBOARD_KEY,
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    MAX_FILE_SIZE,
    RELOAD_ALL_SERVICE,
    RELOAD_SERVICES,
    YAML_SUFFIXES,
)
from .matcher import Matcher, Occurrence, chain_conflicts, summarise_object_change
from .registry_ops import EntityOps, apply_ops, build_ops

_LOGGER = logging.getLogger(__name__)

KIND_REGISTRY = "registry"
KIND_METADATA = "metadata"
KIND_YAML = "yaml"
KIND_HELPER = "helper"
KIND_DASHBOARD = "dashboard"
KIND_ENERGY = "energy"


@dataclass
class Change:
    """One location that will be, or was, rewritten."""

    kind: str
    target: str
    count: int
    samples: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "count": self.count,
            "samples": self.samples,
            "note": self.note,
        }


@dataclass
class ScanResult:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # url_path -> rewritten config, handed back to the frontend to save.
    dashboards: dict[str, Any] = field(default_factory=dict)
    yaml_files: list[Path] = field(default_factory=list)
    # Populated only on apply.
    backup: str | None = None
    # True once an apply has passed validation and started writing. Distinguishes
    # "rejected, nothing touched" from "ran, but some steps reported errors" --
    # the caller must still finish the job in the second case.
    applied: bool = False
    # True when the caller asked for a registry-only save, so no file, helper,
    # dashboard or energy reference was rewritten.
    references_skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "changes": [c.as_dict() for c in self.changes],
            "errors": self.errors,
            "warnings": self.warnings,
            # Rewritten dashboard configs are only useful to a caller that is
            # going to save them. Sending them back on a dry run would double
            # the payload of every preview for no reason.
            "dashboards": self.dashboards if self.applied else {},
            "total": sum(c.count for c in self.changes),
            "backup": self.backup,
            "applied": self.applied,
            "references_skipped": self.references_skipped,
        }


def _samples(occurrences: list[Occurrence], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"line": o.line, "before": o.before, "after": o.after}
        for o in occurrences[:limit]
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(
    hass: HomeAssistant, renames: list[dict[str, str]]
) -> tuple[dict[str, str], list[str]]:
    """Turn the frontend payload into an old -> new map, or explain why not."""
    registry = er.async_get(hass)
    mapping: dict[str, str] = {}
    errors: list[str] = []

    # Every entity the batch is renaming away from. Needed to tell a real
    # collision apart from a chained rename, which deserves different advice.
    sources = {
        (item.get("old_entity_id") or "").strip()
        for item in renames
        if (item.get("new_entity_id") or "").strip()
    }

    for item in renames:
        old = (item.get("old_entity_id") or "").strip()
        new = (item.get("new_entity_id") or "").strip()

        # Items carrying only metadata edits have no new_entity_id; they are
        # handled by registry_ops, not here.
        if not old or not new or old == new:
            continue

        entry = registry.async_get(old)
        if entry is None:
            errors.append(f"'{old}' is not in the entity registry.")
            continue

        if "." not in new:
            errors.append(f"'{new}' is not a valid entity ID (needs a domain prefix).")
            continue

        new_domain, _, new_object_id = new.partition(".")
        old_domain = old.partition(".")[0]

        if new_domain != old_domain:
            errors.append(
                f"'{old}' cannot become '{new}': Home Assistant does not allow "
                f"changing the domain ('{old_domain}' -> '{new_domain}')."
            )
            continue

        # Home Assistant's own rule is the authority here: lowercase, digits and
        # single underscores, no leading/trailing or doubled underscore. slugify
        # is used only to suggest a fix.
        if not valid_entity_id(new):
            errors.append(
                f"'{new}' is not a valid entity ID. Use lowercase letters, numbers "
                "and single underscores (suggested: "
                f"'{new_domain}.{slugify(new_object_id) or 'name'}')."
            )
            continue

        existing = registry.async_get(new)
        if existing is not None and existing.entity_id != old:
            if new in sources:
                # Renaming a -> b while b -> c is also queued. Applying both at
                # once would need a specific ordering (and a temporary name if
                # the renames form a cycle), so ask for two runs instead of
                # guessing.
                errors.append(
                    f"'{old}' cannot become '{new}' yet: '{new}' is itself being "
                    "renamed in this batch. Apply that rename on its own first, "
                    "then rename this one."
                )
            else:
                errors.append(f"'{new}' is already taken by another entity.")
            continue

        mapping[old] = new

    errors.extend(chain_conflicts(mapping.items()))
    return mapping, errors


# ---------------------------------------------------------------------------
# YAML files
# ---------------------------------------------------------------------------


def _iter_yaml_files(config_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, files in os.walk(config_dir):
        # Pruning in place stops os.walk descending into excluded trees at all.
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for name in files:
            if name in EXCLUDE_FILES or not name.endswith(YAML_SUFFIXES):
                continue
            path = Path(root) / name
            try:
                if path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            found.append(path)
    return sorted(found)


def _scan_yaml(
    config_dir: Path, matcher: Matcher, write: bool
) -> tuple[list[Change], list[str], list[Path]]:
    changes: list[Change] = []
    errors: list[str] = []
    files = _iter_yaml_files(config_dir)

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            errors.append(f"Could not read {path.name}: {err}")
            continue

        new_text, occurrences = matcher.replace_text(text)
        if not occurrences:
            continue

        if write:
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError as err:
                errors.append(f"Could not write {path.name}: {err}")
                continue

        changes.append(
            Change(
                kind=KIND_YAML,
                target=str(path.relative_to(config_dir)),
                count=len(occurrences),
                samples=_samples(occurrences),
            )
        )

    return changes, errors, files


# ---------------------------------------------------------------------------
# Helper config entries (template sensors, groups, utility meters, ...)
# ---------------------------------------------------------------------------


def _entry_changes(
    hass: HomeAssistant, matcher: Matcher
) -> list[tuple[ConfigEntry, dict[str, Any], dict[str, Any], Change]]:
    pending = []
    for entry in hass.config_entries.async_entries():
        new_data, data_hits = matcher.replace_object(dict(entry.data))
        new_options, option_hits = matcher.replace_object(dict(entry.options))
        total = data_hits + option_hits
        if not total:
            continue

        samples = summarise_object_change(dict(entry.data), new_data)
        samples += summarise_object_change(dict(entry.options), new_options)
        pending.append(
            (
                entry,
                new_data,
                new_options,
                Change(
                    kind=KIND_HELPER,
                    target=f"{entry.title} ({entry.domain})",
                    count=total,
                    samples=[
                        {"line": 0, "before": s.before, "after": s.after}
                        for s in samples[:5]
                    ],
                    note="Helper / integration configuration",
                ),
            )
        )
    return pending


# ---------------------------------------------------------------------------
# Energy dashboard preferences
# ---------------------------------------------------------------------------


async def _energy_change(
    hass: HomeAssistant, matcher: Matcher, write: bool
) -> Change | None:
    try:
        from homeassistant.components.energy.data import async_get_manager
    except ImportError:
        return None

    try:
        manager = await async_get_manager(hass)
    except Exception:  # noqa: BLE001 - energy may not be set up at all
        return None

    if not manager.data:
        return None

    new_data, hits = matcher.replace_object(dict(manager.data))
    if not hits:
        return None

    samples = summarise_object_change(dict(manager.data), new_data)
    if write:
        await manager.async_update(new_data)

    return Change(
        kind=KIND_ENERGY,
        target="Energy dashboard preferences",
        count=hits,
        samples=[{"line": 0, "before": s.before, "after": s.after} for s in samples[:5]],
    )


# ---------------------------------------------------------------------------
# Lovelace dashboards
#
# Configs arrive from the frontend (which fetched them over the public
# `lovelace/config` websocket command) and the rewritten versions go back for
# the frontend to save with `lovelace/config/save`. That keeps HA's in-memory
# copy authoritative at all times.
# ---------------------------------------------------------------------------


def _dashboard_changes(
    matcher: Matcher, dashboards: dict[str, Any]
) -> tuple[list[Change], dict[str, Any]]:
    changes: list[Change] = []
    rewritten: dict[str, Any] = {}

    for url_path, config in (dashboards or {}).items():
        if not config:
            continue
        new_config, hits = matcher.replace_object(config)
        if not hits:
            continue
        samples = summarise_object_change(config, new_config)
        label = "Default dashboard" if url_path == DEFAULT_DASHBOARD_KEY else url_path
        changes.append(
            Change(
                kind=KIND_DASHBOARD,
                target=label,
                count=hits,
                samples=[
                    {"line": 0, "before": s.before, "after": s.after} for s in samples[:5]
                ],
                note="Lovelace dashboard",
            )
        )
        rewritten[url_path] = new_config

    return changes, rewritten


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _metadata_change(op: EntityOps) -> Change:
    """One preview card summarising an entity's name/label/category edits."""
    return Change(
        kind=KIND_METADATA,
        target=op.entity_id,
        count=len(op.descriptions),
        samples=[
            {"line": 0, "before": before, "after": after}
            for before, after in op.descriptions
        ],
        note="Entity registry metadata (no references to rewrite)",
    )


async def async_scan(
    hass: HomeAssistant,
    renames: list[dict[str, Any]],
    dashboards: dict[str, Any] | None = None,
) -> ScanResult:
    """Dry run: report every change without touching anything."""
    result = ScanResult()
    mapping, errors = validate(hass, renames)
    meta_ops, meta_errors = build_ops(hass, renames)
    result.errors = errors + meta_errors

    for op in meta_ops:
        result.changes.append(_metadata_change(op))

    if not mapping:
        # Metadata-only batches still need a preview, but there is nothing to
        # search for in files.
        return result

    matcher = Matcher(mapping)
    config_dir = Path(hass.config.path())

    for old, new in mapping.items():
        result.changes.append(
            Change(
                kind=KIND_REGISTRY,
                target=old,
                count=1,
                samples=[{"line": 0, "before": old, "after": new}],
                note="Entity registry (long-term statistics migrate automatically)",
            )
        )

    yaml_changes, yaml_errors, files = await hass.async_add_executor_job(
        _scan_yaml, config_dir, matcher, False
    )
    result.changes.extend(yaml_changes)
    result.errors.extend(yaml_errors)
    result.yaml_files = files

    result.changes.extend(
        change for *_, change in _entry_changes(hass, matcher)
    )

    if (energy := await _energy_change(hass, matcher, False)) is not None:
        result.changes.append(energy)

    dash_changes, rewritten = _dashboard_changes(matcher, dashboards or {})
    result.changes.extend(dash_changes)
    result.dashboards = rewritten

    return result


async def async_apply(
    hass: HomeAssistant,
    renames: list[dict[str, Any]],
    dashboards: dict[str, Any] | None = None,
    skip_references: bool = False,
) -> ScanResult:
    """Apply the batch. Backs up first; aborts entirely if validation fails.

    With `skip_references`, only the entity registry is written -- no YAML,
    helper, dashboard or energy rewriting. The caller is responsible for any
    references to a renamed ID.
    """
    result = ScanResult()
    result.references_skipped = skip_references
    mapping, errors = validate(hass, renames)
    meta_ops, meta_errors = build_ops(hass, renames)
    result.errors = errors + meta_errors
    if result.errors or (not mapping and not meta_ops):
        return result

    matcher = Matcher(mapping)
    config_dir = Path(hass.config.path())

    # Enumerate YAML up front so the backup covers exactly what we may write.
    # If the backup fails this raises, and it raises before anything has been
    # written -- which is the direction we want to fail in.
    # A registry-only save touches no YAML, so there is nothing to snapshot
    # beyond .storage.
    files = [] if skip_references else await hass.async_add_executor_job(
        _iter_yaml_files, config_dir
    )
    result.backup = await async_create_backup(hass, files)

    # Past this point something will be written, so every later error is a
    # partial-failure report rather than a rejection.
    result.applied = True

    # 1. Registry first. This is what migrates recorder statistics, and it makes
    #    the new IDs resolvable before anything starts referring to them.
    #
    #    An entity that is both renamed and re-labelled must be written in a
    #    single call: once the rename lands, the old entity ID no longer
    #    resolves and a second lookup would fail.
    registry = er.async_get(hass)
    ops_by_entity: dict[str, EntityOps] = {op.entity_id: op for op in meta_ops}

    for old, new in mapping.items():
        op = ops_by_entity.pop(old, None)
        kwargs: dict[str, Any] = dict(op.updates) if op else {}
        kwargs["new_entity_id"] = new
        try:
            registry.async_update_entity(old, **kwargs)
        except (ValueError, KeyError, TypeError) as err:
            result.errors.append(f"Could not rename '{old}': {err}")
            if op is not None:
                # The rename failed, so the entity still answers to its old ID.
                # Put its metadata edits back in the queue rather than losing
                # them along with the rename.
                ops_by_entity[old] = op
            continue
        result.changes.append(
            Change(
                kind=KIND_REGISTRY,
                target=old,
                count=1,
                samples=[{"line": 0, "before": old, "after": new}],
                note="Entity registry",
            )
        )
        if op is not None:
            result.changes.append(_metadata_change(op))

    # 1b. Entities with metadata edits but no rename.
    remaining = list(ops_by_entity.values())
    result.errors.extend(apply_ops(hass, remaining))
    for op in remaining:
        result.changes.append(_metadata_change(op))

    if skip_references or not mapping:
        # Either the caller asked for a registry-only save, or this is a
        # metadata-only batch -- nothing references a friendly name or a label,
        # so the file scan and the reloads have nothing to do.
        return result

    # 2. YAML text rewrite.
    yaml_changes, yaml_errors, _ = await hass.async_add_executor_job(
        _scan_yaml, config_dir, matcher, True
    )
    result.changes.extend(yaml_changes)
    result.errors.extend(yaml_errors)

    # 3. Helper / integration config entries.
    for entry, new_data, new_options, change in _entry_changes(hass, matcher):
        try:
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options
            )
        except Exception as err:  # noqa: BLE001 - one bad entry must not abort
            result.errors.append(f"Could not update '{entry.title}': {err}")
            continue
        result.changes.append(change)

    # 4. Energy dashboard.
    try:
        if (energy := await _energy_change(hass, matcher, True)) is not None:
            result.changes.append(energy)
    except Exception as err:  # noqa: BLE001
        result.errors.append(f"Could not update energy preferences: {err}")

    # 5. Lovelace configs go back to the frontend to save.
    dash_changes, rewritten = _dashboard_changes(matcher, dashboards or {})
    result.changes.extend(dash_changes)
    result.dashboards = rewritten

    # 6. Pick up the rewritten YAML without a restart.
    await _async_reload(hass, result)

    return result


async def _async_reload(hass: HomeAssistant, result: ScanResult) -> None:
    """Reload YAML-backed config so the rewrite takes effect without a restart.

    `homeassistant.reload_all` covers far more domains than any list we could
    maintain, so prefer it. It does not reload core config, so `customize.yaml`
    still needs its own call.
    """
    services: list[tuple[str, str]] = []

    if hass.services.has_service(*RELOAD_ALL_SERVICE):
        services.append(RELOAD_ALL_SERVICE)
        services.append(("homeassistant", "reload_core_config"))
    else:
        services.extend(RELOAD_SERVICES)

    for domain, service in services:
        if not hass.services.has_service(domain, service):
            continue
        try:
            await hass.services.async_call(domain, service, blocking=True)
        except Exception as err:  # noqa: BLE001 - a failed reload is not fatal
            result.warnings.append(
                f"Reload of {domain}.{service} failed ({err}); "
                "restart Home Assistant to pick up the rewritten YAML."
            )
