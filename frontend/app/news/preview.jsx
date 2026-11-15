"use client";

import { useEffect, useRef, useState } from "react";
import MicrophoneHelp from "../microphone-help";
import { useWebVoice } from "../web-voice";
import { Icon } from "../icons";

// Topic chips show a short label and send a fuller question to the real chat backend.
const copy = {
  en: {
    label: "Your question", send: "Send", sources: "View sources", published: "Published",
    examples: [
      { label: "Selling with GetZelling", question: "How does GetZelling help me sell my home?" },
      { label: "Our listing fees", question: "What are GetZelling’s listing fees?" },
      { label: "The GetZelling app", question: "How does the GetZelling client app help me during a sale?" },
      { label: "Luxury homes for sale", question: "Can you help me find luxury homes for sale in South Florida?" },
      { label: "Ask about Miami condo trends", question: "What did July 2025 reporting say about Miami condos?" },
      { label: "Miami home values", question: "What do your Market insights say about Miami home values?" },
      { label: "Book a Listing Presentation", question: "I would like to schedule a Listing Presentation for my property." },
      { label: "Miami real estate market", question: "What do your Market insights say about the Miami real estate market in 2025?" },
      { label: "Arrange a video call with a GetZelling agent", question: "Can you help me arrange a video call with a GetZelling agent?" },
    ],
  },
  es: {
    label: "Tu pregunta", send: "Enviar", sources: "Ver fuentes", published: "Publicado",
    examples: [
      { label: "Vender con GetZelling", question: "¿Cómo me ayuda GetZelling a vender mi propiedad?" },
      { label: "Nuestras comisiones", question: "¿Cuáles son los honorarios de GetZelling para vender mi propiedad?" },
      { label: "La app de GetZelling", question: "¿Cómo me ayuda la aplicación de GetZelling durante la venta?" },
      { label: "Casas de lujo en venta", question: "¿Pueden ayudarme a encontrar casas de lujo en venta en el sur de Florida?" },
      { label: "Pregunta sobre tendencias de condominios en Miami", question: "¿Qué decía la cobertura de julio de 2025 sobre los condominios en Miami?" },
      { label: "Valores de viviendas en Miami", question: "¿Qué dicen sus análisis de mercado sobre los valores de las viviendas en Miami?" },
      { label: "Agendar una presentación de venta", question: "Me gustaría agendar un Plan de venta para mi propiedad." },
      { label: "Mercado inmobiliario de Miami", question: "¿Qué información tiene sobre el mercado inmobiliario de Miami en 2025?" },
      { label: "Coordinar una videollamada con un agente de GetZelling", question: "¿Pueden ayudarme a coordinar una videollamada con un agente de GetZelling?" },
    ],
  },
};

