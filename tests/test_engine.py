"""Tests for the scan/apply engine, especially the dry-run guarantee.

Home Assistant is stubbed by conftest rather than installed, so these run fast
while still exercising the real file-walking and rewriting code against a real
temporary filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeEntry, FakeHass, load

engine = load("engine")
Matcher = load("matcher").Matcher


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
