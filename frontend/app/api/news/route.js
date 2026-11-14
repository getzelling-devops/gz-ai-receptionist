// Local review bridge to `gcloud run services proxy`, bound to loopback.
// Public deployment requires a separate authenticated proxy and abuse controls.
let pending = 0;

export async function POST(request) {
  if (process.env.NODE_ENV !== "development" || process.env.NEWS_PREVIEW_ENABLED !== "true") {
    return new Response(null, { status: 404 });
  }
  const origin = request.headers.get("origin");
  // Next dev may normalize request.url to localhost while the browser uses
  // 127.0.0.1. Compare to the actual, explicitly loopback-only Host header.
  const host = request.headers.get("host") || new URL(request.url).host;
  if (!/^(127\.0\.0\.1|localhost):\d+$/.test(host)
      || (origin && origin !== `http://${host}`)) return new Response(null, { status: 403 });
  let target;
  try {
    target = new URL(process.env.NEWS_BACKEND_URL);
    if (target.protocol !== "http:" || target.hostname !== "127.0.0.1" || target.username || target.password) throw new Error();
  } catch { return Response.json({ error: "Archive unavailable" }, { status: 503 }); }
  if (!request.headers.get("content-type")?.startsWith("application/json")) return new Response(null, { status: 415 });
  if (pending >= 2) return new Response(null, { status: 429 });
  pending += 1;
  try {
    const reader = request.body?.getReader();
    if (!reader) return new Response(null, { status: 400 });
    const pieces = []; let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 8192) { await reader.cancel(); return new Response(null, { status: 413 }); }
      pieces.push(value);
    }
    let body;
    try { body = JSON.parse(Buffer.concat(pieces).toString("utf8")); }
    catch { return new Response(null, { status: 400 }); }
    if (typeof body.question !== "string" || !body.question.trim() || body.question.length > 2000) {
      return new Response(null, { status: 422 });
    }
    const upstream = await fetch(new URL("/chat", target), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: body.question.trim() }), signal: AbortSignal.timeout(65000),
      cache: "no-store",
    });
    if (!upstream.ok) return Response.json({ error: "Archive unavailable" }, { status: 503 });
    return Response.json(await upstream.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return Response.json({ error: "Archive unavailable" }, { status: 503 }); }
  finally { pending -= 1; }
}
