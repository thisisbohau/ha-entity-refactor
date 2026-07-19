/**
 * Tests for the batch editor's string operations.
 *
 * The panel module ends in `customElements.define`, which cannot run under
 * Node, so this slices the pure-function section out of the real source and
 * evaluates it. That keeps the tests honest -- they exercise the shipped code,
 * not a copy of it.
 *
 *   node tests/test_batch_ops.mjs
 *
 * Uses a hand-rolled runner rather than `node:test` so it works on Node 16,
 * which is what ships in several Home Assistant dev setups.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const results = { pass: 0, fail: 0 };
function test(name, fn) {
  try {
    fn();
    results.pass++;
  } catch (err) {
    results.fail++;
    console.error(`FAIL  ${name}\n      ${err.message.split("\n").join("\n      ")}`);
  }
}
process.on("exit", () => {
  console.log(`${results.pass} passed, ${results.fail} failed`);
  if (results.fail) process.exitCode = 1;
});

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const source = readFileSync(
  join(root, "custom_components/entity_renamer/frontend/entity-renamer-panel.js"),
  "utf8"
);

const start = source.indexOf("/* ------------------------------------------------------------------ utils */");
const end = source.indexOf("/* ------------------------------------------------------------------ panel */");
assert.ok(start > 0 && end > start, "utils section markers not found in panel source");

const { applyOps, slugify, isValidEntityId, categoryPayload } = await import(
  `data:text/javascript,${encodeURIComponent(
    source.slice(start, end) +
      "\nexport { applyOps, slugify, titleCase, escapeRe, isValidEntityId, categoryPayload };"
  )}`
);

const NONE = {
  find: "",
  replace: "",
  regex: false,
  ignoreCase: false,
  stripPrefix: "",
  stripSuffix: "",
  addPrefix: "",
  addSuffix: "",
  transform: "",
};
const ops = (over) => ({ ...NONE, ...over });

test("no operations leaves the value alone", () => {
  assert.equal(applyOps("living_room_temp", ops({})), "living_room_temp");
});

test("literal find and replace", () => {
  assert.equal(
    applyOps("shellyplus_kitchen_power", ops({ find: "shellyplus_", replace: "" })),
    "kitchen_power"
  );
});

test("literal find does not treat input as regex", () => {
  // A literal "." must not match every character.
  assert.equal(applyOps("a.b.c", ops({ find: ".", replace: "_" })), "a_b_c");
});

test("regex mode with capture groups", () => {
  assert.equal(
    applyOps("temp_kitchen", ops({ find: "^(\\w+)_(\\w+)$", replace: "$2_$1", regex: true })),
    "kitchen_temp"
  );
});

test("invalid regex is a no-op rather than a crash", () => {
  assert.equal(applyOps("abc", ops({ find: "([", replace: "x", regex: true })), "abc");
});

test("ignore case", () => {
  assert.equal(applyOps("Kitchen_Temp", ops({ find: "kitchen", replace: "hall", ignoreCase: true })), "hall_Temp");
});

test("strip prefix only when it actually matches", () => {
  assert.equal(applyOps("old_lamp", ops({ stripPrefix: "old_" })), "lamp");
  assert.equal(applyOps("bold_lamp", ops({ stripPrefix: "old_" })), "bold_lamp");
});

test("strip suffix only when it actually matches", () => {
  assert.equal(applyOps("lamp_2", ops({ stripSuffix: "_2" })), "lamp");
  assert.equal(applyOps("lamp_23", ops({ stripSuffix: "_2" })), "lamp_23");
});

test("documented order: strip runs before add", () => {
  // "rename old_x to new_x" must not become "new_old_x".
  assert.equal(
    applyOps("old_lamp", ops({ stripPrefix: "old_", addPrefix: "new_" })),
    "new_lamp"
  );
});

test("documented order: replace runs before transform", () => {
  assert.equal(
    applyOps("Küche Lampe", ops({ find: " ", replace: "_", transform: "slug" })),
    "kuche_lampe"
  );
});

test("slugify strips accents and collapses separators", () => {
  assert.equal(slugify("Wohnzimmer  Übergröße!"), "wohnzimmer_ubergrosse");
});

test("slugify output is a valid entity object_id", () => {
  const out = slugify("0x00158d00.Temp (Küche) #2");
  assert.match(out, /^[a-z0-9_]+$/);
});

test("title case turns underscores into words", () => {
  assert.equal(applyOps("living_room_temp", ops({ transform: "title" })), "Living Room Temp");
});

test("prefix and suffix together", () => {
  assert.equal(applyOps("lamp", ops({ addPrefix: "kitchen_", addSuffix: "_light" })), "kitchen_lamp_light");
});

test("empty and nullish input are handled", () => {
  assert.equal(applyOps("", ops({ addPrefix: "x_" })), "x_");
  assert.equal(applyOps(null, ops({})), "");
});

test("global replace hits every occurrence", () => {
  assert.equal(applyOps("a_b_a_b", ops({ find: "a", replace: "z" })), "z_b_z_b");
});

/* ---------------------------------------------------------- entity ID rule */
// These must agree with homeassistant.core.valid_entity_id, which the backend
// enforces. A mismatch would let the panel enable Apply for a rejected ID.

test("accepts ordinary entity IDs", () => {
  for (const id of ["sensor.kitchen_temp", "binary_sensor.door_2", "light.k9"]) {
    assert.equal(isValidEntityId(id), true, id);
  }
});

test("rejects uppercase, spaces and dashes", () => {
  for (const id of ["sensor.Kitchen", "sensor.kitchen temp", "sensor.kitchen-temp"]) {
    assert.equal(isValidEntityId(id), false, id);
  }
});

test("rejects leading, trailing and doubled underscores", () => {
  for (const id of ["sensor._x", "sensor.x_", "sensor.a__b", "_sensor.x"]) {
    assert.equal(isValidEntityId(id), false, id);
  }
});

test("rejects a missing or extra domain separator", () => {
  for (const id of ["kitchen_temp", "sensor.a.b", "", ".x", "x."]) {
    assert.equal(isValidEntityId(id), false, JSON.stringify(id));
  }
});

/* -------------------------------------------------------- category payload */

test("setting a category on an entity that had none", () => {
  assert.deepEqual(categoryPayload({}, "helpers:abc"), { helpers: "abc" });
});

test("replacing the displayed category", () => {
  assert.deepEqual(categoryPayload({ helpers: "old" }, "helpers:new"), { helpers: "new" });
});

test("clearing the displayed category", () => {
  assert.deepEqual(categoryPayload({ helpers: "old" }, ""), {});
});

test("categories in other scopes survive an edit", () => {
  // The row only shows the first scope; the rest must not be collateral damage.
  assert.deepEqual(categoryPayload({ helpers: "h1", automation: "a1" }, "helpers:h2"), {
    automation: "a1",
    helpers: "h2",
  });
});

test("categories in other scopes survive a clear", () => {
  assert.deepEqual(categoryPayload({ helpers: "h1", automation: "a1" }, ""), {
    automation: "a1",
  });
});

test("category IDs containing a colon are split on the first one only", () => {
  assert.deepEqual(categoryPayload({}, "helpers:a:b"), { helpers: "a:b" });
});
