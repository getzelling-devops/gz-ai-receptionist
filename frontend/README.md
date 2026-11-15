# GetZelling receptionist widget

This standalone Next.js App Router page can be embedded in the website's Firebase-hosted HTML. The host build can mount an iframe on demand with a descriptive title and `allow="microphone"`. Place the following inside the site's chat panel and substitute the deployed HTTPS widget origin. The parent must permit that origin in its framing and microphone policies.

```html
<iframe src="https://WIDGET_HOST/" title="GetZelling receptionist"
        allow="microphone" style="width:100%;height:32rem;border:0"></iframe>
```

From this directory, run `npm ci`, set `NEXT_PUBLIC_VAPI_PUBLIC_KEY` and `NEXT_PUBLIC_VAPI_ASSISTANT_ID`, then run `npm run dev` or `npm run build` and `npm start`. Next.js includes these public settings at build time. Restrict the Vapi public key to the widget domain and saved assistant. The widget links to GetZelling's /terms and /privacy pages. Confirm that the published policies cover recording and retention.

## Private combined website preview

Start the IAM-authenticated archive proxy on loopback:

```sh
gcloud run services proxy news-rag-staging --project=gz-ai-receptionist --region=us-east1 --port=8088
```

From `backend/`, run the private Gizelle bridge. The optional CLI-user mode uses the current operator's Google credentials. Without the flag the bridge uses ADC. All provider secrets come from Secret Manager.

```sh
WEB_PREVIEW_GCLOUD_USER=true uv run uvicorn receptionist.web_preview:app --host 127.0.0.1 --port 8092 --no-access-log
```

From `frontend/`, run:

```sh
NEWS_PREVIEW_ENABLED=true NEWS_BACKEND_URL=http://127.0.0.1:8088 npm run dev -- --hostname 127.0.0.1 --port 3108
```

Open `http://127.0.0.1:3108/` or `/news` for the same unified Gizelle conversation. Both text and voice support GetZelling information, Market insights, contact requests and appointments. Text automatically retrieves cited historical articles through Vertex and routes company and appointment requests to the saved Vapi assistant. Existing clients that send a topic field remain supported. The saved website assistant uses its signed market-insights tool for market facts. The operator bridge can still supply checked excerpts for older assistant configurations; set WEB_RETRIEVAL_TOOL=true to omit that legacy context. Current-market requests explain the historical cutoff and offer a report or team call.

The panel follows the Gizelle design handoff (gz-gz-website/handoff/design_handoff_gizelle_chat). The header has Talk live, an EN/ES toggle, a More menu (Email Gizelle, Clear conversation) and, when embedded, a close button that asks the website to minimize the panel. The welcome view offers Type a message and Talk live cards and nine topic chips; each chip shows a short label and sends a fuller question to the chat backend. Enter sends and Shift+Enter adds a line. Terms and recording-policy links stay at the bottom during text, voice consent and calls. A voice call shows a Midnight header with timer, waveform and speaking status, the live transcript (in-progress lines faded), and Mute and End call. English uses Listing Presentation and Spanish uses Plan de venta. Consecutive voice fragments from one speaker share a message block. Switching from voice to text carries recent spoken turns forward. Calendar modifications require the original provider conversation identity. A visitor requesting a change across channels needs team assistance.

The unnumbered Vapi assistant **Gizelle | GetZelling web staging** has its own saved booking tools, report webhook and credential. Its web-only market instructions are in `backend/website-market-prompt.md`. Save the webhook and its credential on the assistant itself to allow Vapi to sign reports. Chat carries its provider chat ID and checks ownership in Firestore. The staging browser receives no Vapi key. Each affirmative web consent writes the language, disclosure version, session and Google server timestamp before room creation. An expiring, single-use HttpOnly grant authorizes a server-side call to Vapi. The backend signs a one-minute assistant-scoped JWT, links the call ID to its consent, and returns the room to the React SDK. Audio starts after the visitor joins. The website speaks one English or Spanish farewell through its finish-call function, waits for GZ_FAREWELL_COMPLETE, and then invokes the guarded silent close_gizelle_web tool. The completion endpoint includes a short audio-drain pause. Expected Daily meeting-ended events return the widget to text. The telephone flow uses its separate assistant.

