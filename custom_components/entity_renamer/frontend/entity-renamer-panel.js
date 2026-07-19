/**
 * Entity Renamer panel.
 *
 * Deliberately dependency-free vanilla custom element: a custom panel cannot
 * reliably import Lit from Home Assistant's own bundle, and pulling it from a
 * CDN would break every offline install. Everything below is plain DOM.
 *
 * Editing model: every control writes into `_edits`, a per-entity override map.
 * Nothing is sent to Home Assistant until Preview or Apply, so the batch editor,
 * per-row edits and manual tweaks are all the same kind of staged change and can
 * be freely mixed and undone.
 */

const DEFAULT_DASHBOARD_KEY = "__default__";
const MAX_RENDERED_ROWS = 400;
const BATCH_PREVIEW_ROWS = 15;

const css = `
  :host { display: block; height: 100%; background: var(--primary-background-color); }
  .shell { display: flex; flex-direction: column; height: 100%; }

  header {
    display: flex; align-items: center; gap: 8px;
    height: 56px; padding: 0 16px; box-sizing: border-box;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
    font-size: 20px; font-weight: 400; flex: 0 0 auto;
  }
  header .title { flex: 1; }
  .menu-btn {
    background: none; border: none; color: inherit; cursor: pointer;
    font-size: 22px; line-height: 1; padding: 8px; border-radius: 50%;
  }
  .menu-btn:hover { background: rgba(255,255,255,.12); }

  .toolbar {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    padding: 10px 16px; flex: 0 0 auto;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .search { flex: 1 1 260px; min-width: 180px; }
  .hint { color: var(--secondary-text-color); font-size: 13px; }

  .selbar {
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 10px 16px; flex: 0 0 auto;
    background: var(--primary-color); color: var(--text-primary-color, #fff);
  }
  .selbar .spacer { flex: 1; }
  .selbar button {
    background: rgba(255,255,255,.16); color: inherit; border: none;
    border-radius: 6px; padding: 7px 12px; cursor: pointer;
    font-size: 13px; font-family: inherit; font-weight: 500;
  }
  .selbar button:hover { background: rgba(255,255,255,.28); }
  .selbar button.strong { background: #fff; color: var(--primary-color); }

  input[type="text"], input[type="search"], select {
    width: 100%; box-sizing: border-box;
    padding: 7px 9px; border-radius: 6px;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    font-family: inherit; font-size: 13px;
  }
  input:focus, select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  label.cb { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }

  .list { flex: 1 1 auto; overflow-y: auto; padding: 8px 16px 24px; }

  .group { margin-bottom: 8px; border-radius: 8px; overflow: hidden;
           background: var(--card-background-color, #fff);
           box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12)); }
  .group > .head {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; user-select: none; color: var(--primary-text-color); font-weight: 500;
  }
  .group > .head .grow { flex: 1; cursor: pointer; display: flex; align-items: center; gap: 10px; }
  .group > .head:hover { background: var(--secondary-background-color, #f4f4f4); }
  .chev { width: 14px; display: inline-block; transition: transform .15s; color: var(--secondary-text-color); }
  .group.open .chev { transform: rotate(90deg); }
  .count { color: var(--secondary-text-color); font-weight: 400; font-size: 13px; }
  .badge { background: var(--primary-color); color: #fff; border-radius: 10px;
           padding: 1px 8px; font-size: 12px; font-weight: 500; }

  .device { padding: 2px 0 8px; }
  .device > .dhead {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 14px 4px 30px; font-size: 13px; font-weight: 500;
    color: var(--secondary-text-color);
  }
  .device > .dhead .area { font-weight: 400; opacity: .8; }

  .row { padding: 6px 14px 8px 30px; border-left: 3px solid transparent; }
  .row.dirty { background: var(--secondary-background-color, rgba(3,169,244,.07));
               border-left-color: var(--primary-color); }
  .row.sel { background: rgba(3,169,244,.10); }
  .row .line1 { display: grid; grid-template-columns: 22px 1fr 16px 1fr 30px; gap: 8px; align-items: center; }
  .row .meta  { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 8px; margin: 6px 0 0 30px; }
  @media (max-width: 900px) {
    .row .meta { grid-template-columns: 1fr; margin-left: 0; }
    .row .line1 { grid-template-columns: 22px 1fr 30px; }
    .row .line1 .arrow { display: none; }
  }
  .cur {
    font-family: var(--code-font-family, ui-monospace, Menlo, Consolas, monospace);
    font-size: 13px; color: var(--secondary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .arrow { text-align: center; color: var(--secondary-text-color); }
  .row input.id { font-family: var(--code-font-family, ui-monospace, Menlo, Consolas, monospace); }
  .row input.invalid { border-color: var(--error-color, #db4437); }
  .field { display: flex; flex-direction: column; gap: 3px; }
  .field > .lab { font-size: 11px; text-transform: uppercase; letter-spacing: .4px;
                  color: var(--secondary-text-color); }
  .reset { background: none; border: none; cursor: pointer; color: var(--secondary-text-color);
           font-size: 16px; padding: 4px; border-radius: 50%; visibility: hidden; }
  .row.dirty .reset { visibility: visible; }
  .reset:hover { background: var(--secondary-background-color); }

  .chipbtn {
    display: flex; flex-wrap: wrap; gap: 4px; align-items: center; min-height: 31px;
    padding: 4px 8px; border-radius: 6px; cursor: pointer; text-align: left;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    font-family: inherit; font-size: 13px; width: 100%; box-sizing: border-box;
  }
  .chip { background: var(--secondary-background-color, #eee); border-radius: 10px;
          padding: 1px 8px; font-size: 12px; white-space: nowrap; }
  .chipbtn .ph { color: var(--secondary-text-color); }

  .popover {
    position: fixed; z-index: 20; min-width: 230px; max-height: 320px; overflow-y: auto;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,.3); padding: 8px;
  }
  .popover .opt { display: flex; align-items: center; gap: 8px; padding: 6px 6px;
                  border-radius: 6px; cursor: pointer; font-size: 13px; }
  .popover .opt:hover { background: var(--secondary-background-color, #f2f2f2); }
  .popover .newrow { display: flex; gap: 6px; padding-top: 8px; margin-top: 6px;
                     border-top: 1px solid var(--divider-color); }

  .footer {
    flex: 0 0 auto; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    padding: 12px 16px; background: var(--card-background-color, #fff);
    border-top: 1px solid var(--divider-color, #e0e0e0);
    box-shadow: 0 -2px 8px rgba(0,0,0,.08);
  }
  .footer .spacer { flex: 1; }

  button.action {
    border: none; border-radius: 6px; padding: 10px 16px; cursor: pointer;
    font-size: 14px; font-weight: 500; font-family: inherit;
    background: var(--primary-color); color: var(--text-primary-color, #fff);
  }
  button.action.secondary { background: transparent; color: var(--primary-color);
                            border: 1px solid var(--primary-color); }
  button.action[disabled] { opacity: .45; cursor: not-allowed; }

  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 15;
             display: flex; align-items: center; justify-content: center; padding: 16px; }
  .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color);
            border-radius: 10px; max-width: 920px; width: 100%; max-height: 88vh;
            display: flex; flex-direction: column; overflow: hidden; }
  .dialog h2 { margin: 0; padding: 18px 20px 8px; font-size: 20px; font-weight: 500; }
  .dialog .body { padding: 0 20px 12px; overflow-y: auto; flex: 1; }
  .dialog .foot { display: flex; gap: 10px; justify-content: flex-end;
                  padding: 12px 20px 18px; border-top: 1px solid var(--divider-color); }

  fieldset { border: 1px solid var(--divider-color); border-radius: 8px;
             margin: 0 0 14px; padding: 10px 12px 12px; }
  legend { font-size: 12px; text-transform: uppercase; letter-spacing: .5px;
           color: var(--secondary-text-color); padding: 0 4px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  @media (max-width: 700px) { .grid2, .grid3 { grid-template-columns: 1fr; } }

  .ptable { width: 100%; border-collapse: collapse; font-size: 12px;
            font-family: var(--code-font-family, ui-monospace, Menlo, monospace); }
  .ptable td { padding: 3px 6px; border-bottom: 1px solid var(--divider-color);
               word-break: break-all; }
  .ptable td.k { color: var(--secondary-text-color); font-family: inherit; white-space: nowrap; }

  .change { border: 1px solid var(--divider-color); border-radius: 8px;
            padding: 10px 12px; margin-bottom: 10px; }
  .change .t { font-weight: 500; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .change .kind { font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
                  color: var(--secondary-text-color); }
  .change pre { margin: 8px 0 0; padding: 8px; border-radius: 6px; overflow-x: auto;
                background: var(--secondary-background-color, #f4f4f4); font-size: 12px;
                font-family: var(--code-font-family, ui-monospace, Menlo, monospace); }
  .del { color: var(--error-color, #c62828); }
  .add { color: var(--success-color, #2e7d32); }

  .banner { border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; font-size: 14px; }
  .banner.error { background: rgba(219,68,55,.12); color: var(--error-color, #c62828); }
  .banner.warn  { background: rgba(255,167,38,.15); color: var(--warning-color, #ef6c00); }
  .banner.ok    { background: rgba(67,160,71,.13); color: var(--success-color, #2e7d32); }
  .banner ul { margin: 6px 0 0; padding-left: 18px; }

  .empty { text-align: center; color: var(--secondary-text-color); padding: 48px 16px; }
  .spinner { text-align: center; padding: 48px; color: var(--secondary-text-color); }
`;

