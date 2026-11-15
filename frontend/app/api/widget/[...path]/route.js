// This loopback bridge is exclusive to the private operator preview.
const paths = new Map([["session", "session"], ["chat", "chat"], ["call-status", "call-status"], ["consent", "consent"], ["call/web", "voice"]]);
let pending = 0;

export async function POST(request, context) {
  const hosted = process.env.WIDGET_HOSTED_PREVIEW === "true";
  if (!hosted && (process.env.NODE_ENV !== "development" || process.env.NEWS_PREVIEW_ENABLED !== "true"))
    return new Response(null, { status: 404 });
  const host = request.headers.get("host");
  const expected = hosted ? `https://${host}` : `http://${host}`;
  if ((!hosted && !/^(localhost|127\.0\.0\.1):\d+$/.test(host)) || request.headers.get("origin") !== expected)
    return new Response(null, { status: 403 });
  const { path } = await context.params;
  const action = paths.get(path.join("/"));
  if (!action) return new Response(null, { status: 404 });
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json")
    return new Response(null, { status: 415 });
  if (pending >= 2) return new Response(null, { status: 429 });
  pending++;
  try {
    const reader = request.body?.getReader();
    if (!reader) return new Response(null, { status: 400 });
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 140000) { await reader.cancel(); return new Response(null, { status: 413 }); }
      chunks.push(value);
    }
    let body;
    try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch { return new Response(null, { status: 400 }); }
    if (!hosted && action === "voice") {
      const cookie = request.headers.get("cookie") || "";
      const grant = /(?:^|; )gz_web_grant=([a-f0-9-]{36})\.([\w-]{43})(?:;|$)/.exec(cookie);
      if (!grant || body?.assistantId !== grant[1]) return new Response(null, { status: 403 });
      body = { session: grant[1], ticket: grant[2] };
    }
    const response = await fetch(`${hosted ? process.env.WIDGET_BACKEND_URL : "http://127.0.0.1:8092"}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json", ...(hosted ? {Authorization: request.headers.get("authorization") || ""} : {}) }, body: JSON.stringify(body),
      cache: "no-store", signal: AbortSignal.timeout(75000),
    });
    if (!response.ok) return new Response(null, { status: response.status < 500 ? response.status : 503 });
    const data = await response.json();
    const headers = { "Cache-Control": "no-store" };
    const cookieOptions = "Path=/api/widget/call/web; HttpOnly; SameSite=Strict";
    if (!hosted && action === "consent") {
      headers["Set-Cookie"] = `gz_web_grant=${body.session}.${data.ticket}; Max-Age=180; ${cookieOptions}`;
      return Response.json({ accepted: true }, { headers });
    }
    if (!hosted && action === "voice") headers["Set-Cookie"] = `gz_web_grant=; Max-Age=0; ${cookieOptions}`;
    return Response.json(data, { headers });
  } catch { return new Response(null, { status: 503 }); }
  finally { pending--; }
}
