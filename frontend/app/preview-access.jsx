"use client";

import { useEffect, useState } from "react";
import Preview from "./widget-preview";

export default function PreviewAccess() {
  const [mounted,setMounted]=useState(false);
  const [access, setAccess] = useState(null);
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const [embedded, setEmbedded] = useState(false);
  useEffect(() => {
    setMounted(true);
    if (location.hash === "#voice" && !window.opener) {
      setEmbedded(true);
      setError("Please open voice from Gizelle on the GetZelling website. This tab could not connect to the original panel.");
      return;
    }
    const voiceTab = location.hash === "#voice" && window.opener;
    if (!voiceTab && (window.parent === window || location.hash !== "#website")) return;
    setEmbedded(true);
    const allowed = voiceTab ? [location.origin] : ["https://getzelling.com", "https://www.getzelling.com", "https://gz-gz-website.web.app"];
    const timeout=setTimeout(()=>setError("Please close this tab or panel and open Gizelle again from the GetZelling website."),12000);
    function receive(e) {
      if (e.source !== (voiceTab ? window.opener : parent) || !allowed.includes(e.origin)) return;
      if (e.data?.type === "gizelle:unavailable") setError("Please close Gizelle and try again in a moment.");
      if ((e.data?.type === (voiceTab ? "gizelle:voice-session" : "gizelle:session")) && typeof e.data.session_token === "string" && typeof e.data.session_id === "string") {
        clearTimeout(timeout);
        setAccess({session_id:e.data.session_id, session_token:e.data.session_token,
          startWithVoice:!!voiceTab||e.data.mode==="voice",initialLanguage:e.data.language==="es"?"es":"en",
          initialHistory:Array.isArray(e.data.history)?e.data.history.slice(-24).filter(t=>["user","assistant"].includes(t?.role)&&typeof t.content==="string").map(t=>({role:t.role,content:t.content.slice(0,1200)})):[]});
      }
    }
    window.addEventListener("message", receive);
    for (const origin of allowed) (voiceTab ? window.opener : parent).postMessage({type:voiceTab ? "gizelle:voice-ready" : "gizelle:ready"}, origin);
    return () => { clearTimeout(timeout); window.removeEventListener("message", receive); };
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

  if (!mounted) return <main role="status" className="min-h-dvh bg-white p-6 text-navy">Opening Gizelle…</main>;
  if (access) return <Preview sessionId={access.session_id} sessionToken={access.session_token} startWithVoice={access.startWithVoice} initialLanguage={access.initialLanguage} initialHistory={access.initialHistory} />;
  if (embedded) return <main role="status" className="min-h-dvh bg-white p-6 text-navy">{error || "Opening Gizelle…"}</main>;
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
