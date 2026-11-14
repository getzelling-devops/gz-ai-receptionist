import test from "node:test";
import assert from "node:assert/strict";
import { POST } from "../app/api/widget/[...path]/route.js";

const session = "ac22068d-47ea-4eb1-b3fa-026fc142bafd";
const ticket = "t".repeat(43);
function post(path, body, headers = {}) {
  return POST(new Request("http://localhost:3108/api/widget/" + path, {
    method: "POST", headers: { host: "localhost:3108", origin: "http://localhost:3108",
      "content-type": "application/json", ...headers }, body: JSON.stringify(body),
  }), { params: Promise.resolve({ path: path.split("/") }) });
}

test("preview voice requires a same-origin, server-issued consent grant", async t => {
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.endsWith("/consent")) return Response.json({ ticket });
    assert.equal(url, "http://127.0.0.1:8092/voice");
    assert.deepEqual(JSON.parse(init.body), { session, ticket });
    return Response.json({ webCallUrl: "https://example.test/room" });
  });
  process.env.NEWS_PREVIEW_ENABLED = "true";
  process.env.NODE_ENV = "production";
  assert.equal((await post("consent", {})).status, 404);
  process.env.NODE_ENV = "development";
  assert.equal((await post("call/web", { accepted: true })).status, 403);
  assert.equal((await post("consent", {}, { origin: "https://example.org" })).status, 403);
  assert.equal(globalThis.fetch.mock.callCount(), 0);
  const consent = await post("consent", { accepted: true, session });
  assert.deepEqual(await consent.json(), { accepted: true });
  const cookie = consent.headers.get("set-cookie");
  assert.match(cookie, /HttpOnly; SameSite=Strict/);
  assert.equal((await post("call/web", { assistantId: "different-tab" }, { cookie: cookie.split(";")[0] })).status, 403);
  const join = await post("call/web", { assistantId: session }, { cookie: cookie.split(";")[0] });
  assert.equal(join.status, 200);
  assert.match(join.headers.get("set-cookie"), /Max-Age=0/);
});
