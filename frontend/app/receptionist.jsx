"use client";

import { useEffect, useRef, useState } from "react";
import { useVapiChat } from "@vapi-ai/client-sdk-react";

// The hosted entry point can enable voice once it has its own consent backend.
export default function Receptionist({ publicKey, assistantId }) {
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const bottom = useRef(null);
  const chat = useVapiChat({
    enabled: true, publicKey, assistantId,
    assistantOverrides: { variableValues: { gz_handoff: "[]" } },
    onError: () => setNotice("Your message could not be delivered. Please try again."),
  });

  useEffect(() => { bottom.current?.scrollIntoView({ block: "nearest" }); }, [chat.messages]);

  async function send(event) {
    event.preventDefault();
    if (!draft.trim() || chat.isLoading) return;
    setNotice("");
    const text = draft.trim();
    setDraft("");
    await chat.sendMessage(text);
  }

  return <>
    <div className="space-y-3 overflow-y-auto rounded-xl border border-hairline bg-white p-4 text-sm" role="log" aria-label="Conversation">
      <p>By chatting, you agree to our <a href="https://getzelling.com/terms" target="_blank" rel="noreferrer" className="text-navy underline">terms</a> and <a href="https://getzelling.com/privacy" target="_blank" rel="noreferrer" className="text-navy underline">recording policy</a>. How can I help you today?</p>
      {chat.messages.filter(turn => turn.content).map((turn, i) => <p key={i}><strong className="font-medium text-navy">{turn.role === "user" ? "You" : "Gizelle"}</strong><br />{turn.content}</p>)}
      <div ref={bottom} />
    </div>
    {notice && <p role="status">{notice}</p>}
    <form onSubmit={send} className="flex gap-2">
      <label className="sr-only" htmlFor="message">Message</label>
      <input id="message" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Type a message" className="min-w-0 flex-1 rounded border border-hairline bg-white px-3" />
      <button className="min-h-11 rounded bg-bronze px-4 font-medium text-white" disabled={!draft.trim() || chat.isLoading}>Send</button>
    </form>
  </>;
}
