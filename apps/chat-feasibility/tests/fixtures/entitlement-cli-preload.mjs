import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { CopilotClient, RuntimeConnection } from "@github/copilot-sdk";

const root = process.env.PENGE_FAKE_ROOT;
const scenario = process.env.PENGE_FAKE_SCENARIO;
if (!root || !["startup", "listing", "delayed"].includes(scenario)) {
    throw new Error("Missing synthetic entitlement test configuration");
}

const runtime = fileURLToPath(new URL("./unresponsive-runtime.mjs", import.meta.url));
const synthetic = new CopilotClient({
    connection: RuntimeConnection.forStdio({ path: process.execPath, args: [runtime] }),
    mode: "empty",
    baseDirectory: root,
    useLoggedInUser: false,
    logLevel: "none",
    onRuntimeProcessSpawned: (pid) => writeFileSync(join(root, "spawned.pid"), String(pid)),
    env: {
        PENGE_FAKE_PID_FILE: join(root, "runtime.pid"),
        PENGE_FAKE_PHASE_FILE: join(root, "phase"),
        PENGE_FAKE_SHUTDOWN: "stubborn",
        PENGE_FAKE_HANDSHAKE: scenario === "listing" ? "complete" : "never",
    },
});

const { start, listModels, stop, forceStop } = CopilotClient.prototype;

CopilotClient.prototype.start = async function () {
    if (this === synthetic) return start.call(this);
    if (scenario === "delayed") {
        writeFileSync(join(root, "start-waiting"), "ready");
        while (!existsSync(join(root, "release-start"))) {
            await new Promise((resolve) => setTimeout(resolve, 20));
        }
    }
    return start.call(synthetic);
};

CopilotClient.prototype.listModels = function () {
    return listModels.call(synthetic);
};

CopilotClient.prototype.stop = function () {
    writeFileSync(join(root, "stop-called"), "ready");
    return stop.call(synthetic);
};

CopilotClient.prototype.forceStop = function () {
    writeFileSync(join(root, "force-stop-called"), "ready");
    return forceStop.call(synthetic);
};
