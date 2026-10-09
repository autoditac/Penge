import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

const forbidden = [
    "AskPengeE2EHarness",
    "Synthetic Penge report lookup",
    "synthetic-session-ask-penge",
];
const assetsDirectory = new URL("../dist/assets/", import.meta.url);
const entries = await readdir(assetsDirectory, { withFileTypes: true });

for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".js")) {
        continue;
    }

    const content = await readFile(join(assetsDirectory.pathname, entry.name), "utf8");
    for (const marker of forbidden) {
        if (content.includes(marker)) {
            throw new Error(`Production bundle contains E2E-only marker: ${marker}`);
        }
    }
}
