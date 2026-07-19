"""Tests for the reference matcher.

This is the only code in the integration that rewrites the user's files, so the
boundary cases (prefix collisions, `states.` access, chained renames) are pinned
down here. The module imports nothing from Home Assistant, so these run with a
bare `python3 -m pytest tests/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "entity_renamer"))

from matcher import Matcher, chain_conflicts  # noqa: E402


def replace(text: str, mapping: dict[str, str]) -> str:
    return Matcher(mapping).replace_text(text)[0]


def test_simple_reference():
    assert replace("entity_id: sensor.old", {"sensor.old": "sensor.new"}) == (
        "entity_id: sensor.new"
    )


def test_does_not_touch_longer_ids():
    """`sensor.old_2` is a different entity and must survive untouched."""
    text = "a: sensor.old\nb: sensor.old_2\nc: sensor.older\n"
    out = replace(text, {"sensor.old": "sensor.new"})
    assert out == "a: sensor.new\nb: sensor.old_2\nc: sensor.older\n"


def test_does_not_touch_same_object_id_in_other_domain():
    out = replace("x: binary_sensor.old", {"sensor.old": "sensor.new"})
    assert out == "x: binary_sensor.old"


def test_template_states_function():
    out = replace(
        "value_template: \"{{ states('sensor.old') | float }}\"",
        {"sensor.old": "sensor.new"},
    )
    assert "states('sensor.new')" in out


def test_states_object_access_keeps_prefix():
    out = replace("{{ states.sensor.old.state }}", {"sensor.old": "sensor.new"})
    assert out == "{{ states.sensor.new.state }}"


def test_attribute_access_after_id():
    out = replace("{{ states('sensor.old') }} sensor.old.state", {"sensor.old": "sensor.new"})
    assert out == "{{ states('sensor.new') }} sensor.new.state"


def test_batch_is_single_pass_no_cascade():
    """a->b and b->c applied together must not turn a into c."""
    mapping = {"sensor.a": "sensor.b", "sensor.b": "sensor.c"}
    assert replace("1: sensor.a\n2: sensor.b", mapping) == "1: sensor.b\n2: sensor.c"


def test_longest_match_wins():
    mapping = {"sensor.foo": "sensor.x", "sensor.foo_bar": "sensor.y"}
    assert replace("sensor.foo_bar", mapping) == "sensor.y"
    assert replace("sensor.foo", mapping) == "sensor.x"


def test_comments_and_formatting_preserved():
    text = "# keep me\nentity_id: sensor.old   # trailing note\n\n"
    out = replace(text, {"sensor.old": "sensor.new"})
    assert out == "# keep me\nentity_id: sensor.new   # trailing note\n\n"


def test_occurrence_reporting():
    _, occurrences = Matcher({"sensor.old": "sensor.new"}).replace_text(
        "a\nentity_id: sensor.old\nb\n"
    )
    assert len(occurrences) == 1
    assert occurrences[0].line == 2
    assert occurrences[0].before == "entity_id: sensor.old"
    assert occurrences[0].after == "entity_id: sensor.new"


def test_object_replacement_including_keys():
    matcher = Matcher({"sensor.old": "sensor.new"})
    obj = {
        "cards": [{"entity": "sensor.old", "name": "untouched"}],
        "overrides": {"sensor.old": {"note": "{{ states('sensor.old') }}"}},
    }
    new, count = matcher.replace_object(obj)
    assert count == 3
    assert new["cards"][0]["entity"] == "sensor.new"
    assert "sensor.new" in new["overrides"]
    assert new["overrides"]["sensor.new"]["note"] == "{{ states('sensor.new') }}"


def test_object_replacement_leaves_non_strings():
    matcher = Matcher({"sensor.old": "sensor.new"})
    new, count = matcher.replace_object({"n": 5, "f": 1.5, "b": True, "z": None})
    assert count == 0
    assert new == {"n": 5, "f": 1.5, "b": True, "z": None}


def test_empty_mapping_is_a_noop():
    assert replace("sensor.old", {}) == "sensor.old"


def test_chain_conflicts_detects_cascade():
    problems = chain_conflicts([("sensor.a", "sensor.b"), ("sensor.b", "sensor.c")])
    assert any("split these into two runs" in p.lower() for p in problems)


def test_chain_conflicts_detects_duplicate_target():
    problems = chain_conflicts([("sensor.a", "sensor.z"), ("sensor.b", "sensor.z")])
    assert any("would both become" in p for p in problems)


def test_chain_conflicts_clean_batch():
    assert chain_conflicts([("sensor.a", "sensor.x"), ("sensor.b", "sensor.y")]) == []
