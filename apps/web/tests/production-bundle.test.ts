/** @vitest-environment node */
import { execFileSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, it } from "vitest";

it("reads production assets when the checkout path contains spaces", async () => {
  const root = await mkdtemp(join(tmpdir(), "penge web bundle "));
  const assets = join(root, "dist", "assets");
  const script = join(root, "scripts", "assert-production-bundle.mjs");

  try {
    await mkdir(assets, { recursive: true });
    await mkdir(join(root, "scripts"), { recursive: true });
    await copyFile(new URL("../scripts/assert-production-bundle.mjs", import.meta.url), script);
    await writeFile(join(assets, "index.js"), "synthetic safe bundle");

    expect(() => execFileSync(process.execPath, [script], { encoding: "utf8" })).not.toThrow();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
