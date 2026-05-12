/* global URL, process */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const sourcePath = new URL("./desktopDelivery.ts", import.meta.url);
const source = fs.readFileSync(sourcePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;

const tempPath = path.join(os.tmpdir(), `desktopDelivery-${process.pid}-${Date.now()}.mjs`);
fs.writeFileSync(tempPath, compiled, "utf8");

try {
  const { createDesktopDeliveryNotice } = await import(pathToFileURL(tempPath).href);

  assert.deepEqual(
    createDesktopDeliveryNotice({ title: "", message: "done" }, 123),
    {
      id: "desktop-delivery-123",
      title: "Scheduled task",
      preview: "done",
    },
  );

  assert.equal(
    createDesktopDeliveryNotice({ title: "Morning report", message: "x".repeat(170) }, 456)
      .preview,
    `${"x".repeat(140)}...`,
  );
} finally {
  fs.rmSync(tempPath, { force: true });
}