const widgetCopy = {
  en: {
    sub: "AI assistant", talkLive: "Talk live", contact: "Email Gizelle", clear: "Clear conversation", more: "More options", close: "Minimize Gizelle", language: "Language",
    greet: "Hello, I am Gizelle. Ask me about buying, selling, or the Miami market. You can type, or talk with me live.",
    typeTitle: "Type a message", typeDesc: "Chat by text, at your own pace.",
    talkDesc: "A real-time voice conversation, like a phone call, with a live transcript.", tryTopic: "Try a topic",
    placeholder: "Ask Gizelle anything", thinking: "Gizelle is replying…",
    permTitle: "Start a voice call with Gizelle",
    permBody: "You speak and Gizelle answers out loud, in real time. Everything you both say appears here as a live transcript.",
    consent: "GetZelling will record and transcribe this call for service and training. Do you agree?",
    permMic: "Your browser will ask for microphone access.", agree: "Agree and call", decline: "Continue typing",
    permission: "Look for your browser’s microphone prompt and choose Allow…", connecting: "Connecting…",
    voiceCall: "Live voice call", listening: "Listening", speaking: "Gizelle is speaking", muted: "You are muted",
    mute: "Mute", unmute: "Unmute", end: "End call", callHint: "The transcript updates live as you both speak.",
    started: "Voice call started", ended: "Call ended", elapsed: "Call time",
    failure: "Gizelle is unavailable. Please try again or email the team.",
    disclosure: "By chatting, you agree to our", terms: "terms", and: "and", privacy: "recording policy",
  },
  es: {
    sub: "Asistente de IA", talkLive: "Hablar en vivo", contact: "Enviar email a Gizelle", clear: "Borrar conversación", more: "Más opciones", close: "Minimizar Gizelle", language: "Idioma",
    greet: "Hola, soy Gizelle. Pregúntame sobre comprar, vender o el mercado de Miami. Puedes escribir o hablar conmigo en vivo.",
    typeTitle: "Escribir un mensaje", typeDesc: "Chatea por texto, a tu ritmo.",
    talkDesc: "Una conversación de voz en tiempo real, como una llamada, con transcripción en vivo.", tryTopic: "Prueba un tema",
    placeholder: "Pregúntale a Gizelle", thinking: "Gizelle está respondiendo…",
    permTitle: "Iniciar una llamada de voz con Gizelle",
    permBody: "Tú hablas y Gizelle responde en voz alta, en tiempo real. Todo lo que digan aparece aquí como transcripción en vivo.",
    // The consent wording is recorded with each call; keep it unchanged unless the disclosure version changes.
    consent: "GetZelling grabará y transcribirá esta llamada para atención y capacitación. ¿Está de acuerdo?",
    permMic: "Tu navegador pedirá acceso al micrófono.", agree: "Aceptar y llamar", decline: "Seguir escribiendo",
    permission: "Busca la solicitud de micrófono del navegador y elige Permitir…", connecting: "Conectando…",
    voiceCall: "Llamada de voz en vivo", listening: "Escuchando", speaking: "Gizelle está hablando", muted: "Estás en silencio",
    mute: "Silenciar", unmute: "Activar micrófono", end: "Terminar llamada", callHint: "La transcripción se actualiza en vivo mientras hablan.",
    started: "Llamada de voz iniciada", ended: "Llamada terminada", elapsed: "Duración de la llamada",
    failure: "Gizelle no está disponible. Inténtalo de nuevo o escribe al equipo.",
    disclosure: "Al chatear, aceptas nuestros", terms: "términos", and: "y la", privacy: "política de grabación",
  },
};

const clock = seconds => Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");

