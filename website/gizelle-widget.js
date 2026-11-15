(async () => {
  const script = document.currentScript;
  const configured = script?.dataset.widgetOrigin;
  if (!configured || document.getElementById("gz-gizelle")) return;
  const origin = new URL(configured).origin;
  if (!origin.startsWith("https://") && !origin.startsWith("http://127.0.0.1:")) return;
  const site = script.dataset.siteAdmission === "true";
  if (site) {
    try {
      const gate = await (window.GBSPreviewAccess?.ready ?? fetch("/api/preview/session", {cache:"no-store"}).then(r => r.json()));
      if (gate?.required !== true || gate?.authenticated !== true) return;
    } catch { return; }
  }
  const es = document.documentElement.lang.startsWith("es");
  const t = es
    ? {talk: "Hablar con Gizelle", live: "Llamada de voz en vivo", retry: "Inténtalo de nuevo", chat: "Chat", chatLabel: "Chatear con Gizelle",
      nudge: "¿Preguntas? Gizelle puede atenderte por llamada de voz en vivo o por chat.", dismiss: "Cerrar", frame: "Asistente de GetZelling"}
    : {talk: "Talk to Gizelle", live: "Live voice call", retry: "Try again", chat: "Chat", chatLabel: "Chat with Gizelle",
      nudge: "Questions? Gizelle can take a live voice call or chat.", dismiss: "Dismiss", frame: "GetZelling assistant"};
  const root = document.createElement("div");
  root.id = "gz-gizelle";
  const shadow = root.attachShadow({ mode: "open" });
  // Design system tokens (Stone & Paper, Midnight for the launcher).
  shadow.innerHTML = `<style>
    :host{--navy:#0B2545;--midnight-surface:#12305C;--midnight-muted:#AEB9D1;--midnight-border:rgba(255,255,255,.14);
      --bronze-light:#D6A96A;--text:#201C16;--text-tertiary:#716D62;--border:#E4DCCD;
      --elevation-card:0 10px 40px rgba(11,37,69,.08);--transition:.33s ease;
      font-family:Geist,Arial,sans-serif;color:var(--text)}
    *{box-sizing:border-box}
    button{font:inherit;margin:0;cursor:pointer}
    button:focus-visible{outline:2px solid var(--navy);outline-offset:2px}
    .dock{position:fixed;right:24px;bottom:24px;z-index:10000;display:flex;flex-direction:column;align-items:flex-end;gap:10px;
      opacity:0;transform:translateY(16px);pointer-events:none;transition:opacity .3s ease,transform .3s ease}
    .dock.in{opacity:1;transform:none;pointer-events:auto}
    .dock[hidden]{display:none}
    .bar{display:flex;height:52px;background:var(--navy);border-radius:4px;overflow:hidden;box-shadow:var(--elevation-card)}
    .bar button{border:0;background:transparent;color:#fff;transition:background-color var(--transition)}
    .bar button:hover{background:var(--midnight-surface)}
    .bar button:focus-visible{outline-color:#F4F1E8;outline-offset:-4px}
    .talk{display:flex;align-items:center;gap:12px;padding:0 16px;text-align:left}
    .lines{display:flex;flex-direction:column;gap:1px}
    .title{font-size:15px;font-weight:500;line-height:1.2}
    .sub{font-size:12px;line-height:1.2;color:var(--midnight-muted)}
    .split{width:1px;background:var(--midnight-border)}
    .chat{width:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0}
    .nudge{width:240px;padding:12px 14px;display:flex;gap:10px;align-items:flex-start;background:#fff;border:1px solid var(--border);
      border-radius:12px 12px 4px 12px;box-shadow:var(--elevation-card);opacity:0;transform:translateY(8px);
      transition:opacity .3s ease,transform .3s ease}
    .nudge.in{opacity:1;transform:none}
    .nudge[hidden]{display:none}
    .nudge p{flex:1;margin:0;font-size:14px;line-height:1.45;color:var(--text)}
    .nudge button{width:20px;height:20px;display:flex;align-items:center;justify-content:center;border:0;padding:0;background:none;color:var(--text-tertiary)}
    .panel{position:fixed;right:24px;bottom:24px;z-index:10001;width:420px;max-width:calc(100vw - 32px);
      height:min(680px,calc(100dvh - 48px));border:1px solid var(--border);border-radius:12px;background:#fff;
      overflow:hidden;box-shadow:var(--elevation-card);animation:gzIn .3s ease}
    .panel[hidden]{display:none}
    iframe{display:block;border:0;width:100%;height:100%;background:#fff}
    @keyframes gzIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
    @media(max-width:500px){.dock{right:16px;bottom:16px}.panel{right:16px;bottom:16px;height:calc(100dvh - 32px)}}
    @media(prefers-reduced-motion:reduce){.dock,.nudge{transition:none}.panel{animation:none}}
  </style>
  <div class="dock" hidden>
    <div class="nudge" role="status" hidden>
      <p>${t.nudge}</p>
      <button type="button" class="dismiss" aria-label="${t.dismiss}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
    </div>
    <div class="bar">
      <button type="button" class="talk" aria-expanded="false" aria-controls="gizelle-panel">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#D6A96A" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M2 10v3M6 6v11M10 3v18M14 8v7M18 5v13M22 10v3"/></svg>
        <span class="lines"><span class="title">${t.talk}</span><span class="sub">${t.live}</span></span>
      </button>
      <span class="split" aria-hidden="true"></span>
      <button type="button" class="chat" aria-label="${t.chatLabel}" aria-expanded="false" aria-controls="gizelle-panel">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>
        <span class="sub">${t.chat}</span>
      </button>
    </div>
  </div>
  <section class="panel" id="gizelle-panel" role="region" aria-label="Gizelle" hidden></section>`;
  const dock = shadow.querySelector(".dock");
  const nudge = shadow.querySelector(".nudge");
  const talk = shadow.querySelector(".talk");
  const chat = shadow.querySelector(".chat");
  const panel = shadow.querySelector(".panel");
  let frame;
  let opening = false;
  let sessionSent = false;
  let mode = "chat";
  let opener = chat;

  // Buyers and Sellers have a floating bottom navigation; sit above it when the two would overlap.
  const placeDock = () => {
    dock.style.bottom = "";
    const bar = document.querySelector(".gzb-bar");
    if (!bar || dock.hidden) return;
    const b = bar.getBoundingClientRect(), d = dock.getBoundingClientRect();
    if (b.width && b.left < d.right && b.right > d.left && b.top < d.bottom && b.bottom > d.top)
      dock.style.bottom = Math.round(window.innerHeight - b.top + 12) + "px";
  };
  window.addEventListener("resize", placeDock);

  // Show the launcher after the visitor scrolls past the hero, or after 8 seconds.
  let shown = false;
  const reveal = () => {
    if (shown) return;
    shown = true;
    document.removeEventListener("scroll", onScroll, true);
    dock.hidden = false;
    placeDock();
    requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.add("in")));
    let seen = false;
    try { seen = sessionStorage.getItem("gz-gizelle-nudge") === "1"; sessionStorage.setItem("gz-gizelle-nudge", "1"); } catch {}
    if (!seen) setTimeout(() => {
      if (!panel.hidden) return;
      nudge.hidden = false;
      requestAnimationFrame(() => nudge.classList.add("in"));
      setTimeout(hideNudge, 6000);
    }, 1500);
  };
  // Pages scroll either the document or an inner container, so listen in the capture phase.
  const onScroll = e => {
    const target = e.target === document ? document.scrollingElement : e.target;
    if ((target?.scrollTop || 0) > window.innerHeight * 0.6) reveal();
  };
  document.addEventListener("scroll", onScroll, {capture: true, passive: true});
  setTimeout(reveal, 8000);

  function hideNudge() {
    nudge.classList.remove("in");
    setTimeout(() => { nudge.hidden = true; }, 300);
  }

  window.addEventListener("message", async e => {
    if (!frame || e.source !== frame.contentWindow || e.origin !== origin) return;
    if (e.data?.type === "gizelle:minimize") return minimize();
    if (!site || e.data?.type !== "gizelle:ready" || opening) return;
    opening = true;
    try {
      const r = await fetch("/api/preview/gizelle-session", {method:"POST", cache:"no-store"});
      if (!r.ok) throw Error();
      const {session_id, session_token} = await r.json();
      frame.contentWindow.postMessage({type:"gizelle:session", session_id, session_token, mode, language: es ? "es" : "en"}, origin);
      sessionSent = true;
    } catch {
      frame.contentWindow.postMessage({type:"gizelle:unavailable"}, origin);
      frame.remove(); frame = null; sessionSent = false;
      minimize();
      shadow.querySelector(".talk .sub").textContent = t.retry;
    } finally { opening = false; }
  });

  function setExpanded(value) {
    talk.setAttribute("aria-expanded", value);
    chat.setAttribute("aria-expanded", value);
  }
  function minimize() {
    if (panel.hidden) return;
    panel.hidden = true;
    dock.hidden = false;
    placeDock();
    setExpanded("false");
    opener.focus();
  }
  function open(nextMode, from) {
    mode = nextMode; opener = from;
    nudge.hidden = true;
    if (!frame) {
      sessionSent = false;
      frame = document.createElement("iframe");
      frame.src = origin + (site ? "/#website" : "/");
      frame.title = t.frame;
      frame.allow = "microphone";
      // Without the website handshake, tell the panel which step to show once it loads.
      if (!site) frame.addEventListener("load", () => frame?.contentWindow.postMessage({type:"gizelle:show", mode}, origin), {once: true});
      panel.append(frame);
    } else if (sessionSent || !site) {
      frame.contentWindow.postMessage({type:"gizelle:show", mode}, origin);
    }
    shadow.querySelector(".talk .sub").textContent = t.live;
    panel.hidden = false;
    dock.hidden = true;
    setExpanded("true");
    frame.focus();
  }
  talk.addEventListener("click", () => open("voice", talk));
  chat.addEventListener("click", () => open("chat", chat));
  shadow.querySelector(".dismiss").addEventListener("click", hideNudge);
  shadow.addEventListener("keydown", event => { if (event.key === "Escape") minimize(); });
  document.body.append(root);
})();
