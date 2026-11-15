"use client";

import { useEffect, useRef } from "react";
import Vapi from "@vapi-ai/web";

// Use the web peer for consented rooms so normal room closure is handled before reporting errors.
// onSpeechChange and onPartialTranscript are display-only: they report activity and never change the call.
export function useWebVoice({ session, sessionToken, onCallStart, onCallEnd, onError, onTranscript, onSpeechChange, onPartialTranscript }) {
  const client = useRef(null);
  const completed = useRef(false);
  const announced = useRef(false);
  const expectedEnd = useRef(false);
  const callId = useRef(null);
  const generation = useRef(0);
  const microphone = useRef(null);
  const closeTimer = useRef(null);
  const releaseMicrophone = () => { microphone.current?.getTracks().forEach(track => track.stop()); microphone.current = null; };
  function dispose() {
    clearTimeout(closeTimer.current);
    client.current?.removeAllListeners();
    client.current?.stop().catch(() => {});
    releaseMicrophone();
  }
  const handlers = useRef({});
  handlers.current = { onCallStart, onCallEnd, onError, onTranscript, onSpeechChange, onPartialTranscript };

  function configure(track) {
    const call = new Vapi("local-preview", "/api/widget", {}, {audioSource: track, videoSource: false});
    client.current = call;
    const attempt = generation.current;
    const finish = async () => {
      if (completed.current || attempt !== generation.current) return;
      const wasActive = announced.current;
      let normal = expectedEnd.current;
      completed.current = true; clearTimeout(closeTimer.current); releaseMicrophone();
      if (!normal && wasActive && sessionToken && callId.current) {
        try {
          const r=await fetch("/api/widget/call-status", {method:"POST",
            headers:{"Content-Type":"application/json",Authorization:"Bearer "+sessionToken},
            body:JSON.stringify({call_id:callId.current}),signal:AbortSignal.timeout(5000)});
          if(r.ok) normal=/^assistant-ended-call/.test((await r.json()).ended_reason || "");
        } catch {}
      }
      if(attempt === generation.current) handlers.current.onCallEnd({unexpected:wasActive && !normal});
    };
    const failure = error => {
      if (completed.current) return;
      const detail = [error?.message, error?.error?.message, JSON.stringify(error)].join(" ");
      if (/meeting.*ended|meeting-ended|ejection/i.test(detail)) finish();
      else handlers.current.onError(error);
    };
    call.on("call-start", () => {
      if (announced.current || attempt !== generation.current) return;
      announced.current = true; handlers.current.onCallStart();
    });
    call.on("call-end", finish);
    call.on("error", failure);
    call.on("message", message => {
      if (message.type === "hang" || (message.type === "status-update" && message.status === "ended")) {
        expectedEnd.current = true;
        // The control message can arrive before the last buffered audio packet.
        // Keep playback mounted briefly; explicit visitor hang-up stays immediate.
        if (!closeTimer.current) closeTimer.current = setTimeout(() => {
          finish(); call.stop().catch(failure);
        }, 1500);
      }
      if (message.type === "transcript" && message.transcriptType === "final")
        handlers.current.onTranscript({ role: message.role, text: message.transcript });
      if (message.type === "transcript" && message.transcriptType === "partial")
        handlers.current.onPartialTranscript?.({ role: message.role, text: message.transcript });
    });
    call.on("speech-start", () => handlers.current.onSpeechChange?.(true));
    call.on("speech-end", () => handlers.current.onSpeechChange?.(false));
  }

  useEffect(() => () => dispose(), []);

  return {
    async prepareCall() {
      // Called directly by Agree and call, before any server round trip.
      // Acquire permission only: no audio is sent until consent authorizes a room.
      dispose(); generation.current++; completed.current = false; announced.current = false; expectedEnd.current = false; callId.current = null; closeTimer.current = null;
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("MICROPHONE_UNAVAILABLE");
      let stream, permissionTimer, waiting = true;
      try {
        const permission = navigator.mediaDevices.getUserMedia({audio:true, video:false}).then(value => {
          if (!waiting) { value.getTracks().forEach(track => track.stop()); throw new Error("Late permission"); }
          return value;
        });
        stream = await Promise.race([permission, new Promise((_,reject) => {
          permissionTimer = setTimeout(() => reject(new Error("Permission timed out")), 20000);
        })]);
      } catch (error) {
        throw new Error(error.name === "NotAllowedError" ? "MICROPHONE_DENIED" : "MICROPHONE_UNAVAILABLE");
      } finally { waiting = false; clearTimeout(permissionTimer); }
      const track=stream.getAudioTracks()[0];
      if (!track || track.readyState !== "live") {
        stream.getTracks().forEach(track=>track.stop()); throw new Error("MICROPHONE_UNAVAILABLE");
      }
      microphone.current = stream; configure(track);
    },
    cancelCall() { dispose(); },
    async startCall() {
      if (!client.current || !microphone.current) throw new Error("MICROPHONE_UNAVAILABLE");
      const response = await fetch("/api/widget/call/web", {
        method: "POST", headers: { "Content-Type": "application/json", ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) },
        body: JSON.stringify({ assistantId: session }), signal: AbortSignal.timeout(25000),
      });
      if (!response.ok) throw new Error("Voice unavailable");
      const room=await response.json(); callId.current=room.id;
      let timer;
      try { await Promise.race([client.current.reconnect(room),
        new Promise((resolve,reject)=>{timer=setTimeout(()=>{
          // A setup deadline must never tear down a call that has already started.
          if(announced.current) resolve(); else reject(new Error("VOICE_TIMEOUT"));
        },35000);})]); }
      catch (error) { dispose(); if (!completed.current) throw error; }
      finally { clearTimeout(timer); }
    },
    // Stops sending microphone audio while the call stays open; the visitor's Mute button.
    setMuted(muted) { client.current?.setMuted(muted); },
    async endCall() {
      expectedEnd.current = true;
      clearTimeout(closeTimer.current);
      client.current.end();
      await client.current.stop(); releaseMicrophone();
    },
  };
}
