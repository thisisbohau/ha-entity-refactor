# Entity ID Renamer

A Home Assistant custom integration (HACS-compatible) that renames entity IDs
**and rewrites every reference to them** — automations, scripts, scenes,
dashboards, helpers, templates and the energy dashboard.

Home Assistant will happily let you rename an entity, but it does not update the
places that point at it. This integration closes that gap.

## What it does

Adds an **Entity Renamer** page to the sidebar (admin only). One list view does
everything:

- every entity in the registry, grouped by **integration → device**
- a search bar over entity ID, friendly name, device name, integration and label
- per row: current ID on the left, and editable **entity ID**, **name**,
  **labels** and **category** on the right
- **multi-select** with checkboxes — per row, per device, per integration, or all
  currently shown
- a **batch editor** for the selection (see below)
- **Preview changes** — a dry run showing every file and object that would be
  touched, with before/after lines
- **Save entity changes** — writes the registry only, without touching
  references (see below)
- **Update and replace all references** — applies the whole batch
- **Clean up orphaned entities** — removes registry entries left behind by
  deleted integrations (see below)

Everything is staged locally. The batch editor, per-row tweaks and manual edits
are all the same kind of pending change, so you can mix them freely, undo any
row, and review the lot in a single preview before anything is written.

## Batch editor

Select any number of entities, hit **Batch edit**, and apply to the entity ID,
the name, or both:

| Operation | Notes |
| --- | --- |
| Find and replace | Literal by default; optional regex (with `$1` capture groups) and ignore-case |
| Strip prefix / suffix | Only strips when it actually matches, so nothing is truncated by accident |
| Add prefix / suffix | |
| Transform | lowercase, UPPERCASE, slugify, Title Case |
| Labels | Add or remove across the whole selection; create new labels inline |
| Category | Set or clear for the whole selection |

Operations run in a fixed order — **strip → find/replace → transform → add** —
so "strip `old_` and add `new_`" gives `new_lamp`, not `new_old_lamp`. A live
preview inside the dialog shows the resulting IDs and names before you stage
anything.

Entity ID operations apply to the part **after** the domain, so a batch edit can
never break `sensor.` into something invalid. `slugify` handles German text the
way HA does (`Übergröße` → `ubergrosse`).

### Names, labels and categories

These are entity registry metadata — nothing outside the registry references
them, so they need no file rewriting. They still travel through the same preview
and the same single Apply.

- **Name** is the friendly-name override. Clearing the box removes your override,
  so the name falls back to whatever the integration supplied.
- **Labels** are HA labels ("tags"). New ones can be created from the picker.
- **Category** uses HA's category registry, which is scoped (automation, script,
  scene, helpers) — the dropdown shows the scope next to each name. Setting a
  category replaces any existing one.
- `entity_category` (Config / Diagnostic) is deliberately **not** editable: it is
  integration-defined behaviour, not user metadata.

## Save entity changes (registry only)

The **Save entity changes** button writes the entity registry and stops there —
no YAML, dashboards, helpers or energy preferences are touched, and nothing is
reloaded.

For **names, labels and categories** this is the natural choice: nothing outside
the registry refers to them, so there is nothing to rewrite.

For an **entity ID rename** it is the exact footgun this integration exists to
prevent — automations, scripts, dashboards and templates pointing at the old ID
will silently stop working. The panel therefore shows a red confirmation listing
every affected rename before it proceeds. Use it only when you know nothing
refers to those entities.

## Cleaning up orphaned entities

Deleted an integration and its entities are still cluttering every picker (and
holding on to the IDs you want)? The toolbar shows **Clean up N orphaned…**
whenever such entries exist.

An entity is treated as orphaned when no integration is backing it. Home
Assistant writes an `unavailable` state with a `restored: true` attribute for
exactly these, which is what the detection keys on.

Deliberately **not** listed:

- **Disabled entities** — they have no state by design; deleting them would
  destroy a decision you made on purpose.
- **Offline devices** — an unavailable-but-backed entity still has a real state,
  so a Shelly that is merely unplugged is never offered for deletion.
- **Anything, during startup** — before startup completes almost nothing has a
  state, so the scan refuses to run and says so.

Safety: a `.storage` backup is written first, and every entity is **re-checked
server-side at deletion time**. The panel's list is treated as a request, not an
instruction — if an entity has come back to life since the list was built, it is
skipped and reported rather than deleted. Removal cannot be undone from the
panel; recorder history is not deleted but becomes unreachable.

## What gets updated

