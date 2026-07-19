"""Tests for the scan/apply engine, especially the dry-run guarantee.

Home Assistant is not a test dependency here. `engine.py` only touches a handful
of HA symbols at import time, so those are stubbed below with faithful
implementations (the entity ID validator is HA's real regex). That keeps the
suite fast while still exercising the real file-walking and rewriting code
against a real temporary filesystem.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "entity_renamer"


# ---------------------------------------------------------------------------
# Minimal Home Assistant stubs, installed before importing the component.
# ---------------------------------------------------------------------------

_VALID_ENTITY_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")


def _install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.valid_entity_id = lambda value: _VALID_ENTITY_ID.match(value) is not None
    core.callback = lambda func: func

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object

    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: hass.entity_registry

    util = types.ModuleType("homeassistant.util")

    def slugify(value: str, *, separator: str = "_") -> str:
        text = re.sub(r"[^a-z0-9]+", separator, str(value).lower())
        return re.sub(f"{separator}+", separator, text).strip(separator)

    util.slugify = slugify

    for name, module in {
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.config_entries": config_entries,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.util": util,
    }.items():
        sys.modules[name] = module


_install_stubs()

# Register `entity_renamer` as a package without running its __init__, which
# would pull in the frontend/panel machinery this test has no use for. The
# modules under test then resolve their relative imports normally.
_package = types.ModuleType("entity_renamer")
_package.__path__ = [str(COMPONENT)]
sys.modules["entity_renamer"] = _package

import importlib  # noqa: E402

engine = importlib.import_module("entity_renamer.engine")
Matcher = importlib.import_module("entity_renamer.matcher").Matcher


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEntry:
    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self.name = None
        self.original_name = None
        self.labels: set[str] = set()
        self.categories: dict[str, str] = {}


class FakeEntityRegistry:
    def __init__(self, entity_ids: list[str]) -> None:
        self.entities = {eid: FakeEntry(eid) for eid in entity_ids}

    def async_get(self, entity_id: str) -> FakeEntry | None:
        return self.entities.get(entity_id)


class FakeHass:
    def __init__(self, entity_ids: list[str]) -> None:
        self.entity_registry = FakeEntityRegistry(entity_ids)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A miniature /config tree covering the interesting cases."""
    (tmp_path / "automations.yaml").write_text(
        "- alias: Test\n"
        "  trigger:\n"
        "    - platform: state\n"
        "      entity_id: sensor.old   # keep this comment\n"
        "  action:\n"
        "    - service: light.turn_on\n"
        "      target: {entity_id: light.other}\n",
        encoding="utf-8",
    )
    (tmp_path / "configuration.yaml").write_text(
        "template:\n  - sensor:\n      state: \"{{ states('sensor.old') }}\"\n",
        encoding="utf-8",
    )
    (tmp_path / "untouched.yaml").write_text("foo: bar\n", encoding="utf-8")

    # Must never be read or written.
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "core.entity_registry.yaml").write_text("entity_id: sensor.old\n", encoding="utf-8")

    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("token: sensor.old\n", encoding="utf-8")

    custom = tmp_path / "custom_components" / "thing"
    custom.mkdir(parents=True)
    (custom / "x.yaml").write_text("entity_id: sensor.old\n", encoding="utf-8")

    backups = tmp_path / "entity_renamer_backups"
    backups.mkdir()
    (backups / "old.yaml").write_text("entity_id: sensor.old\n", encoding="utf-8")

    return tmp_path


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def test_iter_yaml_files_scope(config_dir: Path):
    found = {p.name for p in engine._iter_yaml_files(config_dir)}
    assert found == {"automations.yaml", "configuration.yaml", "untouched.yaml"}


def test_iter_yaml_files_excludes_dotted_and_listed_dirs(config_dir: Path):
    paths = [str(p) for p in engine._iter_yaml_files(config_dir)]
    for forbidden in (".storage", "custom_components", "entity_renamer_backups", "secrets.yaml"):
        assert not any(forbidden in p for p in paths), forbidden


# ---------------------------------------------------------------------------
# The dry-run guarantee
# ---------------------------------------------------------------------------


def test_scan_yaml_dry_run_writes_nothing(config_dir: Path):
    before = snapshot(config_dir)
    matcher = Matcher({"sensor.old": "sensor.new"})

    changes, errors, _ = engine._scan_yaml(config_dir, matcher, False)

    assert snapshot(config_dir) == before, "dry run modified files on disk"
    assert not errors
    # It still has to *report* the changes it would make.
    assert {c.target for c in changes} == {"automations.yaml", "configuration.yaml"}
    assert sum(c.count for c in changes) == 2


