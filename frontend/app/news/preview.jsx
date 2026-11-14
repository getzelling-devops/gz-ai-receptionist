"use client";

import { useEffect, useRef, useState } from "react";
import { useWebVoice } from "../web-voice";

const copy = {
  en: {
    eyebrow: "GetZelling",
    notice: "Historical coverage · May–Oct 2025",
    label: "Your question", placeholder: "Ask about a place, topic, or date…", send: "Send",
    loading: "Finding the details…", error: "Market news is temporarily unavailable. Please try again.",
    you: "You", team: "GetZelling", sources: "View sources", published: "Published",
    enter: "Enter key", newLine: "New line", sendMessage: "Send message", enterHint: "Shift + Enter adds a new line",
    prompt: "Try a topic", clear: "Clear conversation",
    examples: [
      { label: "Selling with GetZelling", question: "How does GetZelling help me sell my home?" },
      { label: "Our listing fees", question: "What are GetZelling’s listing fees?" },
      { label: "The GetZelling app", question: "How does the GetZelling client app help me during a sale?" },
      { label: "Explore the Miami market", question: "What do your Market insights say about the Miami real estate market in 2025?" },
      { label: "Miami condo insights", question: "What did July 2025 reporting say about Miami condos?" },
      { label: "South Florida luxury", question: "What did July 2025 reporting say about Palm Beach luxury properties?" },
      { label: "Book a Listing Presentation", question: "I would like to schedule a Listing Presentation for my property." },
      { label: "Arrange a phone or video call", question: "Can you help me arrange a phone or video call with GetZelling?" },
    ],
  },
  es: {
    eyebrow: "GetZelling",
    notice: "Noticias históricas · May–oct 2025",
    label: "Su pregunta", placeholder: "Pregunte por un lugar, tema o fecha…", send: "Enviar",
    loading: "Buscando información…", error: "Las noticias no están disponibles por el momento. Inténtelo de nuevo.",
    you: "Usted", team: "GetZelling", sources: "Ver fuentes", published: "Publicado",
    enter: "Tecla Enter", newLine: "Nueva línea", sendMessage: "Enviar mensaje", enterHint: "Mayús + Enter añade una línea",
    prompt: "Pruebe con un tema", clear: "Borrar conversación",
    examples: [
      { label: "Vender con GetZelling", question: "¿Cómo me ayuda GetZelling a vender mi propiedad?" },
      { label: "Nuestros honorarios", question: "¿Cuáles son los honorarios de GetZelling para vender mi propiedad?" },
      { label: "La app de GetZelling", question: "¿Cómo me ayuda la aplicación de GetZelling durante la venta?" },
      { label: "Explorar el mercado de Miami", question: "¿Qué información tiene sobre el mercado inmobiliario de Miami en 2025?" },
      { label: "Condominios en Miami", question: "¿Qué decía la cobertura de julio de 2025 sobre los condominios en Miami?" },
      { label: "Lujo en el sur de Florida", question: "¿Qué decía la cobertura de julio de 2025 sobre las propiedades de lujo en Palm Beach?" },
      { label: "Agendar un Plan de venta", question: "Me gustaría agendar un Plan de venta para mi propiedad." },
      { label: "Agendar llamada o videollamada", question: "¿Puede ayudarme a agendar una llamada o videollamada con GetZelling?" },
    ],
  },
};

const widgetCopy = {
  en: {
    title: "Ask Gizelle",
    contact: "Email Gizelle", placeholder: "Ask about GetZelling, the market, or a meeting…", thinking: "Gizelle is replying…",
    voice: "Talk to Gizelle", agree: "Agree and call", decline: "Continue typing", end: "Return to text",
    consent: "GetZelling will record and transcribe this call for service and training. Do you agree?",
    connecting: "Connecting…", speaking: "On a call with Gizelle", failure: "Gizelle is unavailable. Please try again or email the team.",
    disclosure: "By chatting, you agree to our", terms: "terms", and: "and", privacy: "recording policy",
  },
  es: {
    title: "Pregunte a Gizelle",
    contact: "Escribir a Gizelle", placeholder: "Pregunte por GetZelling, el mercado o una cita…", thinking: "Gizelle está respondiendo…",
    voice: "Hablar con Gizelle", agree: "Acepto, iniciar llamada", decline: "Seguir escribiendo", end: "Volver al chat",
    consent: "GetZelling grabará y transcribirá esta llamada para atención y capacitación. ¿Está de acuerdo?",
    connecting: "Conectando…", speaking: "En llamada con Gizelle", failure: "Gizelle no está disponible. Inténtelo de nuevo o escriba al equipo.",
    disclosure: "Al chatear, acepta nuestros", terms: "términos", and: "y nuestra", privacy: "política de grabación",
  },
};

