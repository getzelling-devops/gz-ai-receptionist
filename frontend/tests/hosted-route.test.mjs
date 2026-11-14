import test from "node:test";
import assert from "node:assert/strict";
import {POST} from "../app/api/widget/[...path]/route.js";

test("hosted preview forwards the visitor bearer and keeps consent out of third-party cookies", async t => {
  const before = {...process.env};
  process.env.WIDGET_HOSTED_PREVIEW = "true";
  process.env.WIDGET_BACKEND_URL = "https://backend.example";
  t.after(() => {
    for (const name of ["WIDGET_HOSTED_PREVIEW", "WIDGET_BACKEND_URL"]) {
      if (before[name] === undefined) delete process.env[name]; else process.env[name] = before[name];
    }
  });
  const fetch = t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "https://backend.example/voice");
    assert.equal(options.headers.Authorization, "Bearer visitor-session");
    assert.deepEqual(JSON.parse(options.body), {assistantId: "server-issued-session"});
    return Response.json({webCallUrl: "https://room.example"});
  });
  const make = origin => new Request("http://localhost:8080/api/widget/call/web", {
    method: "POST", headers: {Host: "widget.example", Origin: origin,
      Authorization: "Bearer visitor-session", "Content-Type": "application/json"},
    body: JSON.stringify({assistantId: "server-issued-session"}),
  });
  const context = {params: Promise.resolve({path: ["call", "web"]})};
  assert.equal((await POST(make("https://untrusted.example"), context)).status, 403);
  assert.equal(fetch.mock.callCount(), 0);
  const reply = await POST(make("https://widget.example"), context);
  assert.equal(reply.status, 200);
  assert.equal(reply.headers.get("set-cookie"), null);
});
