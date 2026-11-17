import { writeFileSync } from "node:fs";

writeFileSync(process.env.PENGE_FAKE_PID_FILE, String(process.pid));

if (process.env.PENGE_FAKE_SHUTDOWN === "stubborn") {
    process.on("SIGTERM", () => {});
    setInterval(() => {}, 1_000);
}

let buffered = Buffer.alloc(0);

function respond(id, result) {
    const body = JSON.stringify({ jsonrpc: "2.0", id, result });
    process.stdout.write(`Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`);
}

process.stdin.on("data", (chunk) => {
    buffered = Buffer.concat([buffered, chunk]);
    while (true) {
        const headerEnd = buffered.indexOf("\r\n\r\n");
        if (headerEnd < 0) return;
        const match = /^Content-Length: (\d+)/i.exec(buffered.subarray(0, headerEnd).toString());
        if (!match) throw new Error("Missing synthetic JSON-RPC content length");
        const length = Number(match[1]);
        const messageEnd = headerEnd + 4 + length;
        if (buffered.length < messageEnd) return;
        const request = JSON.parse(buffered.subarray(headerEnd + 4, messageEnd).toString());
        buffered = buffered.subarray(messageEnd);

        if (request.method === "connect" && process.env.PENGE_FAKE_HANDSHAKE === "never") {
            continue;
        } else if (request.method === "connect") {
            respond(request.id, { protocolVersion: 3 });
        } else if (
            request.method === "runtime.shutdown" &&
            process.env.PENGE_FAKE_SHUTDOWN === "graceful"
        ) {
            respond(request.id, {});
        }
    }
});
