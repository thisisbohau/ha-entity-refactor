"""Tests for orphan detection and removal.

This is the only destructive feature in the integration, so the cases that must
NOT be deleted get more attention than the ones that should.
"""

from __future__ import annotations

from conftest import (
    ConfigEntryState,
    CoreState,
    FakeEntry,
    FakeHass,
    load,
)

orphans = load("orphans")


class FakeConfigEntry:
    def __init__(self, entry_id: str, title: str, state: ConfigEntryState) -> None:
        self.entry_id = entry_id
        self.title = title
        self.state = state


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_restored_placeholder_state_is_an_orphan():
    """The realistic case: HA writes an `unavailable` state with
    `restored: True` for every registry entry no platform is backing."""
    hass = FakeHass([FakeEntry("sensor.ghost")], restored={"sensor.ghost"})
    found, warnings = orphans.find_orphans(hass)

    assert [o["entity_id"] for o in found] == ["sensor.ghost"]
    assert warnings == []


def test_entity_without_any_state_is_an_orphan():
    hass = FakeHass([FakeEntry("sensor.ghost")], live=set())
    found, _ = orphans.find_orphans(hass)
    assert [o["entity_id"] for o in found] == ["sensor.ghost"]


def test_live_entity_is_not_an_orphan():
    hass = FakeHass([FakeEntry("sensor.alive")], live={"sensor.alive"})
    found, _ = orphans.find_orphans(hass)
    assert found == []


def test_offline_device_is_not_an_orphan():
    """An unavailable-but-backed entity has a real state and must never be
    offered for deletion just because the device is off."""
    hass = FakeHass([FakeEntry("sensor.offline_shelly")], live={"sensor.offline_shelly"})
    found, _ = orphans.find_orphans(hass)
    assert found == []


def test_disabled_entity_is_never_an_orphan():
    """A disabled entity has no state by design. Deleting it would destroy a
    deliberate user choice."""
    hass = FakeHass(
        [FakeEntry("sensor.off", disabled_by="user")], restored={"sensor.off"}
    )
    found, _ = orphans.find_orphans(hass)
    assert found == []


def test_nothing_is_reported_before_startup_completes():
    """During startup almost nothing has a state; every entity would look
    orphaned."""
    hass = FakeHass(
        [FakeEntry("sensor.a"), FakeEntry("sensor.b")],
        live=set(),
        state=CoreState.starting,
    )
    found, warnings = orphans.find_orphans(hass)

    assert found == []
    assert warnings and "starting up" in warnings[0]


def test_reason_when_config_entry_is_gone():
    hass = FakeHass(
        [FakeEntry("sensor.ghost", config_entry_id="missing")],
        live=set(),
        config_entries={},
    )
    found, _ = orphans.find_orphans(hass)
    assert found[0]["reason"] == orphans.REASON_ENTRY_GONE


def test_reason_when_config_entry_is_not_loaded():
    hass = FakeHass(
        [FakeEntry("sensor.ghost", config_entry_id="e1")],
        live=set(),
        config_entries={
            "e1": FakeConfigEntry("e1", "Broken Thing", ConfigEntryState.SETUP_ERROR)
        },
    )
    found, _ = orphans.find_orphans(hass)
    assert orphans.REASON_ENTRY_NOT_LOADED in found[0]["reason"]
    assert "Broken Thing" in found[0]["reason"]


def test_reason_for_a_removed_yaml_platform():
    hass = FakeHass([FakeEntry("sensor.ghost", config_entry_id=None)], live=set())
    found, _ = orphans.find_orphans(hass)
    assert found[0]["reason"] == orphans.REASON_NO_PROVIDER


def test_results_are_sorted_by_integration_then_id():
    hass = FakeHass(
        [
            FakeEntry("sensor.z", platform="alpha"),
            FakeEntry("sensor.a", platform="zulu"),
            FakeEntry("sensor.b", platform="alpha"),
        ],
        live=set(),
    )
    found, _ = orphans.find_orphans(hass)
    assert [o["entity_id"] for o in found] == ["sensor.b", "sensor.z", "sensor.a"]


# ---------------------------------------------------------------------------
# Removal -- the safety net
# ---------------------------------------------------------------------------


def test_removes_an_orphan():
    hass = FakeHass([FakeEntry("sensor.ghost")], restored={"sensor.ghost"})
    removed, errors = orphans.remove_orphans(hass, ["sensor.ghost"])

    assert removed == ["sensor.ghost"]
    assert errors == []
    assert hass.entity_registry.async_get("sensor.ghost") is None


def test_refuses_to_remove_a_live_entity():
    """The panel's list can be stale. An entity that came back must survive
    even if the client asks for its deletion."""
    hass = FakeHass([FakeEntry("sensor.alive")], live={"sensor.alive"})
    removed, errors = orphans.remove_orphans(hass, ["sensor.alive"])

    assert removed == []
    assert any("provided again" in e for e in errors)
    assert hass.entity_registry.async_get("sensor.alive") is not None


def test_refuses_to_remove_a_disabled_entity():
    hass = FakeHass([FakeEntry("sensor.off", disabled_by="user")], live=set())
    removed, errors = orphans.remove_orphans(hass, ["sensor.off"])

    assert removed == []
    assert errors
    assert hass.entity_registry.async_get("sensor.off") is not None


def test_removes_nothing_before_startup_completes():
    hass = FakeHass([FakeEntry("sensor.ghost")], live=set(), state=CoreState.starting)
    removed, errors = orphans.remove_orphans(hass, ["sensor.ghost"])

    assert removed == []
    assert errors
    assert hass.entity_registry.async_get("sensor.ghost") is not None


def test_unknown_entity_is_reported_not_crashed():
    hass = FakeHass([], live=set())
    removed, errors = orphans.remove_orphans(hass, ["sensor.nope"])

    assert removed == []
    assert any("no longer in the registry" in e for e in errors)


def test_mixed_batch_removes_only_the_orphans():
    hass = FakeHass(
        [
            FakeEntry("sensor.ghost"),
            FakeEntry("sensor.alive"),
            FakeEntry("sensor.off", disabled_by="user"),
        ],
        live={"sensor.alive"},
        restored={"sensor.ghost", "sensor.off"},
    )
    removed, errors = orphans.remove_orphans(
        hass, ["sensor.ghost", "sensor.alive", "sensor.off"]
    )

    assert removed == ["sensor.ghost"]
    assert len(errors) == 2
    assert hass.entity_registry.async_get("sensor.alive") is not None
    assert hass.entity_registry.async_get("sensor.off") is not None
