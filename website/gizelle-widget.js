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
  const root = document.createElement("div");
  root.id = "gz-gizelle";
  const shadow = root.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>
    :host{font-family:Geist,Arial,sans-serif;color:#201C16}
    *{box-sizing:border-box}
    button{font:500 14px Geist,Arial,sans-serif;cursor:pointer;min-height:44px}
    button:focus-visible{outline:2px solid #0B2545;outline-offset:3px}
    .launcher{position:fixed;right:24px;bottom:24px;z-index:10000;border:1px solid #8C6844;
      border-radius:6px;background:#8C6844;color:#fff;padding:0 18px}
    .panel{position:fixed;right:24px;bottom:80px;z-index:10001;width:450px;max-width:calc(100vw - 32px);
      height:min(740px,calc(100dvh - 108px));border:1px solid #8C6844;border-radius:10px;
      background:#F4F1EA;overflow:hidden;box-shadow:0 8px 30px rgba(11,37,69,.12)}
    .panel[hidden]{display:none}
    .bar{display:flex;justify-content:space-between;align-items:center;height:44px;padding:0 12px;
      border-bottom:1px solid #E4DCCD;font-size:12px;color:#6E6656}
    .close{border:0;background:transparent;color:#0B2545;width:44px;font-size:24px}
    iframe{display:block;border:0;width:100%;height:calc(100% - 44px);background:#F4F1EA}
    @media(max-width:500px){.launcher{right:16px;bottom:16px}.panel{right:16px;bottom:72px;
      height:calc(100dvh - 88px)}}
  </style>
  <button class="launcher" aria-expanded="false" aria-controls="gizelle-panel">${es ? "Hablar con Gizelle" : "Talk to Gizelle"}</button>
  <section class="panel" id="gizelle-panel" role="region" aria-label="Gizelle" hidden>
    <div class="bar"><span>GetZelling</span><button class="close" aria-label="${es ? "Minimizar Gizelle" : "Minimize Gizelle"}">×</button></div>
  </section>`;
  const launcher = shadow.querySelector(".launcher");
  const panel = shadow.querySelector(".panel");
  let frame;
  let opening = false;
  if (site) window.addEventListener("message", async e => {
    if (!frame || e.source !== frame.contentWindow || e.origin !== origin || e.data?.type !== "gizelle:ready" || opening) return;
    opening = true;
    try {
      const r = await fetch("/api/preview/gizelle-session", {method:"POST", cache:"no-store"});
      if (!r.ok) throw Error();
      const {session_id, session_token} = await r.json();
      frame.contentWindow.postMessage({type:"gizelle:session", session_id, session_token}, origin);
    } catch {
      frame.contentWindow.postMessage({type:"gizelle:unavailable"}, origin);
      frame.remove(); frame = null;
      panel.hidden = true; launcher.setAttribute("aria-expanded","false"); launcher.focus();
      launcher.textContent = es ? "Reintentar con Gizelle" : "Retry Gizelle";
    } finally { opening = false; }
  });
  function minimize() {
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  }
  launcher.addEventListener("click", () => {
    if (!panel.hidden) return minimize();
    if (!frame) {
      frame = document.createElement("iframe");
      frame.src = origin + (site ? "/#website" : "/");
      frame.title = es ? "Asistente de GetZelling" : "GetZelling assistant";
      frame.allow = "microphone";
      panel.append(frame);
    }
    panel.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    shadow.querySelector(".close").focus();
  });
  shadow.querySelector(".close").addEventListener("click", minimize);
  shadow.addEventListener("keydown", event => { if (event.key === "Escape") minimize(); });
  document.body.append(root);
})();