// The voice transcriber sometimes spells the assistant's introduction “Giselle”.
function cleanAssistant(text) {
  return text.replace(/\b(this is|I’m|I'm|soy) Giselle\b/gi, "$1 Gizelle")
    .replace(/\b(?:giselle|gizelle)@getselling\.com\b/gi, "gizelle@getzelling.com")
    .replace(/\bgiselle@getzelling\.com\b/gi, "gizelle@getzelling.com")
    .replace(/\bgetselling\b/gi, "GetZelling");
}

function Bubble({ role, faded, children }) {
  const assistant = role === "assistant";
  return <div className={`max-w-[84%] whitespace-pre-wrap px-3.5 py-2.5 text-[14.5px] leading-[1.55] [text-wrap:pretty] ${assistant
    ? "self-start rounded-[12px_12px_12px_4px] bg-paper text-ink" : "self-end rounded-[12px_12px_4px_12px] bg-navy text-white"}`}
    style={faded ? { opacity: 0.6 } : undefined}>{children}</div>;
}

function Divider({ children }) {
  return <div className="flex items-center gap-2.5 py-1.5 text-xs text-tertiary">
    <span className="h-px flex-1 bg-hairline" /><span>{children}</span><span className="h-px flex-1 bg-hairline" />
  </div>;
}

function Waveform({ speaking, paused }) {
  return <div aria-hidden="true" className="flex h-11 items-center gap-1">
    {Array.from({ length: 28 }, (_, i) => <span key={i} className="gz-wave-bar w-[3px] rounded-[2px]" style={{
      height: 10 + ((i * 37) % 30), opacity: paused ? 0.35 : 1, transition: "background-color .33s ease",
      background: speaking ? "var(--color-bronze-light)" : "var(--color-midnight-text)",
      animationDuration: `${0.7 + (i % 5) * 0.12}s`, animationDelay: `${-(i % 7) * 0.13}s`,
      animationPlayState: paused ? "paused" : "running",
    }} />)}
  </div>;
}

function Terms({ w, className = "" }) {
  return <p className={`flex flex-wrap gap-x-1 text-[11.5px] leading-4 text-tertiary ${className}`}>
    <span>{w.disclosure}</span>
    <a className="underline underline-offset-[3px]" href="https://getzelling.com/terms" target="_blank" rel="noreferrer">{w.terms}</a>
    <span>{w.and}</span>
    <a className="underline underline-offset-[3px]" href="https://getzelling.com/privacy" target="_blank" rel="noreferrer">{w.privacy}</a>
  </p>;
}

export default function NewsPreview({ sessionToken, sessionId, startWithVoice = false, initialHistory = [], initialLanguage = "en" }) {
  const [voiceState, setVoiceState] = useState(startWithVoice ? "consent" : "text");
  const [session, setSession] = useState(() => sessionId || crypto.randomUUID());
  const [micIssue,setMicIssue] = useState(false);
  const [isEmbedded,setIsEmbedded] = useState(false);
  const voiceTab=useRef(null);
  useEffect(()=>setIsEmbedded(window.parent!==window),[]);
  const previous = useRef(null);
  const voiceLock = useRef(false);
  const requestLock = useRef(false);
  const [language, setLanguage] = useState(initialLanguage);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState(initialHistory);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Display-only call state for the voice screen.
  const [menuOpen, setMenuOpen] = useState(false);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [partial, setPartial] = useState(null);
  const [callSeconds, setCallSeconds] = useState(0);
  const callStarted = useRef(null);
  const scroller = useRef(null);
  const input = useRef(null);
  const menu = useRef(null);
  const c = copy[language];
  const w = widgetCopy[language];
  const locked = busy || voiceState !== "text";

  function resetCallDisplay() { setMuted(false); setSpeaking(false); setPartial(null); }
  function callEndedDisplay() {
    if (callStarted.current === null) return;
    const seconds = Math.floor((Date.now() - callStarted.current) / 1000);
    callStarted.current = null; resetCallDisplay();
    setTurns(items => [...items, { divider: "ended", seconds }]);
  }

  const voice = useWebVoice({
    session, sessionToken,
    onCallStart: () => {
      resetCallDisplay(); callStarted.current = Date.now(); setCallSeconds(0);
      setTurns(items => [...items, { divider: "started" }]);
      setVoiceState("active");
    },
    onCallEnd: () => { callEndedDisplay(); setError(""); previous.current = null; voiceLock.current = false; setVoiceState("text"); },
    onError: error => {
      if (/meeting.*ended|meeting-ended|ejection/i.test([error?.message, JSON.stringify(error)].join(" "))) {
        callEndedDisplay(); previous.current = null; voiceLock.current = false; setVoiceState("text"); setError(""); return;
      }
      if (["audio-processing-setup-error", "audio-processor-recovery-error", "audio-observer-setup-error"].includes(error?.type)) return;
      callEndedDisplay(); voiceLock.current = false; setVoiceState("text"); setError(w.failure);
    },
    onTranscript: ({role, text}) => {
      const content = role === "assistant" ? cleanAssistant(text) : text;
      setPartial(current => current?.role === role ? null : current);
      setTurns(items => [...items, {role, content, voice: true}]);
    },
    onPartialTranscript: ({role, text}) => setPartial({ role, content: role === "assistant" ? cleanAssistant(text) : text }),
    onSpeechChange: setSpeaking,
  });

  function context() {
    return { session, language, history: turns.filter(turn => !turn.divider).slice(-24).map(({ role, content }) =>
      ({ role, content: content.slice(0, 1200) })) };
  }

  function openVoiceTab() {
    const tab=window.open(location.origin+"/#voice","gizelle-voice");
    if (!tab) setError(language==="es"?"Permite abrir una pestaña para continuar, o sigue escribiendo.":"Allow a new tab to open, or continue typing here.");
    voiceTab.current=tab;
  }

  useEffect(()=>{
    const relay=e=>{
      if(e.origin!==location.origin || e.source!==voiceTab.current || e.data?.type!=="gizelle:voice-ready") return;
      e.source.postMessage({type:"gizelle:voice-session",session_id:session,session_token:sessionToken,
        language,history:context().history},location.origin);
    };
    window.addEventListener("message",relay);
    return ()=>window.removeEventListener("message",relay);
  },[session,sessionToken,language,turns]);

  async function agree() {
    if (voiceLock.current) return;
    voiceLock.current = true; setError(""); setMicIssue(false); setVoiceState("permission");
    try {
      await voice.prepareCall();
      setVoiceState("connecting");
      const response = await fetch("/api/widget/consent", { method: "POST",
        headers: { "Content-Type": "application/json", ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) },
        body: JSON.stringify({ ...context(), version: "web-voice-v1", accepted: true }) });
      if (!response.ok) throw new Error();
      await voice.startCall();
    } catch (failure) {
      voice.cancelCall();
      voiceLock.current = false;
      const microphoneFailure = /^MICROPHONE_/.test(failure?.message || "");
      setMicIssue(microphoneFailure);
      setVoiceState(microphoneFailure ? "consent" : "text");
      if (!microphoneFailure && !/meeting.*ended|meeting-ended|ejection/i.test(String(failure?.message || failure)))
        setError(w.failure);
    }
  }

  // The website launcher can open the panel in chat or at the voice consent step.
  // The message only changes which step is shown; starting a call still needs Agree and call.
  useEffect(() => {
    const show = e => {
      if (e.source !== window.parent || e.data?.type !== "gizelle:show" || !["voice", "chat"].includes(e.data.mode)) return;
      setMenuOpen(false);
      if (e.data.mode === "voice") setVoiceState(state => { if (state === "text") { setMicIssue(false); return "consent"; } return state; });
      else { setVoiceState(state => state === "consent" ? "text" : state); setTimeout(() => input.current?.focus(), 50); }
    };
    window.addEventListener("message", show);
    return () => window.removeEventListener("message", show);
  }, []);

  useEffect(() => {
    if (voiceState !== "active") return;
    const timer = setInterval(() => {
      if (callStarted.current !== null) setCallSeconds(Math.floor((Date.now() - callStarted.current) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [voiceState]);

  // Scroll to the newest message only when the conversation changes, so visitors can scroll back freely.
  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight; }, [turns, busy, partial]);

  useEffect(() => {
    if (!menuOpen) return;
    const outside = e => { if (!menu.current?.contains(e.target)) setMenuOpen(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [menuOpen]);

  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
    el.style.overflowY = el.scrollHeight > 120 ? "auto" : "hidden";
  }, [question, voiceState]);

  const grouped = [];
  for (const turn of turns) {
    const last = grouped.at(-1);
    if (turn.voice && last?.voice && turn.role === last.role) last.content += " " + turn.content;
    else grouped.push({ ...turn });
  }

  for (const turn of grouped) {
    if (turn.voice && turn.role === "assistant") {
      turn.content = turn.content
        .replace(/7[\s.,-]*8[\s.,-]*6[\s.,-]*9[\s.,-]*7[\s.,-]*7[\s.,-]*2[\s.,-]*7[\s.,-]*7[\s.,-]*4\b/g, "786-977-2774")
        .replace(/Have\.\s+A wonderful day/gi, "Have a wonderful day");
    }
  }

  async function ask(event, override) {
    event?.preventDefault();
    const text = (override ?? question).trim();
    if (requestLock.current || locked || !text) return;
    requestLock.current = true;
    setQuestion(""); setBusy(true); setError("");
    setTurns(previous => [...previous, { role: "user", content: text }]);
    try {
      const response = await fetch("/api/widget/chat", {
        method: "POST", headers: { "Content-Type": "application/json", ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) },
        body: JSON.stringify({ ...context(), previous: previous.current, question: text }),
      });
      if (!response.ok) throw new Error("Unavailable");
      const data = await response.json();
      if (typeof data.answer !== "string" || (data.citations && !Array.isArray(data.citations))) throw new Error("Invalid response");
      previous.current = data.previous;
      setTurns(previous => [...previous, { role: "assistant", content: data.answer, citations: data.citations }]);
    } catch {
      setError(w.failure); setQuestion(text);
      setTurns(previous => previous.at(-1)?.role === "user" && previous.at(-1)?.content === text
        ? previous.slice(0, -1) : previous);
    }
    finally { requestLock.current = false; setBusy(false); input.current?.focus(); }
  }

  function askForCall() { setMenuOpen(false); setError(""); setMicIssue(false); setVoiceState("consent"); }
  function chooseTyping() {
    if (voiceState === "consent") { setMicIssue(false); setVoiceState("text"); }
    setTimeout(() => input.current?.focus(), 0);
  }
  function clearConversation() {
    setMenuOpen(false); setTurns([]); previous.current = null;
    if (!sessionId) setSession(crypto.randomUUID()); setError("");
  }
  function minimize() { setMenuOpen(false); window.parent.postMessage({ type: "gizelle:minimize" }, "*"); }
  function toggleMute() { const next = !muted; voice.setMuted(next); setMuted(next); }

  const inCall = voiceState === "active";
  const consentStep = ["consent", "permission", "connecting"].includes(voiceState);
  const hasConversation = turns.some(turn => !turn.divider);
  const showWelcome = !inCall && !hasConversation && !busy;
  const lastGroup = grouped.at(-1);
  const partialInline = partial && lastGroup?.voice && lastGroup.role === partial.role;
  const callStatus = speaking ? w.speaking : muted ? w.muted : w.listening;

  const shell = isEmbedded ? "h-dvh w-full" : "min-h-dvh w-full bg-paper sm:flex sm:items-center sm:justify-center sm:p-6";
  const card = isEmbedded ? "h-full w-full"
    : "h-dvh w-full sm:h-[min(680px,calc(100dvh-48px))] sm:w-[420px] sm:rounded-[12px] sm:border sm:border-hairline sm:shadow-card";

  return <main className={shell} lang={language}
    onKeyDown={event => {
      if (event.key !== "Escape") return;
      if (menuOpen) { event.preventDefault(); setMenuOpen(false); }
      else if (isEmbedded) { event.preventDefault(); minimize(); }
    }}>
    <div className={`gz-panel-in flex flex-col overflow-hidden bg-white text-ink ${card}`}>

    {!inCall && <header className="relative flex flex-none items-center gap-2 border-b border-hairline py-[14px] pl-4 pr-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h1 className="text-[17px] font-medium leading-[1.2] text-navy">Gizelle</h1>
        <p className="truncate text-xs text-tertiary">{w.sub}</p>
      </div>
      <button type="button" onClick={askForCall} disabled={busy || voiceState === "permission" || voiceState === "connecting"}
        aria-pressed={consentStep}
        className="gz-secondary gz-ease flex h-8 items-center gap-[7px] whitespace-nowrap rounded-[4px] px-3 text-[13px] font-medium">
        <Icon name="phone" size={15} /><span>{w.talkLive}</span>
      </button>
      <div role="group" aria-label={w.language} className="flex overflow-hidden rounded-[4px] border border-hairline">
        {["en", "es"].map(value => <button key={value} type="button" disabled={locked}
          aria-pressed={language === value} onClick={() => { setLanguage(value); setError(""); }}
          className={`gz-ease gz-solid h-[30px] w-[30px] text-xs font-medium ${language === value ? "bg-navy text-white" : "bg-white text-muted"}`}>
          {value === "en" ? "EN" : "ES"}
        </button>)}
      </div>
      <div ref={menu} className="contents">
        <button type="button" aria-label={w.more} aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}
          className="gz-ease flex h-8 w-8 items-center justify-center rounded-[4px] text-muted hover:bg-paper">
          <Icon name="more" size={18} />
        </button>
        {menuOpen && <div role="menu" className="absolute right-11 top-[52px] z-10 flex min-w-[200px] flex-col rounded-[8px] border border-hairline bg-white p-1.5 shadow-card">
          <a role="menuitem" href="mailto:gizelle@getzelling.com" onClick={() => setMenuOpen(false)}
            className="gz-ease flex items-center gap-2.5 rounded-[4px] p-2.5 text-sm text-ink hover:bg-paper">
            <Icon name="mail" /><span>{w.contact}</span>
          </a>
          <button role="menuitem" type="button" disabled={locked} onClick={clearConversation}
            className="gz-ease flex items-center gap-2.5 rounded-[4px] p-2.5 text-left text-sm text-ink hover:bg-paper">
            <Icon name="trash" /><span>{w.clear}</span>
          </button>
        </div>}
      </div>
      {isEmbedded && <button type="button" aria-label={w.close} onClick={minimize}
        className="gz-ease flex h-9 w-9 flex-none items-center justify-center rounded-full border border-gold-hover bg-white text-navy hover:border-bronze">
        <Icon name="close" />
      </button>}
    </header>}

    {inCall && <header className="gz-midnight flex flex-none flex-col justify-center gap-[14px] bg-midnight p-4 text-midnight-text">
      <div className="flex items-center gap-2.5">
        <div className="flex flex-1 flex-col gap-0.5">
          <h1 className="text-[17px] font-medium leading-[1.2]">Gizelle</h1>
          <p className="text-xs text-midnight-muted">{w.voiceCall}</p>
        </div>
        <div className="flex items-center gap-2 text-[13px] tabular-nums text-midnight-body">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-success-dark" />
          <span aria-label={`${w.elapsed} ${clock(callSeconds)}`}>{clock(callSeconds)}</span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-2">
        <Waveform speaking={speaking} paused={muted && !speaking} />
        <p role="status" className="text-sm text-midnight-body">{callStatus}</p>
      </div>
    </header>}

    <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto p-4" data-conversation-scroll>
      <section className="flex flex-col gap-2.5" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
        <Bubble role="assistant">{w.greet}</Bubble>
        {grouped.map((turn, i) => turn.divider
          ? <Divider key={i}>{turn.divider === "started" ? w.started : `${w.ended} · ${clock(turn.seconds)}`}</Divider>
          : <Bubble key={i} role={turn.role}>
            {turn.content}
            {partialInline && i === grouped.length - 1 && <span style={{ opacity: 0.6 }}> {partial.content}</span>}
            {!!turn.citations?.length && <details className="group mt-3 border-t border-hairline pt-1 whitespace-normal">
              <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 text-[13px] font-medium text-navy [&::-webkit-details-marker]:hidden">
                <span>{c.sources} ({turn.citations.length})</span>
                <span aria-hidden="true" className="text-bronze transition-transform duration-[330ms] group-open:rotate-90">›</span>
              </summary>
              <ol className="space-y-3 pb-1 pt-2">
                {turn.citations.map(source => <li key={source.id} className="text-[13px] leading-relaxed">
                  <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-navy underline decoration-hairline underline-offset-4 hover:decoration-bronze">
                    [{source.number}] {source.title}
                  </a>
                  <p className="mt-1 text-xs text-muted">{source.publisher} · {c.published} {source.published_at}</p>
                </li>)}
              </ol>
            </details>}
          </Bubble>)}
        {partial && !partialInline && <Bubble role={partial.role} faded>{partial.content}</Bubble>}
        {busy && <div className="self-start rounded-[12px_12px_12px_4px] bg-paper px-3.5 py-3">
          <span className="sr-only" role="status">{w.thinking}</span>
          <span aria-hidden="true" className="flex gap-1">
            {[0, 1, 2].map(i => <span key={i} className="gz-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: `${i * 0.2}s` }} />)}
          </span>
        </div>}
      </section>

      {showWelcome && <section className="mt-4 flex flex-col gap-2.5" aria-label={w.tryTopic}>
        <div className="grid grid-cols-2 gap-2.5">
          {[
            { key: "type", selected: !consentStep, icon: "message", title: w.typeTitle, desc: w.typeDesc, pick: chooseTyping, disabled: busy || voiceState === "permission" || voiceState === "connecting" },
            { key: "talk", selected: consentStep, icon: "phone", title: w.talkLive, desc: w.talkDesc, pick: askForCall, disabled: busy || voiceState === "permission" || voiceState === "connecting" },
          ].map(option => <button key={option.key} type="button" aria-pressed={option.selected} onClick={option.pick} disabled={option.disabled}
            className="gz-option gz-ease flex flex-col gap-1.5 rounded-[12px] border bg-white px-3.5 py-3 text-left">
            <span className="flex items-center gap-2">
              <Icon name={option.icon} size={18} />
              <span className="text-[15px] font-medium leading-[1.3]">{option.title}</span>
              <Icon name="arrowRight" className="ml-auto" />
            </span>
            <span className="text-[13px] leading-[1.4] text-body [text-wrap:pretty]">{option.desc}</span>
          </button>)}
        </div>
        <h2 className="mt-1 text-xs font-normal text-tertiary">{w.tryTopic}</h2>
        <div className="flex flex-wrap gap-2">
          {c.examples.map(item => <button key={item.label} type="button" disabled={locked} onClick={() => ask(null, item.question)}
            className="gz-ease min-h-[34px] rounded-[8px] border border-hairline bg-white px-3 py-1.5 text-left text-[13px] leading-snug text-navy hover:border-navy">
            {item.label}
          </button>)}
        </div>
      </section>}
    </div>

    {voiceState === "text" && <footer className="widget-composer flex flex-none flex-col gap-1.5 border-t border-hairline px-4 pt-3">
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      <form id="gizelle-form" onSubmit={ask}
        className="gz-composer flex items-end gap-2 rounded-[8px] border border-silver bg-white py-1.5 pl-3.5 pr-1.5 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-navy">
        <label htmlFor="news-question" className="sr-only">{c.label}</label>
        <textarea ref={input} id="news-question" value={question} disabled={locked} maxLength={2000} rows={1}
          onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          onChange={event => setQuestion(event.target.value)} placeholder={w.placeholder}
          className="max-h-[120px] min-w-0 flex-1 resize-none border-0 bg-transparent py-1.5 text-[14.5px] leading-[1.5] text-ink outline-none placeholder:text-tertiary" />
        <button type="submit" aria-label={c.send} disabled={busy || !question.trim()}
          className={`gz-ease gz-solid flex h-[34px] w-[34px] flex-none items-center justify-center rounded-full ${question.trim()
            ? "bg-bronze text-white hover:bg-bronze-hover active:bg-bronze-active" : "bg-paper text-tertiary"}`}>
          <Icon name="arrowUp" size={18} />
        </button>
      </form>
      <Terms w={w} />
    </footer>}

    {consentStep && <section aria-labelledby="gizelle-consent-title" className="widget-composer gz-panel-in flex max-h-[70%] flex-none flex-col gap-2.5 overflow-y-auto border-t border-hairline px-4 pt-[18px]">
      <h2 id="gizelle-consent-title" className="text-[17px] font-medium text-navy">{w.permTitle}</h2>
      <p className="text-sm leading-[1.55] text-body [text-wrap:pretty]">{w.permBody}</p>
      <p className="text-sm leading-[1.55] text-body [text-wrap:pretty]">{w.consent}</p>
      <p className="flex items-center gap-2 text-[13px] text-muted"><Icon name="mic" /><span>{w.permMic}</span></p>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {micIssue && <MicrophoneHelp language={language} blocked onOpenTab={isEmbedded && sessionToken ? openVoiceTab : null} />}
      {voiceState !== "consent" && <p role="status" className="text-[13px] text-muted">{voiceState === "permission" ? w.permission : w.connecting}</p>}
      <button type="button" onClick={agree} disabled={voiceState !== "consent"}
        className="gz-primary gz-ease mt-1 flex h-11 w-full items-center justify-center rounded-[4px] text-sm font-medium">{w.agree}</button>
      <button type="button" onClick={() => { setMicIssue(false); setVoiceState("text"); }} disabled={voiceState !== "consent"}
        className="self-center p-1.5 text-[13px] text-muted underline underline-offset-[3px]">{w.decline}</button>
      <Terms w={w} className="justify-center" />
    </section>}

    {inCall && <footer className="widget-composer flex flex-none flex-col gap-2 border-t border-hairline px-4 pt-3">
      <div className="flex gap-2.5">
        <button type="button" onClick={toggleMute}
          className="gz-secondary gz-ease flex h-11 flex-1 items-center justify-center gap-2 rounded-[4px] text-sm font-medium">
          <Icon name="mic" size={17} /><span>{muted ? w.unmute : w.mute}</span>
        </button>
        <button type="button" onClick={() => voice.endCall({force:true})}
          className="gz-primary gz-ease flex h-11 flex-1 items-center justify-center gap-2 rounded-[4px] text-sm font-medium">
          <Icon name="phone" size={17} style={{ transform: "rotate(135deg)" }} /><span>{w.end}</span>
        </button>
      </div>
      <p className="text-center text-[11.5px] text-tertiary">{w.callHint}</p>
      <Terms w={w} className="justify-center" />
    </footer>}
    </div>
  </main>;
}
