/* global URL */
import assert from "node:assert/strict";
import fs from "node:fs";

const companionSource = fs.readFileSync(new URL("./CompanionWindow.tsx", import.meta.url), "utf8");

assert.match(
  companionSource,
  /type CompanionMode = "expanded" \| "compact"/,
  "CompanionWindow should model expanded and compact modes.",
);

assert.match(
  companionSource,
  /cmd_set_companion_mode/,
  "CompanionWindow should call the Tauri companion mode resize command.",
);

assert.match(
  companionSource,
  /setMode\("compact"\)/,
  "The minimize action should enter compact mode.",
);

assert.match(
  companionSource,
  /setMode\("expanded"\)/,
  "The compact pill should be able to expand back.",
);

assert.doesNotMatch(
  companionSource,
  /onClick=\{\(\) => setNotice\(null\)\}/,
  "The minimize button must not merely clear the current notice.",
);
