import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { POST } from "../app/api/news/route.js";

const old = { node: process.env.NODE_ENV, enabled: process.env.NEWS_PREVIEW_ENABLED,
  url: process.env.NEWS_BACKEND_URL, fetch: globalThis.fetch };

afterEach(() => {
  for (const [name, value] of [["NODE_ENV", old.node], ["NEWS_PREVIEW_ENABLED", old.enabled], ["NEWS_BACKEND_URL", old.url]]) {
    if (value === undefined) delete process.env[name]; else process.env[name] = value;
  }
  globalThis.fetch = old.fetch;
});

function configure() {
  process.env.NODE_ENV = "development";
  process.env.NEWS_PREVIEW_ENABLED = "true";
  process.env.NEWS_BACKEND_URL = "http://127.0.0.1:8081";
}
function request(body, origin = "http://localhost:3000") {
  return new Request("http://localhost:3000/api/news", { method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin }, body: JSON.stringify(body) });
}

test("the review bridge cannot be enabled in production", async () => {
  configure(); process.env.NODE_ENV = "production";
  assert.equal((await POST(request({ question: "July condos" }))).status, 404);
});

test("cross-origin requests cannot spend inference", async () => {
  configure(); let calls = 0; globalThis.fetch = () => { calls++; throw new Error(); };
  assert.equal((await POST(request({ question: "July condos" }, "https://another.example"))).status, 403);
  assert.equal(calls, 0);
});

test("only the configured loopback proxy can be used", async () => {
  configure(); process.env.NEWS_BACKEND_URL = "https://another.example";
  assert.equal((await POST(request({ question: "July condos" }))).status, 503);
});

test("the actual request body is bounded", async () => {
  configure();
  assert.equal((await POST(request({ question: "x", extra: "x".repeat(9000) }))).status, 413);
  assert.equal((await POST(request({ question: "x".repeat(2001) }))).status, 422);
});

test("the proxy forwards only the question and suppresses caching", async () => {
  configure(); let sent;
  globalThis.fetch = async (url, options) => {
    sent = { url: url.toString(), ...options };
    return Response.json({ answer: "Archived context", citations: [] });
  };
  const response = await POST(request({ question: " July condos ", collection: "leads", model: "other" }));
  assert.equal(response.status, 200);
  assert.equal(sent.url, "http://127.0.0.1:8081/chat");
  assert.deepEqual(JSON.parse(sent.body), { question: "July condos" });
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("Next dev localhost normalization preserves the actual loopback origin", async () => {
  configure();
  globalThis.fetch = async () => Response.json({ answer: "Archived context", citations: [] });
  const req = new Request("http://localhost:3108/api/news", { method: "POST",
    headers: { "Content-Type": "application/json", Host: "127.0.0.1:3108", Origin: "http://127.0.0.1:3108" },
    body: JSON.stringify({ question: "July condos" }) });
  assert.equal((await POST(req)).status, 200);
});

test("an upstream error does not expose provider details", async () => {
  configure();
  globalThis.fetch = async () => new Response("private provider details", { status: 403 });
  const response = await POST(request({ question: "July condos" }));
  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /private provider details/);
});
