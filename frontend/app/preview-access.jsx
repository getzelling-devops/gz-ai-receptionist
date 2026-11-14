"use client";

import { useEffect, useState } from "react";
import Preview from "./widget-preview";

export default function PreviewAccess() {
  const [access, setAccess] = useState(null);
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const [embedded, setEmbedded] = useState(false);
  useEffect(() => {
    if (window.parent === window || location.hash !== "#website") return;
    setEmbedded(true);
    const allowed = ["https://getzelling.com", "https://www.getzelling.com", "https://gz-gz-website.web.app"];
    function receive(e) {
      if (e.source !== parent || !allowed.includes(e.origin)) return;
      if (e.data?.type === "gizelle:unavailable") setError("Please close Gizelle and try again in a moment.");
      if (e.data?.type === "gizelle:session" && typeof e.data.session_token === "string" && typeof e.data.session_id === "string") {
        setAccess({session_id:e.data.session_id, session_token:e.data.session_token});
      }
    }
    window.addEventListener("message", receive);
    for (const origin of allowed) parent.postMessage({type:"gizelle:ready"}, origin);
    return () => window.removeEventListener("message", receive);
  }, []);

  async function enter(event) {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError("");
    try {
      const response = await fetch("/api/widget/session", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
      });
      if (!response.ok) throw new Error();
      setAccess(await response.json()); setCode("");
    } catch { setError("Please check your preview code and try again."); }
    finally { setPending(false); }
  }

  if (access) return <Preview sessionId={access.session_id} sessionToken={access.session_token} />;
  if (embedded) return <main role="status" className="p-6 text-navy">{error || "Opening Gizelle…"}</main>;
  return <main className="mx-auto flex min-h-dvh w-full max-w-[450px] flex-col justify-center gap-4 px-6">
    <p className="text-xs font-medium uppercase tracking-[0.16em] text-bronze">GetZelling</p>
    <h1 className="text-2xl font-medium text-navy">Gizelle preview</h1>
    <form onSubmit={enter} className="space-y-3">
      <label className="block text-sm" htmlFor="preview-code">Preview access code</label>
      <input id="preview-code" type="password" autoComplete="off" value={code} onChange={event => setCode(event.target.value)}
        className="min-h-11 w-full rounded border border-hairline bg-white px-3" />
      <button disabled={pending || !code.trim()} className="min-h-11 rounded bg-bronze px-4 text-sm font-medium text-white">
        {pending ? "Connecting…" : "Open Gizelle"}
      </button>
      {error && <p role="alert" className="text-sm">{error}</p>}
    </form>
  </main>;
}
