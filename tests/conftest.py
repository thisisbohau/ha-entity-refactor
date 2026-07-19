"""Shared Home Assistant stubs for the test suite.

Home Assistant is not a test dependency. The component touches a small, stable
set of HA symbols, so they are stubbed here with faithful behaviour (the entity
ID validator is HA's real regex). That keeps the suite fast while still
exercising the component's own logic against real data structures.
"""

from __future__ import annotations

import enum
import importlib
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "entity_renamer"

_VALID_ENTITY_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")


class ConfigEntryState(enum.Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    SETUP_ERROR = "setup_error"


class CoreState(enum.Enum):
    starting = "starting"
    running = "running"
    stopping = "stopping"


def _slugify(value: str, *, separator: str = "_") -> str:
    text = re.sub(r"[^a-z0-9]+", separator, str(value).lower())
    return re.sub(f"{separator}+", separator, text).strip(separator)


def _install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.CoreState = CoreState
    core.valid_entity_id = lambda value: _VALID_ENTITY_ID.match(value) is not None
    core.callback = lambda func: func

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    config_entries.ConfigEntryState = ConfigEntryState

    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: hass.entity_registry
    entity_registry.RegistryEntry = object

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.async_get = lambda hass: hass.device_registry
    device_registry.DeviceEntry = object

    util = types.ModuleType("homeassistant.util")
    util.slugify = _slugify

    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.core": core,
        "homeassistant.config_entries": config_entries,
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.util": util,
    }
    sys.modules.update(modules)


def _register_package() -> None:
    """Make `entity_renamer` importable without running its __init__.

    The real __init__ pulls in the frontend/panel machinery, which these tests
    have no use for. Registering the package manually lets the modules under
    test resolve their relative imports normally.
    """
    if "entity_renamer" in sys.modules:
        return
    package = types.ModuleType("entity_renamer")
    package.__path__ = [str(COMPONENT)]
    sys.modules["entity_renamer"] = package


_install_stubs()
_register_package()


def load(module: str):
    """Import a module of the component under test."""
    return importlib.import_module(f"entity_renamer.{module}")


# ---------------------------------------------------------------------------
# Fakes shared by the test modules
# ---------------------------------------------------------------------------


class FakeEntry:
    """Stand-in for entity_registry.RegistryEntry."""

    def __init__(
        self,
        entity_id: str,
        *,
        platform: str = "demo",
        config_entry_id: str | None = None,
        device_id: str | None = None,
        disabled_by: str | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.platform = platform
        self.config_entry_id = config_entry_id
        self.device_id = device_id
        self.disabled_by = disabled_by
        self.name = None
        self.original_name = None
        self.labels: set[str] = set()
        self.categories: dict[str, str] = {}


class FakeEntityRegistry:
    def __init__(self, entries: list[FakeEntry]) -> None:
        self.entities = {e.entity_id: e for e in entries}
        self.removed: list[str] = []

    def async_get(self, entity_id: str):
        return self.entities.get(entity_id)

    def async_remove(self, entity_id: str) -> None:
        del self.entities[entity_id]
        self.removed.append(entity_id)


class FakeDeviceRegistry:
    def __init__(self, devices: dict | None = None) -> None:
        self.devices = devices or {}

    def async_get(self, device_id: str):
        return self.devices.get(device_id)


class FakeConfigEntries:
    def __init__(self, entries: dict | None = None) -> None:
        self._entries = entries or {}

    def async_get_entry(self, entry_id: str):
        return self._entries.get(entry_id)

    def async_entries(self):
        return list(self._entries.values())


class FakeState:
    def __init__(self, attributes: dict | None = None) -> None:
        self.attributes = attributes or {}


class FakeStates:
    """Models Home Assistant's three cases for a registry entry.

    `live`     -- a platform is backing it (an offline device still lands here,
                  with an `unavailable` state and no `restored` attribute).
    `restored` -- HA wrote a placeholder state because nothing is backing it.
    neither    -- no state object at all.
    """

    def __init__(
        self, live: set[str] | None = None, restored: set[str] | None = None
    ) -> None:
        self.live = live or set()
        self.restored = restored or set()

    def get(self, entity_id: str):
        if entity_id in self.restored:
            return FakeState({"restored": True})
        if entity_id in self.live:
            return FakeState({})
        return None


class FakeHass:
    def __init__(
        self,
        entries: list[FakeEntry] | list[str] | None = None,
        *,
        live: set[str] | None = None,
        restored: set[str] | None = None,
        config_entries: dict | None = None,
        devices: dict | None = None,
        state: CoreState = CoreState.running,
    ) -> None:
        normalised = [
            FakeEntry(e) if isinstance(e, str) else e for e in (entries or [])
        ]
        self.entity_registry = FakeEntityRegistry(normalised)
        self.device_registry = FakeDeviceRegistry(devices)
        self.config_entries = FakeConfigEntries(config_entries)
        self.states = FakeStates(live, restored)
        self.state = state
