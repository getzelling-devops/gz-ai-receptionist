"use client";

import { useEffect, useRef } from "react";
import Vapi from "@vapi-ai/web";

// Use the web peer for consented rooms so normal room closure is handled before reporting errors.
export function useWebVoice({ session, sessionToken, onCallStart, onCallEnd, onError, onTranscript }) {
  const client = useRef(null);
  const completed = useRef(false);
  const handlers = useRef({});
  handlers.current = { onCallStart, onCallEnd, onError, onTranscript };

  useEffect(() => {
    const call = new Vapi("local-preview", "/api/widget");
    client.current = call;
    const finish = () => { completed.current = true; handlers.current.onCallEnd(); };
    const failure = error => {
      if (completed.current) return;
      const detail = [error?.message, error?.error?.message, JSON.stringify(error)].join(" ");
      if (/meeting.*ended|meeting-ended|ejection/i.test(detail)) finish();
      else handlers.current.onError(error);
    };
    call.on("call-start", () => handlers.current.onCallStart());
    call.on("call-end", finish);
    call.on("error", failure);
    call.on("message", message => {
      if (message.type === "hang" || (message.type === "status-update" && message.status === "ended")) {
        finish();
        call.stop().catch(failure);
      }
      if (message.type === "transcript" && message.transcriptType === "final")
        handlers.current.onTranscript({ role: message.role, text: message.transcript });
    });
    return () => { call.removeAllListeners(); call.stop().catch(() => {}); };
  }, []);

  return {
    async startCall() {
      completed.current = false;
      const response = await fetch("/api/widget/call/web", {
        method: "POST", headers: { "Content-Type": "application/json", ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) },
        body: JSON.stringify({ assistantId: session }),
      });
      if (!response.ok) throw new Error("Voice unavailable");
      try { await client.current.reconnect(await response.json()); }
      catch (error) { if (!completed.current) throw error; }
    },
    async endCall() {
      client.current.end();
      await client.current.stop();
    },
  };
}
