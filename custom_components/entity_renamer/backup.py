"""Snapshot the files an apply run can touch, before it touches them."""

from __future__ import annotations

import logging
import os
import tarfile
from datetime import datetime
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import BACKUP_DIR, BACKUP_KEEP

_LOGGER = logging.getLogger(__name__)


def _create(config_dir: Path, yaml_files: list[Path]) -> str:
    backup_root = config_dir / BACKUP_DIR
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = backup_root / f"entity_renamer-{stamp}.tar.gz"

    with tarfile.open(archive, "w:gz") as tar:
        storage = config_dir / ".storage"
        if storage.is_dir():
            tar.add(storage, arcname=".storage")
        for path in yaml_files:
            try:
                tar.add(path, arcname=str(path.relative_to(config_dir)))
            except ValueError:
                # Outside the config dir; nothing we should be writing anyway.
                continue

    _prune(backup_root)
    return str(archive)


def _prune(backup_root: Path) -> None:
    archives = sorted(
        backup_root.glob("entity_renamer-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in archives[BACKUP_KEEP:]:
        try:
            os.remove(stale)
        except OSError:  # pragma: no cover - best effort
            _LOGGER.warning("Could not remove old backup %s", stale)


async def async_create_backup(
    hass: HomeAssistant, yaml_files: list[Path]
) -> str:
    """Write a tar.gz of `.storage` plus every YAML file in scope.

    Returns the archive path. Restoring is a manual `tar xzf` into /config
    followed by a restart -- deliberately not automated, so a restore is always
    a decision the user makes with their eyes open.
    """
    config_dir = Path(hass.config.path())
    return await hass.async_add_executor_job(_create, config_dir, yaml_files)