| Target | How |
| --- | --- |
| Entity registry (ID, name, labels, category) | `entity_registry.async_update_entity` — an ID rename also migrates long-term statistics |
| `/config/**.yaml` (`automations.yaml`, `scripts.yaml`, `scenes.yaml`, `configuration.yaml`, packages, `customize.yaml`, …) | Text replace, preserving comments and formatting |
| UI helpers (template, group, min/max, utility meter, threshold, derivative, …) | `config_entries.async_update_entry` |
| Lovelace storage dashboards | `lovelace/config/save` websocket API |
| Energy dashboard | Energy manager API |

After applying, `homeassistant.reload_all` and `homeassistant.reload_core_config`
run automatically, so most changes take effect without a restart. On cores
without `reload_all`, it falls back to reloading `automation`, `script`, `scene`
and `template` individually.

### Deliberately not touched

`.storage` files are **never** edited directly. Home Assistant keeps those
mirrored in memory and would overwrite hand-edits on its next save. Everything
storage-backed goes through a public API instead.

These directories under `/config` are skipped entirely, so nothing in them is
read or rewritten: `.storage`, any other dot-directory, `custom_components`,
`blueprints`, `www`, `deps`, `backups`, `tts`, `image`, and the integration's own
backup folder. `secrets.yaml` and `known_devices.yaml` are skipped by name.

Not covered, and worth checking by hand after a rename:

- YAML-mode Lovelace dashboards (`ui-lovelace.yaml` **is** covered as a YAML
  file; other YAML dashboards are covered only if they live under `/config`)
- Cloud/Alexa/Google entity aliases and exposure settings
- `person` entity `device_trackers`
- Blueprints (skipped — they use inputs rather than hard-coded entity IDs)
- Anything outside `/config` (Node-RED, AppDaemon, ESPHome device configs)

The preview lists any dashboard it could not read so you know where to look.

### Side effect worth knowing

Config entries are scanned for entity ID references, which is what catches
helpers. If a *regular* integration's config entry happens to contain one, it is
updated too — and Home Assistant reloads a config entry when it changes. The
preview names every config entry it would touch, so you will see it coming.

## Safety

- **Dry run first.** The preview and the apply run the same scan; the preview
  just doesn't write.
- **Backup on every apply.** A timestamped `tar.gz` of `.storage` plus every
  in-scope YAML file lands in `/config/entity_renamer_backups/`. The 20 most
  recent are kept.
- **Validation before anything is written.** A batch is rejected as a whole if
  any new ID is malformed, changes domain (HA does not allow this), collides
  with an existing entity, duplicates another target in the batch, or would
  cascade into another rename in the same batch. Validation uses Home
  Assistant's own `valid_entity_id` rule, and the panel enforces the identical
  rule client-side so Apply is never offered for an ID the server will refuse.
- Reference matching is boundary-aware: renaming `sensor.old` leaves
  `sensor.old_2`, `sensor.older` and `binary_sensor.old` alone.
- **Chained renames are refused, not guessed.** `a → b` while `b → c` needs a
  specific ordering (and a temporary name if the renames form a cycle), so the
  batch is rejected with an explanation. Apply them as two runs.
- **Partial failures are reported honestly.** If the registry rename succeeds
  but, say, a YAML file is read-only, the result says changes *were* written and
  lists what failed. It never claims "nothing was changed" when something was.

Restoring is manual and intentionally so:

```bash
cd /config
tar xzf entity_renamer_backups/entity_renamer-20260719-141530.tar.gz
```

then restart Home Assistant.

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/thisisbohau/ha-entity-refactor`, category
   **Integration**
3. Install **Entity ID Renamer**, restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Entity ID Renamer**

### Manual

Copy `custom_components/entity_renamer/` into your `/config/custom_components/`,
restart, then add the integration.

## Development

The pieces that could silently corrupt data are tested without needing Home
Assistant or any npm install:

```bash
python3 -m pytest tests/ -q          # matcher, file scoping, dry-run, validation
node tests/test_batch_ops.mjs        # batch editor operations, ID rule, categories
```

- `tests/test_matcher.py` — reference matching boundary cases.
- `tests/test_engine.py` — proves the dry run writes nothing (byte-compares a
  temporary `/config` tree before and after), that excluded directories are
  never touched, and that validation rejects what it should. Home Assistant is
  stubbed rather than installed.
- `tests/test_orphans.py` — orphan detection and removal, weighted towards the
  entities that must *never* be deleted (disabled, offline, live, mid-startup).
- `tests/test_batch_ops.mjs` — slices the pure-function section out of the real
  panel source and evaluates it, so it exercises the shipped code, not a copy.

Both suites run in CI along with `hassfest` and HACS validation
(`.github/workflows/validate.yml`).

## License

MIT — see [LICENSE](LICENSE).
