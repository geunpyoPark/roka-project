const WebSocket = require("ws");

const PORT = 3001;
const wss = new WebSocket.Server({ port: PORT });

console.log(`🟢 Signaling Server started ws://localhost:${PORT}`);

const clients = new Map();
let userCounter = 1;

wss.on("connection", (ws) => {
    const myId = `user_${userCounter++}`;
    clients.set(myId, ws);

    console.log(`🔵 ${myId} connected`);

    ws.send(JSON.stringify({ type: "welcome", id: myId }));

    ws.on("message", (msg) => {
        try {
            const parsed = JSON.parse(msg);
            const { to, data } = parsed;

            if (to === "all") {
                for (const [cid, cws] of clients.entries()) {
                    if (cws !== ws && cws.readyState === WebSocket.OPEN) {
                        cws.send(JSON.stringify({ from: myId, data }));
                    }
                }
            } else if (clients.has(to)) {
                const target = clients.get(to);
                if (target.readyState === WebSocket.OPEN) {
                    target.send(JSON.stringify({ from: myId, data }));
                }
            }
        } catch (e) {
            console.log("❌ Parse error", e);
        }
    });

    ws.on("close", () => {
        clients.delete(myId);
        console.log(`🔴 ${myId} disconnected`);
    });
});