The archive uses the IAM-protected Cloud Run service and the 15 source-checked excerpts. Both local bridges return 404 in production. The hosted pilot uses its separate authenticated bridge (below). Public release requires a corpus approved for that audience. Gizelle’s published contact address is gizelle@getzelling.com. The owner confirmed incoming delivery from an external Gmail address to gizelle@getzelling.com with a Gmail inbox screenshot on November 14, 2026. Browser testing should include microphone refusal, switching languages, and recording and lead delivery on a consented call.

Run `node --test tests/*.test.mjs` and `npm run build` from this directory for the bridge tests and production build.

## Hosted private pilot

The production entry point is enabled with `WIDGET_HOSTED_PREVIEW=true`. `WIDGET_BACKEND_URL` selects the hosted FastAPI service. The widget asks for the owner's preview code before issuing a two-hour server-created visitor session. Its opaque session token stays in the widget's memory and is forwarded as a bearer token. Embedded requests use no third-party session cookie. The backend uses its attached GCP identity for Firestore, Secret Manager and invocation of the private news service.

`receptionist.web_app:app` enforces the session identity, per-session and aggregate request budgets, a request-body limit and single-use affirmative voice consent. The code is fetched at runtime from the `gizelle-preview-access` Secret Manager secret. Five voice starts per hour per visitor session, 120 authenticated requests per hour per visitor session, and 500 authenticated/tool requests per UTC day are the initial pilot limits. Login attempts are separately bounded. The review corpus retains private visibility.

Both typed market retrieval and the signed `market-insights` Vapi function use `receptionist.market_client.search`. The function accepts only the saved website assistant and requires a stored consent record for a web voice call. The news service keeps IAM protection and its separate database. Call reports still reach the existing signed lead-delivery webhook.

The website loader is `website/gizelle-widget.js` at the repository root. It shows the navy two-part launcher (Talk to Gizelle opens the voice consent step, Chat opens the text view) after the visitor scrolls past the hero or after 8 seconds, with a one-time nudge per browser session. It lazily mounts one microphone-enabled iframe in a 420px panel, and hides the panel while retaining the iframe when minimized. `scripts/publish_website_preview.py` clones the current live Firebase Hosting version into the expiring `gizelle-pilot` channel, adds the loader and microphone policy, and confirms the live release version afterward. `scripts/configure_web_market_tool.py` attaches the retrieval tool to the website assistant.

The pilot channel also includes /gizelle-preview.html, a test page for the embedded launcher. The website’s existing invitation gate restricts login to its approved domains, so the preview channel homepage may reject a website code. The test page contains no restricted site content and still requires the separate widget preview code.

## Invitation-only website integration

The main website's build (in the sibling gz-gz-website repository) installs js/gizelle-widget.js and the iframe microphone policy. The fixed launcher appears after the website confirms its private invitation session. On first open the iframe requests a session from its parent. The parent POSTs to /api/preview/gizelle-session; the website API checks its signed HttpOnly cookie and exact origin, reads gizelle-preview-access using its attached identity, then exchanges it server-side for an expiring visitor session. Only the visitor token is passed to the iframe, with both origin and window checked. Minimizing preserves the iframe. Voice still requires Agree and call. No DNS change is needed for the embedded Cloud Run origin.

The website integration intentionally fails closed in public mode. Before removing the website invitation, replace private admission with the chosen public abuse controls and approve the corpus for public use. Keep the operator-only standalone preview separately code-gated. The website includes its own copy of the launcher: keep both files in sync when changing it.

Mobile voice requests a live microphone track directly from Agree and call before creating a room. Denied or unanswered permission creates no Vapi call; text remains available. The acquired track is passed explicitly to the SDK, stopped on cleanup, and connection attempts are time-bounded. Hang control messages allow a short audio-drain interval before browser cleanup so the final farewell is not cut off by the widget. Actual iPhone browser verification remains part of device acceptance.

Microphone setup now explains the browser's native prompt before calling. A denied or unavailable microphone keeps the visitor on the consent screen, opens browser-specific English/Spanish help, and offers another user-initiated request. Guidance detects Safari/Chrome on iPhone or iPad and Chrome on Android; a selector handles other browsers or incorrect detection. The widget cannot reset browser or operating-system denials.

An embedded visitor can open voice in a top-level tab. The new tab requests the existing visitor session from its exact same-origin opener via postMessage; both source window and origin are checked. Tokens never enter the URL. Recent conversation and language carry over, but recording consent must be given again. A missing handoff times out with reopen instructions. This fallback changes no microphone permissions and does not bypass consent, API authentication or limits.