def test_scan_yaml_write_mode_actually_writes(config_dir: Path):
    matcher = Matcher({"sensor.old": "sensor.new"})
    engine._scan_yaml(config_dir, matcher, True)

    automations = (config_dir / "automations.yaml").read_text(encoding="utf-8")
    assert "sensor.new" in automations
    assert "sensor.old" not in automations
    assert "# keep this comment" in automations, "comments must survive"
    assert "light.other" in automations, "unrelated entities must be untouched"

    config = (config_dir / "configuration.yaml").read_text(encoding="utf-8")
    assert "states('sensor.new')" in config

    assert (config_dir / "untouched.yaml").read_text(encoding="utf-8") == "foo: bar\n"


def test_write_mode_never_touches_excluded_files(config_dir: Path):
    engine._scan_yaml(config_dir, Matcher({"sensor.old": "sensor.new"}), True)

    assert "sensor.old" in (config_dir / "secrets.yaml").read_text(encoding="utf-8")
    assert "sensor.old" in (
        config_dir / ".storage" / "core.entity_registry.yaml"
    ).read_text(encoding="utf-8")
    assert "sensor.old" in (
        config_dir / "custom_components" / "thing" / "x.yaml"
    ).read_text(encoding="utf-8")


def test_replace_object_does_not_mutate_input():
    """Dashboards and config entries are scanned this way; mutation would make
    a preview destructive even though nothing is saved."""
    original = {"cards": [{"entity": "sensor.old"}], "title": "keep"}
    reference = {"cards": [{"entity": "sensor.old"}], "title": "keep"}

    new, count = Matcher({"sensor.old": "sensor.new"}).replace_object(original)

    assert original == reference, "input object was mutated"
    assert new["cards"][0]["entity"] == "sensor.new"
    assert count == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_accepts_a_clean_rename():
    hass = FakeHass(["sensor.old"])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.old", "new_entity_id": "sensor.new"}]
    )
    assert mapping == {"sensor.old": "sensor.new"}
    assert errors == []


def test_validate_rejects_domain_change():
    hass = FakeHass(["sensor.old"])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.old", "new_entity_id": "binary_sensor.old"}]
    )
    assert mapping == {}
    assert any("does not allow" in e for e in errors)


def test_validate_rejects_collision_with_existing_entity():
    hass = FakeHass(["sensor.old", "sensor.taken"])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.old", "new_entity_id": "sensor.taken"}]
    )
    assert mapping == {}
    assert any("already taken" in e for e in errors)


@pytest.mark.parametrize(
    "bad", ["sensor.Bad", "sensor.bad id", "sensor._bad", "sensor.bad_", "sensor.a__b", "nodomain"]
)
def test_validate_rejects_malformed_ids(bad: str):
    hass = FakeHass(["sensor.old"])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.old", "new_entity_id": bad}]
    )
    assert mapping == {}
    assert errors


def test_validate_rejects_unknown_entity():
    hass = FakeHass([])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.ghost", "new_entity_id": "sensor.new"}]
    )
    assert mapping == {}
    assert any("not in the entity registry" in e for e in errors)


def test_validate_rejects_chained_rename_with_actionable_advice():
    """a -> b while b -> c needs ordering, so it is refused -- but the message
    must say why, not just 'already taken'."""
    hass = FakeHass(["sensor.a", "sensor.b"])
    mapping, errors = engine.validate(
        hass,
        [
            {"old_entity_id": "sensor.a", "new_entity_id": "sensor.b"},
            {"old_entity_id": "sensor.b", "new_entity_id": "sensor.c"},
        ],
    )
    assert "sensor.a" not in mapping
    assert any("itself being renamed in this batch" in e for e in errors)


def test_validate_rejects_a_rename_cycle():
    hass = FakeHass(["sensor.a", "sensor.b"])
    _, errors = engine.validate(
        hass,
        [
            {"old_entity_id": "sensor.a", "new_entity_id": "sensor.b"},
            {"old_entity_id": "sensor.b", "new_entity_id": "sensor.a"},
        ],
    )
    assert len(errors) == 2, "both directions of a swap must be refused"


def test_validate_ignores_metadata_only_items():
    """An item with no new_entity_id is a name/label edit, not a rename."""
    hass = FakeHass(["sensor.old"])
    mapping, errors = engine.validate(
        hass, [{"old_entity_id": "sensor.old", "new_name": "Kitchen"}]
    )
    assert mapping == {}
    assert errors == []
