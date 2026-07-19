"""Entity ID matching and replacement primitives.

All rewriting in this integration goes through :class:`Matcher`. It compiles a
single alternation over every old entity ID in the batch so that a rename batch
is applied in one pass -- chained renames (``a -> b`` and ``b -> c``) can never
cascade into each other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# An entity ID reference is only a match when it is not glued to surrounding
# word characters. The trailing guard is `[\w]` rather than `[\w.]` on purpose:
# `sensor.old.state` in a template is a genuine reference to `sensor.old`,
# while `sensor.old_2` is a different entity and must not match.
_LEAD = r"(?<![\w.])"
_TRAIL = r"(?![\w])"

# Templates also address entities through the state machine object, e.g.
# `states.sensor.old.state`. The optional `states.` prefix is captured so it can
# be preserved in the replacement.
_STATES_PREFIX = r"(states\.)?"


@dataclass(frozen=True)
class Occurrence:
    """A single replaced reference, kept for the dry-run preview."""

    line: int
    before: str
    after: str


class Matcher:
    """Applies a batch of entity ID renames to text and to JSON-like objects."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = dict(mapping)
        if self.mapping:
            # Longest first so `sensor.foo_bar` wins over `sensor.foo` when both
            # are being renamed and one is a prefix of the other.
            alternation = "|".join(
                re.escape(old)
                for old in sorted(self.mapping, key=len, reverse=True)
            )
            self._pattern: re.Pattern[str] | None = re.compile(
                f"{_LEAD}{_STATES_PREFIX}({alternation}){_TRAIL}"
            )
        else:
            self._pattern = None

    def _sub(self, match: re.Match[str]) -> str:
        return (match.group(1) or "") + self.mapping[match.group(2)]

    def replace_text(self, text: str) -> tuple[str, list[Occurrence]]:
        """Replace every reference in ``text``.

        Returns the new text and one :class:`Occurrence` per changed line, so a
        preview can show before/after without diffing whole files.
        """
        if self._pattern is None or not self._pattern.search(text):
            return text, []

        occurrences: list[Occurrence] = []
        out_lines: list[str] = []
        for number, line in enumerate(text.splitlines(keepends=True), start=1):
            new_line = self._pattern.sub(self._sub, line)
            if new_line != line:
                occurrences.append(
                    Occurrence(
                        line=number,
                        before=line.strip("\r\n"),
                        after=new_line.strip("\r\n"),
                    )
                )
            out_lines.append(new_line)
        return "".join(out_lines), occurrences

    def replace_object(self, obj: Any) -> tuple[Any, int]:
        """Recursively replace references inside a JSON-like structure.

        Dictionary keys are rewritten too -- Lovelace and helper options both
        use entity IDs as keys in places.
        """
        if self._pattern is None:
            return obj, 0

        if isinstance(obj, str):
            new = self._pattern.sub(self._sub, obj)
            return new, int(new != obj)

        if isinstance(obj, list):
            count = 0
            result = []
            for item in obj:
                new_item, hits = self.replace_object(item)
                count += hits
                result.append(new_item)
            return result, count

        if isinstance(obj, dict):
            count = 0
            result = {}
            for key, value in obj.items():
                new_key = key
                if isinstance(key, str):
                    new_key, hits = self.replace_object(key)
                    count += hits
                new_value, hits = self.replace_object(value)
                count += hits
                result[new_key] = new_value
            return result, count

        return obj, 0

    def find_in_object(self, obj: Any) -> int:
        """Count references without building a replacement copy."""
        _, count = self.replace_object(obj)
        return count


def summarise_object_change(before: Any, after: Any, limit: int = 5) -> list[Occurrence]:
    """Build preview rows for an object rewrite by walking both trees in step."""
    rows: list[Occurrence] = []

    def walk(old: Any, new: Any, path: str) -> None:
        if len(rows) >= limit:
            return
        if isinstance(old, str) and isinstance(new, str):
            if old != new:
                rows.append(Occurrence(line=0, before=f"{path}: {old}", after=f"{path}: {new}"))
            return
        if isinstance(old, list) and isinstance(new, list):
            for index, (o, n) in enumerate(zip(old, new)):
                walk(o, n, f"{path}[{index}]")
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in old:
                if key in new:
                    walk(old[key], new[key], f"{path}.{key}" if path else str(key))
            return

    walk(before, after, "")
    return rows


def chain_conflicts(renames: Iterable[tuple[str, str]]) -> list[str]:
    """Report renames whose target is another rename's source, or a duplicate."""
    pairs = list(renames)
    sources = {old for old, _ in pairs}
    problems: list[str] = []

    seen_targets: dict[str, str] = {}
    for old, new in pairs:
        if new in sources and new != old:
            problems.append(
                f"'{old}' would be renamed to '{new}', but '{new}' is itself being "
                "renamed in this batch. Split these into two runs."
            )
        if new in seen_targets:
            problems.append(
                f"'{old}' and '{seen_targets[new]}' would both become '{new}'."
            )
        seen_targets[new] = old

    return problems