/* ------------------------------------------------------------------ utils */

// These have no decomposed form, so NFD alone would drop them entirely
// ("Übergröße" would slug to "ubergro_e"). Matches Home Assistant's own slugify.
const TRANSLITERATE = { "ß": "ss", "æ": "ae", "ø": "o", "œ": "oe" };

function slugify(value) {
  return String(value)
    .toLowerCase()
    .replace(/[ßæøœ]/g, (c) => TRANSLITERATE[c])
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // strip accents so "Küche" becomes "kuche"
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function titleCase(value) {
  return String(value).replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
}

function escapeRe(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Mirrors Home Assistant's own VALID_ENTITY_ID rule: lowercase, digits and
 * single underscores, no leading/trailing underscore, no doubled underscore.
 * Written without lookbehind so it works in every browser HA supports.
 *
 * Must stay in step with the backend check in engine.validate(), or the panel
 * would enable Apply for an ID the server then rejects.
 */
function isValidEntityId(value) {
  const parts = String(value ?? "").split(".");
  if (parts.length !== 2) return false;
  const part = (s) =>
    /^[a-z0-9_]+$/.test(s) && !s.startsWith("_") && !s.endsWith("_") && !s.includes("__");
  return part(parts[0]) && part(parts[1]);
}

/**
 * Categories are keyed by scope (automation, script, scene, helpers) and a row
 * only ever shows one of them. Replacing the whole map with the edited entry
 * would silently drop an entity's categories in any other scope, so rebuild it:
 * keep every scope we are not showing, then set or clear the one we are.
 */
function categoryPayload(existing, selected) {
  const categories = { ...(existing || {}) };
  const shownScope = Object.keys(categories)[0];
  if (shownScope) delete categories[shownScope];

  if (selected) {
    const separator = selected.indexOf(":");
    categories[selected.slice(0, separator)] = selected.slice(separator + 1);
  }
  return categories;
}

/**
 * Apply the batch operations to one string.
 *
 * Order is fixed and shown in the dialog: strip, then replace, then transform,
 * then add. Any other order makes "strip `old_` and add `new_`" behave in ways
 * nobody expects.
 */
function applyOps(value, ops) {
  let out = String(value ?? "");

  if (ops.stripPrefix && out.startsWith(ops.stripPrefix)) {
    out = out.slice(ops.stripPrefix.length);
  }
  if (ops.stripSuffix && out.endsWith(ops.stripSuffix)) {
    out = out.slice(0, -ops.stripSuffix.length);
  }

  if (ops.find) {
    let re;
    try {
      re = new RegExp(ops.regex ? ops.find : escapeRe(ops.find), ops.ignoreCase ? "gi" : "g");
    } catch {
      return out; // invalid regex: the dialog reports it separately
    }
    out = out.replace(re, ops.replace ?? "");
  }

  if (ops.transform === "lower") out = out.toLowerCase();
  else if (ops.transform === "upper") out = out.toUpperCase();
  else if (ops.transform === "slug") out = slugify(out);
  else if (ops.transform === "title") out = titleCase(out.replace(/_/g, " "));

  if (ops.addPrefix) out = ops.addPrefix + out;
  if (ops.addSuffix) out = out + ops.addSuffix;

  return out;
}

/* ------------------------------------------------------------------ panel */

class EntityRenamerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._loaded = false;
    this._entities = [];
    this._devices = new Map();
    this._areas = new Map();
    this._labels = new Map(); // label_id -> {label_id, name}
    this._categories = []; // {scope, category_id, name}
    this._orphans = []; // registry entries nothing is providing
    this._orphanWarnings = [];
    this._edits = new Map(); // entity_id -> partial override
    this._selected = new Set();
    this._open = new Set();
    this._query = "";
    this._busy = false;
    this._dialog = null;
    this._popover = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._renderShell();
      this._load();
    }
  }
  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = value;
  }

  /* ------------------------------------------------------------ data */

  async _load() {
    try {
      const [entities, devices, areas] = await Promise.all([
        this._hass.callWS({ type: "config/entity_registry/list" }),
        this._hass.callWS({ type: "config/device_registry/list" }),
        this._hass.callWS({ type: "config/area_registry/list" }),
      ]);

      this._devices = new Map(devices.map((d) => [d.id, d]));
      this._areas = new Map(areas.map((a) => [a.area_id, a]));
      // Disabled entities are kept: they still hold the ID you want to free up.
      this._entities = [...entities].sort((a, b) => a.entity_id.localeCompare(b.entity_id));

      await this._loadLabels();
      await this._loadCategories();
      await this._loadOrphans();

      this._loaded = true;
      this._renderList();
      this._renderFooter();
    } catch (err) {
      this._loaded = true;
      this._error = `Could not load the entity registry: ${err.message || err}`;
      this._renderList();
    }
  }

  async _loadLabels() {
    try {
      const labels = await this._hass.callWS({ type: "config/label_registry/list" });
      this._labels = new Map(labels.map((l) => [l.label_id, l]));
    } catch {
      this._labels = new Map(); // core too old for labels; UI hides the column
    }
  }

  /**
   * Categories live per scope (automation, script, helpers, …). There is no
   * single "entity" scope, so every scope's categories are offered and the
   * option value carries its scope.
   */
  async _loadCategories() {
    this._categories = [];
    const scopes = ["automation", "script", "scene", "helpers"];
    for (const scope of scopes) {
      try {
        const list = await this._hass.callWS({
          type: "config/category_registry/list",
          scope,
        });
        for (const c of list) {
          this._categories.push({ scope, category_id: c.category_id, name: c.name });
        }
      } catch {
        /* scope unsupported or empty */
      }
    }
  }

  /** Registry entries no integration is providing any more. */
  async _loadOrphans() {
    try {
      const result = await this._hass.callWS({ type: "entity_renamer/orphans" });
      this._orphans = result.orphans || [];
      this._orphanWarnings = result.warnings || [];
    } catch {
      this._orphans = [];
      this._orphanWarnings = [];
    }

    const button = this.shadowRoot.getElementById("cleanup");
    if (!button) return;
    button.hidden = this._orphans.length === 0;
    button.textContent = `Clean up ${this._orphans.length} orphaned…`;
  }

  _openCleanup() {
    const orphans = this._orphans || [];
    const rows = orphans
      .map(
        (o, index) => `
        <tr>
          <td><input type="checkbox" data-orphan="${index}" checked /></td>
          <td>${this._escape(o.entity_id)}</td>
          <td class="k">${this._escape(o.name || "—")}</td>
          <td class="k">${this._escape(o.platform)}</td>
          <td class="k">${this._escape(o.reason)}</td>
        </tr>`
      )
      .join("");

    const body = `
      <div class="banner warn">
        These entities are in the registry but <strong>nothing is providing
        them</strong> — usually the leftovers of a removed integration. Deleting
        one frees its entity ID.
        <br /><br />
        This <strong>cannot be undone from the panel</strong>. A backup of
        <code>.storage</code> is written first. Recorder history for these
        entities is not deleted, but it is no longer reachable.
        <br /><br />
        Disabled entities are never listed here, and every entity is re-checked
        server-side at deletion — if one has come back to life, it is skipped.
      </div>
      ${
        (this._orphanWarnings || []).length
          ? `<div class="banner warn">${this._orphanWarnings
              .map((w) => this._escape(w))
              .join("<br />")}</div>`
          : ""
      }
      <div style="margin-bottom:8px">
        <label class="cb"><input type="checkbox" id="orphanAll" checked /> Select all</label>
      </div>
      <table class="ptable">
        <tr><td></td><td class="k">Entity ID</td><td class="k">Name</td><td class="k">Integration</td><td class="k">Why</td></tr>
        ${rows}
      </table>
    `;

    this._showDialog(`${orphans.length} orphaned entities`, body, [
      { label: "Cancel", action: () => this._closeDialog() },
      { label: "Delete selected", primary: true, action: () => remove() },
    ]);

    const root = this._dialog;
    const boxes = () => [...root.querySelectorAll("[data-orphan]")];
    root.querySelector("#orphanAll").addEventListener("change", (ev) => {
      for (const box of boxes()) box.checked = ev.target.checked;
    });

    const remove = async () => {
      const ids = boxes()
        .filter((box) => box.checked)
        .map((box) => orphans[Number(box.dataset.orphan)].entity_id);

      if (!ids.length) {
        this._closeDialog();
        return;
      }

      this._showDialog("Removing…", `<div class="spinner">Backing up and removing…</div>`, []);
      try {
        const result = await this._hass.callWS({
          type: "entity_renamer/remove_orphans",
          entity_ids: ids,
        });

        const parts = [
          `<div class="banner ok"><strong>Removed ${result.removed.length} entit${
            result.removed.length === 1 ? "y" : "ies"
          }.</strong>${
            result.backup ? ` Backup: <code>${this._escape(result.backup)}</code>.` : ""
          }</div>`,
        ];
        if (result.errors.length) {
          parts.push(
            `<div class="banner warn"><strong>Skipped:</strong><ul>${result.errors
              .map((e) => `<li>${this._escape(e)}</li>`)
              .join("")}</ul></div>`
          );
        }
        if (result.removed.length) {
          parts.push(
            `<pre>${result.removed.map((e) => this._escape(e)).join("\n")}</pre>`
          );
        }

        this._showDialog("Cleanup complete", parts.join(""), [
          { label: "Close", primary: true, action: () => this._closeDialog() },
        ]);
        await this._load();
      } catch (err) {
        this._showDialog(
          "Failed",
          `<div class="banner error">${this._escape(err.message || String(err))}</div>`,
          [{ label: "Close", primary: true, action: () => this._closeDialog() }]
        );
      }
    };
  }

  async _collectDashboards() {
    const configs = {};
    const skipped = [];

    const targets = [{ url_path: null, key: DEFAULT_DASHBOARD_KEY, title: "Default" }];
    try {
      const list = await this._hass.callWS({ type: "lovelace/dashboards/list" });
      for (const d of list) targets.push({ url_path: d.url_path, key: d.url_path, title: d.title });
    } catch (err) {
      skipped.push(`dashboard list unavailable (${err.message || err})`);
    }

    for (const t of targets) {
      try {
        const config = await this._hass.callWS({ type: "lovelace/config", url_path: t.url_path });
        if (config) configs[t.key] = config;
      } catch (err) {
        // config_not_found simply means "not a storage-mode dashboard".
        if (err.code !== "config_not_found") skipped.push(`${t.title}: ${err.message || err}`);
      }
    }
    return { configs, skipped };
  }

  async _saveDashboards(dashboards) {
    const failed = [];
    for (const [key, config] of Object.entries(dashboards || {})) {
      try {
        await this._hass.callWS({
          type: "lovelace/config/save",
          url_path: key === DEFAULT_DASHBOARD_KEY ? null : key,
          config,
        });
      } catch (err) {
        failed.push(`${key}: ${err.message || err}`);
      }
    }
    return failed;
  }

  /* -------------------------------------------------------- edit model */

  _original(entity) {
    const categories = entity.categories || {};
    const first = Object.entries(categories)[0];
    return {
      entity_id: entity.entity_id,
      name: entity.name ?? entity.original_name ?? "",
      labels: [...(entity.labels || [])].sort(),
      category: first ? `${first[0]}:${first[1]}` : "",
    };
  }

  _current(entity) {
    return { ...this._original(entity), ...(this._edits.get(entity.entity_id) || {}) };
  }

  _dirtyFields(entity) {
    const original = this._original(entity);
    const current = this._current(entity);
    const fields = [];
    if (current.entity_id !== original.entity_id) fields.push("entity_id");
    if (current.name !== original.name) fields.push("name");
    if (current.labels.join("|") !== original.labels.join("|")) fields.push("labels");
    if (current.category !== original.category) fields.push("category");
    return fields;
  }

  _setEdit(entityId, field, value) {
    const entity = this._entities.find((e) => e.entity_id === entityId);
    if (!entity) return;
    const original = this._original(entity);
    const override = { ...(this._edits.get(entityId) || {}) };

    const same =
      field === "labels"
        ? value.join("|") === original.labels.join("|")
        : value === original[field];

    if (same) delete override[field];
    else override[field] = value;

    if (Object.keys(override).length) this._edits.set(entityId, override);
    else this._edits.delete(entityId);
  }

  _dirtyEntities() {
    return this._entities.filter((e) => this._dirtyFields(e).length);
  }

  /* ---------------------------------------------------------- grouping */

  _visibleEntities() {
    const q = this._query.trim().toLowerCase();
    if (!q) return this._entities;
    return this._entities.filter((e) => {
      const device = e.device_id ? this._devices.get(e.device_id) : null;
      const labels = (e.labels || []).map((id) => this._labels.get(id)?.name || id);
      return [
        e.entity_id,
        e.name || e.original_name || "",
        e.platform || "",
        device ? device.name_by_user || device.name || "" : "",
        labels.join(" "),
      ]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }

  _grouped(entities) {
    const byPlatform = new Map();
    for (const entity of entities) {
      const platform = entity.platform || "unknown";
      if (!byPlatform.has(platform)) byPlatform.set(platform, new Map());
      const byDevice = byPlatform.get(platform);
      const key = entity.device_id || "__none__";
      if (!byDevice.has(key)) byDevice.set(key, []);
      byDevice.get(key).push(entity);
    }
    return [...byPlatform.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  _deviceLabel(deviceId) {
    if (deviceId === "__none__") return { name: "Without a device", area: "" };
    const device = this._devices.get(deviceId);
    if (!device) return { name: "Unknown device", area: "" };
    const area = device.area_id ? this._areas.get(device.area_id) : null;
    return {
      name: device.name_by_user || device.name || "Unnamed device",
      area: area ? area.name : "",
    };
  }

  /* ------------------------------------------------------------ render */

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="shell">
        <header>
          <button class="menu-btn" id="menu" title="Menu">&#9776;</button>
          <div class="title">Entity Renamer</div>
        </header>
        <div class="toolbar">
          <div class="search">
            <input type="search" id="q" placeholder="Search entity ID, name, device, integration or label…" />
          </div>
          <div class="hint" id="hint"></div>
          <button class="action secondary" id="cleanup" hidden></button>
        </div>
        <div id="selbar"></div>
        <div class="list" id="list"><div class="spinner">Loading entity registry…</div></div>
        <div class="footer" id="footer"></div>
      </div>
    `;

    this.shadowRoot.getElementById("menu").addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    });

    this.shadowRoot
      .getElementById("cleanup")
      .addEventListener("click", () => this._openCleanup());

    const search = this.shadowRoot.getElementById("q");
    let timer = null;
    search.addEventListener("input", (ev) => {
      clearTimeout(timer);
      const value = ev.target.value;
      timer = setTimeout(() => {
        this._query = value;
        this._renderList();
      }, 180);
    });
  }

  _renderList() {
    const list = this.shadowRoot.getElementById("list");
    const hint = this.shadowRoot.getElementById("hint");
    if (!list) return;

    if (!this._loaded) {
      list.innerHTML = `<div class="spinner">Loading entity registry…</div>`;
      return;
    }
    if (this._error) {
      list.innerHTML = `<div class="banner error">${this._escape(this._error)}</div>`;
      return;
    }

    const entities = this._visibleEntities();
    const groups = this._grouped(entities);
    const searching = this._query.trim().length > 0;

    hint.textContent = `${entities.length} of ${this._entities.length} entities`;

    if (!entities.length) {
      list.innerHTML = `<div class="empty">No entities match “${this._escape(this._query)}”.</div>`;
      this._renderSelBar();
      return;
    }

    // Only expanded groups are rendered, so a 3000-entity registry still opens
    // instantly. A search auto-expands its matches, up to a row budget.
    let budget = MAX_RENDERED_ROWS;
    const html = [];

    for (const [platform, byDevice] of groups) {
      const items = [...byDevice.values()].flat();
      const total = items.length;
      const dirty = items.filter((e) => this._dirtyFields(e).length).length;
      const selected = items.filter((e) => this._selected.has(e.entity_id)).length;

      let open = this._open.has(platform);
      if (searching && budget - total >= 0) {
        open = true;
        budget -= total;
      }

      html.push(`<div class="group ${open ? "open" : ""}">`);
      html.push(
        `<div class="head">
           <input type="checkbox" data-selgroup="${this._escape(platform)}"
                  title="Select all in this integration"
                  ${selected === total ? "checked" : ""} />
           <div class="grow" data-toggle="${this._escape(platform)}">
             <span class="chev">&#9656;</span>
             <span>${this._escape(platform)}</span>
             <span class="count">${total} ${total === 1 ? "entity" : "entities"}</span>
             ${dirty ? `<span class="badge">${dirty} edited</span>` : ""}
             ${selected ? `<span class="count">${selected} selected</span>` : ""}
           </div>
         </div>`
      );

      if (open) {
        const devices = [...byDevice.entries()].sort((a, b) =>
          this._deviceLabel(a[0]).name.localeCompare(this._deviceLabel(b[0]).name)
        );
        for (const [deviceId, deviceItems] of devices) {
          const label = this._deviceLabel(deviceId);
          const allSelected = deviceItems.every((e) => this._selected.has(e.entity_id));
          html.push(`<div class="device">`);
          html.push(
            `<div class="dhead">
               <input type="checkbox" data-seldevice="${this._escape(platform)}|${this._escape(deviceId)}"
                      title="Select all on this device" ${allSelected ? "checked" : ""} />
               <span>${this._escape(label.name)}</span>
               ${label.area ? `<span class="area">· ${this._escape(label.area)}</span>` : ""}
             </div>`
          );
          for (const entity of deviceItems) html.push(this._rowHtml(entity));
          html.push(`</div>`);
        }
      }
      html.push(`</div>`);
    }

    list.innerHTML = html.join("");
    this._bindList(list);
    this._renderSelBar();
  }

  _rowHtml(entity) {
    const id = entity.entity_id;
    const current = this._current(entity);
    const dirty = this._dirtyFields(entity).length > 0;
    const selected = this._selected.has(id);

    const chips = current.labels.length
      ? current.labels
          .map((l) => `<span class="chip">${this._escape(this._labels.get(l)?.name || l)}</span>`)
          .join("")
      : `<span class="ph">No labels</span>`;

    const options = [`<option value=""${current.category ? "" : " selected"}>— No category —</option>`];
    for (const c of this._categories) {
      const value = `${c.scope}:${c.category_id}`;
      options.push(
        `<option value="${this._escape(value)}"${
          value === current.category ? " selected" : ""
        }>${this._escape(c.name)} (${this._escape(c.scope)})</option>`
      );
    }

    return `
      <div class="row ${dirty ? "dirty" : ""} ${selected ? "sel" : ""}" data-row="${this._escape(id)}">
        <div class="line1">
          <input type="checkbox" data-select="${this._escape(id)}" ${selected ? "checked" : ""} />
          <div class="cur" title="${this._escape(id)}">${this._escape(id)}</div>
          <div class="arrow">&#8594;</div>
          <input class="id" type="text" spellcheck="false" autocapitalize="off" autocomplete="off"
                 value="${this._escape(current.entity_id)}" data-field="entity_id"
                 data-id="${this._escape(id)}" />
          <button class="reset" data-reset="${this._escape(id)}" title="Undo all edits on this entity">&#8634;</button>
        </div>
        <div class="meta">
          <div class="field">
            <span class="lab">Name</span>
            <input type="text" placeholder="${this._escape(entity.original_name || "No name")}"
                   value="${this._escape(current.name)}" data-field="name" data-id="${this._escape(id)}" />
          </div>
          <div class="field">
            <span class="lab">Labels</span>
            <button class="chipbtn" data-labels="${this._escape(id)}">${chips}</button>
          </div>
          <div class="field">
            <span class="lab">Category</span>
            <select data-field="category" data-id="${this._escape(id)}">${options.join("")}</select>
          </div>
        </div>
      </div>`;
  }

  _bindList(list) {
    list.querySelectorAll("[data-toggle]").forEach((el) => {
      el.addEventListener("click", () => {
        const key = el.dataset.toggle;
        if (this._open.has(key)) this._open.delete(key);
        else this._open.add(key);
        this._renderList();
      });
    });

    list.querySelectorAll("[data-selgroup]").forEach((el) => {
      el.addEventListener("change", () => {
        const platform = el.dataset.selgroup;
        const items = this._visibleEntities().filter((e) => (e.platform || "unknown") === platform);
        for (const entity of items) {
          if (el.checked) this._selected.add(entity.entity_id);
          else this._selected.delete(entity.entity_id);
        }
        this._renderList();
      });
    });

    list.querySelectorAll("[data-seldevice]").forEach((el) => {
      el.addEventListener("change", () => {
        const [platform, deviceId] = el.dataset.seldevice.split("|");
        const items = this._visibleEntities().filter(
          (e) => (e.platform || "unknown") === platform && (e.device_id || "__none__") === deviceId
        );
        for (const entity of items) {
          if (el.checked) this._selected.add(entity.entity_id);
          else this._selected.delete(entity.entity_id);
        }
        this._renderList();
      });
    });

    // Selection must not re-render: that would drop scroll position and focus.
    list.querySelectorAll("[data-select]").forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.select;
        if (el.checked) this._selected.add(id);
        else this._selected.delete(id);
        el.closest(".row").classList.toggle("sel", el.checked);
        this._renderSelBar();
      });
    });

    list.querySelectorAll("input[data-field], select[data-field]").forEach((el) => {
      const event = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(event, () => {
        const id = el.dataset.id;
        const field = el.dataset.field;
        let value = el.value;
        if (field === "entity_id") value = value.trim();
        this._setEdit(id, field, value);

        const row = el.closest(".row");
        row.classList.toggle("dirty", this._dirtyFields(this._entity(id)).length > 0);
        if (field === "entity_id") {
          el.classList.toggle("invalid", value !== id && !this._validId(id, value));
        }
        this._renderFooter();
      });
    });

    list.querySelectorAll("[data-labels]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._openLabelPicker([el.dataset.labels], el);
      });
    });

    list.querySelectorAll("[data-reset]").forEach((el) => {
      el.addEventListener("click", () => {
        this._edits.delete(el.dataset.reset);
        this._renderList();
        this._renderFooter();
      });
    });
  }

  _entity(entityId) {
    return this._entities.find((e) => e.entity_id === entityId);
  }

  _validId(oldId, value) {
    // HA forbids changing an entity's domain, so that is checked here too.
    return isValidEntityId(value) && value.split(".")[0] === oldId.split(".")[0];
  }

  _invalidCount() {
    return this._dirtyEntities().filter((e) => {
      const current = this._current(e);
      return current.entity_id !== e.entity_id && !this._validId(e.entity_id, current.entity_id);
    }).length;
  }

  /* --------------------------------------------------------- selection */

  _renderSelBar() {
    const bar = this.shadowRoot.getElementById("selbar");
    if (!bar) return;
    const count = this._selected.size;
    if (!count) {
      bar.className = "";
      bar.innerHTML = "";
      return;
    }

    bar.className = "selbar";
    bar.innerHTML = `
      <strong>${count} selected</strong>
      <button id="selall">Select all ${this._visibleEntities().length} shown</button>
      <button id="selnone">Clear selection</button>
      <div class="spacer"></div>
      <button class="strong" id="batch">Batch edit ${count} entities…</button>
    `;
    bar.querySelector("#selall").addEventListener("click", () => {
      for (const entity of this._visibleEntities()) this._selected.add(entity.entity_id);
      this._renderList();
    });
    bar.querySelector("#selnone").addEventListener("click", () => {
      this._selected.clear();
      this._renderList();
    });
    bar.querySelector("#batch").addEventListener("click", () => this._openBatchEditor());
  }

  /* ------------------------------------------------------ label picker */

  _openLabelPicker(entityIds, anchor) {
    this._closePopover();

    // With several entities, a label is pre-checked only when all of them have
    // it; toggling then applies to the whole selection.
    const counts = new Map();
    for (const id of entityIds) {
      const entity = this._entity(id);
      if (!entity) continue;
      for (const label of this._current(entity).labels) {
        counts.set(label, (counts.get(label) || 0) + 1);
      }
    }

    const popover = document.createElement("div");
    popover.className = "popover";
    const options = [...this._labels.values()].sort((a, b) => a.name.localeCompare(b.name));

    popover.innerHTML =
      (options.length
        ? options
            .map((label) => {
              const n = counts.get(label.label_id) || 0;
              const all = n === entityIds.length;
              return `<label class="opt">
                        <input type="checkbox" data-label="${this._escape(label.label_id)}"
                               ${all ? "checked" : ""} ${n && !all ? 'data-partial="1"' : ""} />
                        <span>${this._escape(label.name)}${
                n && !all ? ` <em>(${n}/${entityIds.length})</em>` : ""
              }</span>
                      </label>`;
            })
            .join("")
        : `<div class="opt">No labels defined yet.</div>`) +
      `<div class="newrow">
         <input type="text" id="newlabel" placeholder="New label name" />
         <button class="action" id="createlabel">Add</button>
       </div>`;

    popover.querySelectorAll("[data-label]").forEach((box) => {
      box.addEventListener("change", () => {
        for (const id of entityIds) {
          const entity = this._entity(id);
          if (!entity) continue;
          const labels = new Set(this._current(entity).labels);
          if (box.checked) labels.add(box.dataset.label);
          else labels.delete(box.dataset.label);
          this._setEdit(id, "labels", [...labels].sort());
        }
        this._renderList();
        this._renderFooter();
      });
    });

    const create = async () => {
      const input = popover.querySelector("#newlabel");
      const name = input.value.trim();
      if (!name) return;
      try {
        const label = await this._hass.callWS({
          type: "config/label_registry/create",
          name,
        });
        this._labels.set(label.label_id, label);
        for (const id of entityIds) {
          const entity = this._entity(id);
          if (!entity) continue;
          const labels = new Set(this._current(entity).labels);
          labels.add(label.label_id);
          this._setEdit(id, "labels", [...labels].sort());
        }
        this._closePopover();
        this._renderList();
        this._renderFooter();
      } catch (err) {
        input.value = "";
        input.placeholder = `Failed: ${err.message || err}`;
      }
    };
    popover.querySelector("#createlabel").addEventListener("click", create);
    popover.querySelector("#newlabel").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") create();
    });

    const rect = anchor.getBoundingClientRect();
    popover.style.left = `${Math.min(rect.left, window.innerWidth - 260)}px`;
    popover.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 340)}px`;

    this.shadowRoot.appendChild(popover);
    this._popover = popover;

    setTimeout(() => {
      this._popoverCloser = (ev) => {
        if (!popover.contains(ev.composedPath()[0])) this._closePopover();
      };
      window.addEventListener("click", this._popoverCloser, true);
    }, 0);
  }

  _closePopover() {
    if (this._popoverCloser) {
      window.removeEventListener("click", this._popoverCloser, true);
      this._popoverCloser = null;
    }
    if (this._popover) {
      this._popover.remove();
      this._popover = null;
    }
  }

  /* ------------------------------------------------------ batch editor */

  _openBatchEditor() {
    const ids = [...this._selected];
    const categoryOptions = this._categories
      .map(
        (c) =>
          `<option value="${this._escape(`${c.scope}:${c.category_id}`)}">${this._escape(
            c.name
          )} (${this._escape(c.scope)})</option>`
      )
      .join("");

    const body = `
      <div class="banner warn">
        Operations run in this order: <strong>strip → find/replace → transform → add</strong>.
        Entity ID edits apply to the part <em>after</em> the domain, so the domain can never be broken.
        Nothing is written until you preview and apply.
      </div>

      <fieldset>
        <legend>Apply to</legend>
        <label class="cb"><input type="checkbox" id="doId" checked /> Entity ID</label>
        &nbsp;&nbsp;
        <label class="cb"><input type="checkbox" id="doName" /> Name</label>
      </fieldset>

      <fieldset>
        <legend>Find and replace</legend>
        <div class="grid2">
          <div class="field"><span class="lab">Find</span><input type="text" id="find" /></div>
          <div class="field"><span class="lab">Replace with</span><input type="text" id="replace" /></div>
        </div>
        <div style="margin-top:8px">
          <label class="cb"><input type="checkbox" id="regex" /> Regular expression</label>
          &nbsp;&nbsp;
          <label class="cb"><input type="checkbox" id="icase" /> Ignore case</label>
          <span id="reerr" class="del" style="margin-left:10px"></span>
        </div>
      </fieldset>

      <fieldset>
        <legend>Affixes</legend>
        <div class="grid2">
          <div class="field"><span class="lab">Strip prefix</span><input type="text" id="stripPrefix" /></div>
          <div class="field"><span class="lab">Strip suffix</span><input type="text" id="stripSuffix" /></div>
          <div class="field"><span class="lab">Add prefix</span><input type="text" id="addPrefix" /></div>
          <div class="field"><span class="lab">Add suffix</span><input type="text" id="addSuffix" /></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Transform</legend>
        <select id="transform">
          <option value="">— none —</option>
          <option value="lower">lowercase</option>
          <option value="upper">UPPERCASE</option>
          <option value="slug">slugify (safe for entity IDs)</option>
          <option value="title">Title Case (underscores become spaces)</option>
        </select>
      </fieldset>

      <fieldset>
        <legend>Labels and category</legend>
        <div class="grid3">
          <div class="field">
            <span class="lab">Labels</span>
            <button class="chipbtn" id="batchLabels"><span class="ph">Edit labels…</span></button>
          </div>
          <div class="field">
            <span class="lab">Category</span>
            <select id="batchCategory">
              <option value="__keep__">— leave unchanged —</option>
              <option value="">— clear category —</option>
              ${categoryOptions}
            </select>
          </div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Preview</legend>
        <div id="bpreview"></div>
      </fieldset>
    `;

    this._showDialog(`Batch edit ${ids.length} entities`, body, [
      { label: "Cancel", action: () => this._closeDialog() },
      { label: "Stage these edits", primary: true, action: () => commit() },
    ]);

    const root = this._dialog;
    const get = (id) => root.querySelector(`#${id}`);
    const readOps = () => ({
      find: get("find").value,
      replace: get("replace").value,
      regex: get("regex").checked,
      ignoreCase: get("icase").checked,
      stripPrefix: get("stripPrefix").value,
      stripSuffix: get("stripSuffix").value,
      addPrefix: get("addPrefix").value,
      addSuffix: get("addSuffix").value,
      transform: get("transform").value,
    });

    // Compute the resulting id/name for one entity without mutating state, so
    // the preview and the commit can never disagree.
    const compute = (entity) => {
      const ops = readOps();
      const current = this._current(entity);
      const result = {};

      if (get("doId").checked) {
        const [domain, ...rest] = current.entity_id.split(".");
        const objectId = rest.join(".");
        result.entity_id = `${domain}.${applyOps(objectId, ops)}`;
      }
      if (get("doName").checked) {
        result.name = applyOps(current.name, ops);
      }
      return result;
    };

    const refresh = () => {
      // Surface a bad regex instead of silently doing nothing.
      get("reerr").textContent = "";
      if (get("regex").checked && get("find").value) {
        try {
          new RegExp(get("find").value);
        } catch (err) {
          get("reerr").textContent = `Invalid regex: ${err.message}`;
        }
      }

      const rows = [];
      let changed = 0;
      for (const id of ids) {
        const entity = this._entity(id);
        if (!entity) continue;
        const current = this._current(entity);
        const next = compute(entity);
        const idChanged = next.entity_id !== undefined && next.entity_id !== current.entity_id;
        const nameChanged = next.name !== undefined && next.name !== current.name;
        if (!idChanged && !nameChanged) continue;
        changed++;
        if (rows.length < BATCH_PREVIEW_ROWS) {
          if (idChanged) {
            rows.push(
              `<tr><td class="k">ID</td><td class="del">${this._escape(
                current.entity_id
              )}</td><td class="add">${this._escape(next.entity_id)}</td></tr>`
            );
          }
          if (nameChanged) {
            rows.push(
              `<tr><td class="k">Name</td><td class="del">${this._escape(
                current.name || "—"
              )}</td><td class="add">${this._escape(next.name || "—")}</td></tr>`
            );
          }
        }
      }

      get("bpreview").innerHTML = rows.length
        ? `<table class="ptable">${rows.join("")}</table>
           <div class="hint" style="margin-top:8px">${changed} of ${ids.length} entities affected${
            changed > BATCH_PREVIEW_ROWS ? ` (showing the first ${BATCH_PREVIEW_ROWS} rows)` : ""
          }</div>`
        : `<div class="hint">No entity ID or name changes yet — fill in an operation above.</div>`;
    };

    root
      .querySelectorAll("input, select")
      .forEach((el) => el.addEventListener("input", refresh));
    root.querySelectorAll("select").forEach((el) => el.addEventListener("change", refresh));

    get("batchLabels").addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._openLabelPicker(ids, get("batchLabels"));
    });

    const commit = () => {
      const category = get("batchCategory").value;
      for (const id of ids) {
        const entity = this._entity(id);
        if (!entity) continue;
        const next = compute(entity);
        if (next.entity_id !== undefined) this._setEdit(id, "entity_id", next.entity_id);
        if (next.name !== undefined) this._setEdit(id, "name", next.name);
        if (category !== "__keep__") this._setEdit(id, "category", category);
      }
      this._closeDialog();
      this._renderList();
      this._renderFooter();
    };

    refresh();
  }

  /* ------------------------------------------------------------ footer */

  _renderFooter() {
    const footer = this.shadowRoot.getElementById("footer");
    if (!footer) return;
    const dirty = this._dirtyEntities();
    const count = dirty.length;
    const invalid = this._invalidCount();
    const renames = dirty.filter((e) => this._current(e).entity_id !== e.entity_id).length;
    const ready = count && !invalid && !this._busy ? "" : "disabled";

    footer.innerHTML = `
      <div class="hint">${
        count
          ? `${count} entit${count === 1 ? "y" : "ies"} edited · ${renames} ID rename${
              renames === 1 ? "" : "s"
            }${invalid ? ` · <span class="del">${invalid} invalid</span>` : ""}`
          : "Edit an ID, name, label or category — or select rows and use Batch edit."
      }</div>
      <div class="spacer"></div>
      <button class="action secondary" id="clear" ${count ? "" : "disabled"}>Discard edits</button>
      <button class="action secondary" id="preview" ${ready}>Preview changes</button>
      <button class="action secondary" id="save" ${ready}
              title="Write the registry only — does not update references">Save entity changes</button>
      <button class="action" id="apply" ${ready}>Update and replace all references</button>
    `;

    footer.querySelector("#clear").addEventListener("click", () => {
      this._edits.clear();
      this._renderList();
      this._renderFooter();
    });
    footer.querySelector("#preview").addEventListener("click", () => this._run(false));
    footer.querySelector("#save").addEventListener("click", () => this._confirmSaveOnly());
    footer.querySelector("#apply").addEventListener("click", () => this._run(true));
  }

  /**
   * Registry-only save. Harmless for names, labels and categories -- nothing
   * outside the registry refers to them. For an ID rename it is the exact
   * footgun this integration exists to prevent, so that case is spelled out
   * before it happens.
   */
  _confirmSaveOnly() {
    const renames = this._dirtyEntities().filter(
      (e) => this._current(e).entity_id !== e.entity_id
    );

    const warning = renames.length
      ? `<div class="banner error">
           <strong>${renames.length} entity ID${renames.length === 1 ? "" : "s"} will be renamed
           without updating any references.</strong>
           Automations, scripts, scenes, dashboards, helpers and templates that
           point at the old ID will silently stop working.
           <br /><br />
           Use <em>Update and replace all references</em> instead unless you know
           nothing refers to these entities.
           <pre>${renames
             .map(
               (e) =>
                 `${this._escape(e.entity_id)} → ${this._escape(this._current(e).entity_id)}`
             )
             .join("\n")}</pre>
         </div>`
      : `<div class="banner ok">
           Only names, labels and categories are changing. Nothing outside the
           entity registry refers to those, so there is nothing to rewrite.
         </div>`;

    this._showDialog("Save entity changes only", warning, [
      { label: "Cancel", action: () => this._closeDialog() },
      {
        label: renames.length ? "Rename anyway, without references" : "Save changes",
        primary: true,
        action: () => {
          this._closeDialog();
          this._run(true, true);
        },
      },
    ]);
  }

  /* ----------------------------------------------------------- actions */

  _payload() {
    return this._dirtyEntities().map((entity) => {
      const fields = this._dirtyFields(entity);
      const current = this._current(entity);
      const item = { old_entity_id: entity.entity_id };

      if (fields.includes("entity_id")) item.new_entity_id = current.entity_id;
      if (fields.includes("name")) item.new_name = current.name;
      if (fields.includes("labels")) item.new_labels = current.labels;
      if (fields.includes("category")) {
        item.new_categories = categoryPayload(entity.categories, current.category);
      }
      return item;
    });
  }

  async _run(apply, skipReferences = false) {
    this._busy = true;
    this._renderFooter();
    this._showDialog(
      apply ? "Applying changes…" : "Scanning…",
      `<div class="spinner">${
        skipReferences
          ? "Writing the entity registry…"
          : "Reading dashboards, YAML files, helpers and the energy dashboard…"
      }</div>`,
      []
    );

    try {
      // A registry-only save rewrites no dashboards, so there is no reason to
      // pull every dashboard config over the wire first.
      const { configs, skipped } = skipReferences
        ? { configs: {}, skipped: [] }
        : await this._collectDashboards();

      const result = await this._hass.callWS({
        type: apply ? "entity_renamer/apply" : "entity_renamer/preview",
        renames: this._payload(),
        dashboards: configs,
        skip_references: skipReferences,
      });

      // Key the follow-up on `applied`, not on the error list. An apply that
      // renamed entities but hit one YAML write error still MUST save the
      // rewritten dashboards -- skipping them would leave dashboards pointing
      // at IDs that no longer exist.
      let dashboardFailures = [];
      if (apply && result.applied) {
        dashboardFailures = await this._saveDashboards(result.dashboards);
      }

      this._showResult(apply, result, skipped, dashboardFailures);

      if (apply && result.applied) {
        // Staged edits now describe a registry that has moved on; reload from
        // the source of truth rather than trying to reconcile.
        this._edits.clear();
        this._selected.clear();
        await this._load();
      }
    } catch (err) {
      this._showDialog(
        "Failed",
        `<div class="banner error">${this._escape(err.message || String(err))}</div>`,
        [{ label: "Close", primary: true, action: () => this._closeDialog() }]
      );
    } finally {
      this._busy = false;
      this._renderFooter();
    }
  }

  // `wasApply` = the user pressed Apply (vs Preview).
  // `result.applied` = the server actually started writing.
  // These differ exactly when an apply is rejected by validation, which is the
  // case that used to be reported wrongly.
  _showResult(wasApply, result, skipped, dashboardFailures) {
    const parts = [];

    if (result.errors.length) {
      // A run that started writing reports partial failures; saying "nothing
      // was changed" there would be a lie.
      const heading = !wasApply
        ? "These edits are not valid:"
        : result.applied
          ? "Changes were written, but some steps failed:"
          : "Nothing was changed:";
      parts.push(
        `<div class="banner ${result.applied ? "warn" : "error"}"><strong>${heading}</strong><ul>${result.errors
          .map((e) => `<li>${this._escape(e)}</li>`)
          .join("")}</ul></div>`
      );
    }

    if (wasApply && result.applied && !result.errors.length) {
      parts.push(
        `<div class="banner ok"><strong>Done.</strong> ${result.total} change${
          result.total === 1 ? "" : "s"
        } written.${
          result.backup ? ` Backup: <code>${this._escape(result.backup)}</code>.` : ""
        }</div>`
      );
      if (result.references_skipped) {
        parts.push(
          `<div class="banner warn">Registry only — no references were rewritten,
           and nothing was reloaded.</div>`
        );
      }
    }

    const warnings = [...(result.warnings || []), ...skipped, ...dashboardFailures];
    if (warnings.length) {
      parts.push(
        `<div class="banner warn"><strong>Check these manually:</strong><ul>${warnings
          .map((w) => `<li>${this._escape(w)}</li>`)
          .join("")}</ul></div>`
      );
    }

    if (!result.changes.length && !result.errors.length) {
      parts.push(`<div class="banner warn">Nothing to change.</div>`);
    }

    for (const change of result.changes) {
      const samples = change.samples
        .map(
          (s) =>
            `<span class="del">- ${this._escape(s.before)}</span>\n<span class="add">+ ${this._escape(
              s.after
            )}</span>`
        )
        .join("\n");
      parts.push(`
        <div class="change">
          <div class="t">
            <span class="kind">${this._escape(change.kind)}</span>
            <span>${this._escape(change.target)}</span>
            <span class="count">${change.count} change${change.count === 1 ? "" : "s"}</span>
          </div>
          ${change.note ? `<div class="hint">${this._escape(change.note)}</div>` : ""}
          ${samples ? `<pre>${samples}</pre>` : ""}
        </div>`);
    }

    const buttons = wasApply
      ? [{ label: "Close", primary: true, action: () => this._closeDialog() }]
      : [
          { label: "Cancel", action: () => this._closeDialog() },
          {
            label: "Apply these changes",
            primary: true,
            disabled: result.errors.length > 0,
            action: () => {
              this._closeDialog();
              this._run(true);
            },
          },
        ];

    this._showDialog(
      wasApply ? "Changes applied" : `Preview — ${result.total} change${result.total === 1 ? "" : "s"}`,
      parts.join(""),
      buttons
    );
  }

  /* ------------------------------------------------------------ dialog */

  _showDialog(title, bodyHtml, buttons) {
    this._closeDialog();
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="dialog">
        <h2>${this._escape(title)}</h2>
        <div class="body">${bodyHtml}</div>
        <div class="foot"></div>
      </div>`;

    const foot = overlay.querySelector(".foot");
    for (const button of buttons || []) {
      const el = document.createElement("button");
      el.className = `action${button.primary ? "" : " secondary"}`;
      el.textContent = button.label;
      if (button.disabled) el.disabled = true;
      el.addEventListener("click", button.action);
      foot.appendChild(el);
    }

    this.shadowRoot.appendChild(overlay);
    this._dialog = overlay;
  }

  _closeDialog() {
    this._closePopover();
    if (this._dialog) {
      this._dialog.remove();
      this._dialog = null;
    }
  }

  _escape(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
    );
  }
}

customElements.define("entity-renamer-panel", EntityRenamerPanel);