export default function NewsPreview({ sessionToken, sessionId }) {
  const [voiceState, setVoiceState] = useState("text");
  const [session, setSession] = useState(() => sessionId || crypto.randomUUID());
  const previous = useRef(null);
  const voiceLock = useRef(false);
  const requestLock = useRef(false);
  const [language, setLanguage] = useState("en");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [enterToSend, setEnterToSend] = useState(true);
  const end = useRef(null);
  const input = useRef(null);
  const c = copy[language];
  const w = widgetCopy[language];
  const locked = busy || voiceState !== "text";

  const voice = useWebVoice({
    session, sessionToken,
    onCallStart: () => setVoiceState("active"),
    onCallEnd: () => { setError(""); previous.current = null; voiceLock.current = false; setVoiceState("text"); },
    onError: error => {
      if (/meeting.*ended|meeting-ended|ejection/i.test([error?.message, JSON.stringify(error)].join(" "))) {
        previous.current = null; voiceLock.current = false; setVoiceState("text"); setError(""); return;
      }
      if (["audio-processing-setup-error", "audio-processor-recovery-error", "audio-observer-setup-error"].includes(error?.type)) return;
      voiceLock.current = false; setVoiceState("text"); setError(w.failure);
    },
    onTranscript: ({role, text}) => {
      // The voice transcriber sometimes spells the assistant's introduction “Giselle”.
      const content = role === "assistant"
        ? text.replace(/\b(this is|I’m|I'm|soy) Giselle\b/gi, "$1 Gizelle")
          .replace(/\b(?:giselle|gizelle)@getselling\.com\b/gi, "gizelle@getzelling.com")
          .replace(/\bgiselle@getzelling\.com\b/gi, "gizelle@getzelling.com")
          .replace(/\bgetselling\b/gi, "GetZelling") : text;
      setTurns(items => [...items, {role, content, voice: true}]);
    },
  });

  function context() {
    return { session, language, history: turns.slice(-24).map(({ role, content }) =>
      ({ role, content: content.slice(0, 1200) })) };
  }

  async function agree() {
    if (voiceLock.current) return;
    voiceLock.current = true; setError(""); setVoiceState("connecting");
    try {
      await voice.prepareCall();
      const response = await fetch("/api/widget/consent", { method: "POST",
        headers: { "Content-Type": "application/json", ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}) },
        body: JSON.stringify({ ...context(), version: "web-voice-v1", accepted: true }) });
      if (!response.ok) throw new Error();
      await voice.startCall();
    } catch (failure) {
      voice.cancelCall();
      voiceLock.current = false; setVoiceState("text");
      if (!/meeting.*ended|meeting-ended|ejection/i.test(String(failure?.message || failure)))
        setError(failure?.message === "MICROPHONE_DENIED"
          ? (language === "es" ? "Permita el acceso al micrófono en su navegador y vuelva a intentarlo. También puede seguir escribiendo." : "Allow microphone access in your browser and try again. You can also continue typing.")
          : failure?.message === "MICROPHONE_UNAVAILABLE"
          ? (language === "es" ? "No se pudo acceder al micrófono. Abra esta página en Safari o Chrome y vuelva a intentarlo." : "The microphone could not be accessed. Open this page in Safari or Chrome and try again.")
          : w.failure);
    }
  }

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [turns, busy]);

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

  async function ask(event) {
    event.preventDefault();
    if (requestLock.current || locked || !question.trim()) return;
    requestLock.current = true;
    const text = question.trim();
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

  function example(text) { setQuestion(text); input.current?.focus(); }

  return <main className="widget-shell mx-auto flex h-dvh w-full max-w-[450px] flex-col px-4 sm:px-6" lang={language}>
    <header className="shrink-0 border-b border-hairline py-3">
      <div className="mb-2 flex items-center justify-between gap-4">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-bronze">{c.eyebrow}</p>
        <div className="flex gap-1" aria-label="Language">
          {["en", "es"].map(value => <button key={value} type="button" disabled={locked}
            aria-pressed={language === value} onClick={() => { setLanguage(value); setError(""); }}
            className={`min-h-11 rounded px-3 text-sm ${language === value ? "bg-white font-medium text-navy" : "text-[#6E6656]"}`}>
            {value === "en" ? "EN" : "ES"}
          </button>)}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[24px] font-medium leading-[1.2] tracking-[-0.01em] text-navy">{w.title}</h1>
        <a className="flex min-h-11 items-center text-[13px] text-navy underline underline-offset-4"
          href="mailto:gizelle@getzelling.com">{w.contact}</a>
      </div>

    </header>

    <div className="min-h-0 flex-1 overflow-y-auto py-4" data-conversation-scroll>
    <section className="space-y-3" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
      {grouped.map((turn, i) => <article key={i} className={turn.role === "assistant" ? "rounded-xl border border-hairline bg-white p-4" : "px-1"}>
        <p className="mb-1 text-xs font-medium uppercase tracking-[0.12em] text-[#6E6656]">{turn.role === "user" ? c.you : "Gizelle"}</p>
        <p className="whitespace-pre-wrap text-sm leading-[1.65] text-[#4A4436]">{turn.content}</p>
        {!!turn.citations?.length && <details className="group mt-5 border-t border-hairline pt-1">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-[13px] font-medium text-navy [&::-webkit-details-marker]:hidden">
            <span>{c.sources} ({turn.citations.length})</span>
            <span aria-hidden="true" className="text-bronze transition-transform duration-[330ms] group-open:rotate-90">›</span>
          </summary>
          <ol className="space-y-3 pb-2 pt-2">
            {turn.citations.map(source => <li key={source.id} className="text-[13px] leading-relaxed">
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-navy underline decoration-hairline underline-offset-4 hover:decoration-bronze">
                [{source.number}] {source.title}
              </a>
              <p className="mt-1 text-xs text-[#6E6656]">{source.publisher} · {c.published} {source.published_at}</p>
            </li>)}
          </ol>
        </details>}
      </article>)}
      {busy && <p role="status" className="px-1 text-sm text-[#6E6656]">{w.thinking}</p>}
      <div ref={end} />
    </section>

    {voiceState === "text" && !turns.length && <section className="mt-5" aria-label={c.prompt}>
      <h2 className="mb-1 text-xs text-[#6E6656]">{c.prompt}</h2>
      <div className="flex flex-wrap gap-2">
        {c.examples.map(item => <button key={item.label} type="button" onClick={() => example(item.question)}
          className="min-h-11 rounded border border-hairline px-3 py-2 text-left text-xs leading-relaxed text-navy transition-colors duration-[330ms] hover:border-bronze">
          {item.label}
        </button>)}
      </div>
    </section>}
    </div>
    <footer className="widget-composer shrink-0 border-t border-hairline bg-paper py-3">

    {error && <p role="alert" className="text-sm text-[#8C3B2A]">{error}</p>}
    {voiceState === "text" && <form id="gizelle-form" onSubmit={ask} className="space-y-3">
      <label htmlFor="news-question" className="sr-only">{c.label}</label>
      <textarea ref={input} id="news-question" value={question} disabled={locked} maxLength={2000}
        aria-describedby={enterToSend ? "news-enter-hint" : undefined}
        onKeyDown={event => {
          if (event.key === "Enter" && enterToSend && !event.shiftKey
              && !event.nativeEvent.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        onChange={event => setQuestion(event.target.value)} placeholder={w.placeholder} rows={2}
        className="w-full resize-y rounded border border-hairline bg-white px-4 py-3 text-sm leading-relaxed placeholder:text-[#716D62]" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={busy || !question.trim()}
            className="min-h-11 rounded bg-bronze px-5 text-sm font-medium text-white transition-colors duration-[330ms] hover:bg-[#B18957] active:bg-[#5C3E26]">{c.send}</button>
          <button type="button" disabled={busy} className="min-h-11 rounded border border-bronze px-3 text-sm text-bronze"
            onClick={() => { setError(""); setVoiceState("consent"); }}>{w.voice}</button>
        </div>
        <div className="ml-auto text-right">
          <label className="flex min-h-11 items-center justify-end gap-1.5 text-xs text-[#6E6656]">
            {c.enter}
            <select value={enterToSend ? "send" : "line"} onChange={event => setEnterToSend(event.target.value === "send")}
              className="min-h-11 w-[116px] rounded border border-bronze bg-white px-1.5 text-xs text-navy">
              <option value="send">{c.sendMessage}</option>
              <option value="line">{c.newLine}</option>
            </select>
          </label>
          {enterToSend && <p id="news-enter-hint" className="mt-0.5 text-[11px] leading-4 text-[#6E6656]">{c.enterHint}</p>}
        </div>
      </div>
      {!!turns.length && <button type="button" disabled={locked} onClick={() => { setTurns([]); previous.current = null; if (!sessionId) setSession(crypto.randomUUID()); setError(""); }}
        className="min-h-11 text-[13px] text-[#6E6656] underline underline-offset-4">{c.clear}</button>}
    </form>}
    <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
      {voiceState === "consent" && <><p className="w-full">{w.consent}</p>
        <button className="min-h-11 rounded bg-bronze px-3 text-white" onClick={agree}>{w.agree}</button>
        <button className="min-h-11 text-navy" onClick={() => setVoiceState("text")}>{w.decline}</button></>}
      {voiceState === "connecting" && <p role="status">{w.connecting}</p>}
      {voiceState === "active" && <><p role="status">{w.speaking}</p>
        <button className="min-h-11 rounded border border-bronze px-3" onClick={() => voice.endCall({force:true})}>{w.end}</button></>}
    </div>
      <p className="mt-3 border-t border-hairline pt-2 text-[11px] leading-4 text-[#6E6656]">{w.disclosure} <a className="underline" href="https://getzelling.com/terms" target="_blank" rel="noreferrer">{w.terms}</a> {w.and} <a className="underline" href="https://getzelling.com/privacy" target="_blank" rel="noreferrer">{w.privacy}</a>.</p>
    </footer>
  </main>;
}
