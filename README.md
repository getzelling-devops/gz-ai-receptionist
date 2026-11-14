# gz-ai-receptionist

One repository with an independently deployable FastAPI service in `backend/` and a Next.js widget in `frontend/`. The existing website builds HTML and browser JavaScript into `dist/` and publishes it to Firebase Hosting. Its landing page uses React 18. Its `/api/**` rewrite belongs to the website's own Cloud Run API. Mount the receptionist through the [widget embed](frontend/README.md).

## Local initialization

The initial scaffold was created with the commands below. A fresh checkout should use the lockfiles.

```sh
uv init --bare --python '>=3.11' --name gz-ai-receptionist backend
uv add --project backend fastapi uvicorn firebase-admin google-cloud-secret-manager httpx google-auth requests
```

From a checkout:

```sh
cd backend
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run uvicorn receptionist.main:app --reload --port 8080
```

The backend starts without credentials. Signed operations require the settings below. Local development uses `gcloud auth application-default login` for Secret Manager. On Cloud Run, use the service's attached identity. The backend never loads dotenv files. Build the backend container from the `backend/` directory. It listens on Cloud Run's `PORT`. Deploy with external ingress and unauthenticated invocation, with application-level HMAC authentication on every business route.

## Runtime configuration

The default project is `gz-ai-receptionist`. Give the runtime identity Secret Accessor on the required secrets. The Firebase JSON account needs Firestore access to this project's intended database. Keep client access to CRM collections restricted. Share the booking calendar with the dedicated Calendar service account as an event editor and give that account free/busy access to each blocking calendar. Enable the IAM Service Account Credentials API. The Cloud Run runtime identity needs permission to generate an access token on that Calendar service account. Calendar uses a refreshable ten-minute token scoped to events, free/busy and read-only calendar metadata. Metadata supplies the calendar timezone for all-day conflicts during rescheduling.

| Non-secret setting | Meaning or default |
| --- | --- |
| GCP_PROJECT, FIRESTORE_DATABASE | gz-ai-receptionist, (default) |
| VAPI_HMAC_SECRET | Secret ID, default vapi-webhook-hmac. Store the exact UTF-8 HMAC key without a trailing newline. |
| FIREBASE_ACCOUNT_SECRET | Secret ID, default firebase-service-account. Contains Firebase Admin service account JSON. |
| FIREBASE_AUTH_MODE | Defaults to `secret`. Staging uses `runtime` for Firebase Admin with the attached Cloud Run identity and a database-scoped IAM grant. |
| CALENDAR_SERVICE_ACCOUNT | Target identity for short-lived Calendar tokens. Defaults to receptionist-calendar@GCP_PROJECT.iam.gserviceaccount.com, with GCP_PROJECT expanded. |
| BREVO_API_SECRET | Secret ID, default brevo-api-key. Contains the Brevo API key. |
| BOOKING_CALENDAR_ID | Required writable calendar ID. |
| BUSY_CALENDAR_IDS | Optional comma-separated additional calendars, including Jorge's commitments if kept separately. |
| BREVO_SENDER | Required Brevo-verified sender address. |
| LEAD_EMAIL | Ordinary leads default to activate@getzelling.com. |
| ON_CALL_EMAIL | On-call paging service email ingress or monitored on-call alias. Urgent support mail goes separately to support@getzelling.com. |

Secrets are fetched from Secret Manager at runtime. Secret values are cached in memory for up to 60 seconds. The initialized Firebase Admin app keeps its credential until process restart. Roll instances after rotating the Firebase account key. The backend currently makes no private Vapi management calls.

## Vapi setup

Use the saved assistant, phone number and function-tool server URLs. Attach a Vapi custom HMAC credential to every applicable server URL. Choose SHA-256, hex, no prefix, plaintext key, timestamp included, payload `{timestamp}.{body}`, headers `x-signature` and `x-timestamp`. The verifier uses the original request bytes and accepts Unix seconds or milliseconds within five minutes. Set up a signed staging delivery to confirm the credential format before routing traffic. [Vapi server authentication](https://docs.vapi.ai/server-url/server-authentication)

Use [the bilingual receptionist instructions](backend/assistant-prompt.md), Cartesia Sonic 3.6 Jacqueline voice and a transcriber supporting English and Spanish. The current telephone route uses the pre-assistant Twilio announcement and the post-notice overrides in `backend/receptionist/phone_assistant.json`, including an empty compliancePlan; it does not use Vapi's paid native recording-consent feature. Keep the prompt and phone configuration synchronized. Do not publish the older draft that still contains a native consent plan. The website voice flow requires its affirmative Agree and call step and backend consent authorization before voice begins. Enable recording, transcript artifacts and the end-of-call report only for authorized voice sessions, and verify consent paths separately on each channel. [Vapi recording consent](https://docs.vapi.ai/security-and-privacy/recording-consent-plan)

| Vapi event or function | FastAPI POST route | Configuration |
| --- | --- | --- |
| end-of-call-report | /webhooks/call-ended | Subscribe to end-of-call-report at the assistant Server URL. |
| check-availability | /tools/check-availability | Required date (YYYY-MM-DD), optional appointment_type (default general_inquiry). Include optional start (ISO timestamp with UTC offset) whenever the caller requests a specific time. For a change, include the appointment_id returned by this conversation's booking. |
| book-appointment | /tools/book-appointment | Required start (ISO timestamp with UTC offset), appointment_type, contact_name, phone. Optional meeting_details for property address or video contact. additional_appointment is a boolean used only for an explicitly requested separate meeting of the same type. |
| reschedule-appointment | /tools/reschedule-appointment | Required appointment_id and newly agreed start. Updates the original Calendar event; does not create a second booking. Limited to appointments created in the same conversation. |
| escalate-urgent | /tools/escalate-urgent | Required message, optional phone. Also attach Vapi's native transferCall tool with a fixed, verified E.164 destination for telephone calls. |
| finish-call | /tools/finish-call | Required Vapi-reserved bot_say farewell in the caller's latest language. Vapi finishes playback and removes bot_say before invoking this signed endpoint. The result permits the silent native hang-up tool. |

Use the exact function schemas in `backend/staging-vapi-tools.json`, including the boolean additional_appointment and the reserved bot_say fields. Appointment types are `listing_presentation`, `first_call` and `general_inquiry`. Tools are synchronous. Allow enough time for free/busy, reservation and insertion or update. Configure transfer failure to offer a callback. The SDK and prompt handle web-to-phone handoffs as callbacks. The on-call gateway should page independently of support mail; verify actual page delivery in staging.

When updating a saved Vapi function tool, send its complete intended configuration, including `server`, its HMAC credential ID, and `async: false`. Read the tool back and verify these fields before a call. A staging update that sent only `function` removed the previous server configuration and produced “No result returned.”

Configure an object-valued structured output named `getzelling_lead` with string fields `name`, `phone`, `lead_type` and `summary`. Attach its ID to the assistant. The report also accepts legacy analysis. Unknown values remain null. Modern transcript and mono/stereo recording fields take precedence over legacy fields. [Vapi server events](https://docs.vapi.ai/server-url/events)

## Booking and lead records

- The calendar window is 9 am–6 pm America/New_York, including the meeting's end. Appointments may start at :00, :15, :30 or :45. Listing reservations remain 60 minutes and phone/video or general inquiries remain 30 minutes. Gizelle does not volunteer the duration; when asked, she explains the reserved block and flexibility to the client's needs. In Spanish a listing presentation is a “Plan de venta.” Weekends and listings under 24 hours away receive opaque tentative events. Other eligible appointments receive confirmed events. No extra travel buffer was assumed.
- An availability check with `start` checks the exact requested time and searches forward for an alternative if occupied. Its Miami date must match `date`. A date-only query finds the day's earliest availability. The assistant must read back the exact appointment date, time, timezone and type and obtain agreement before booking, including when offering an alternative.
- For conflicting requests, the assistant receives a tool error with the next available slot within a 14-day search, or a callback option when none is found. Free/busy errors fail closed. Busy events, including out-of-office events, block the corresponding interval.
- Firestore transactions claim each overlapping quarter hour before querying Calendar and inserting or moving an event. The stable Calendar event ID is derived from the conversation and tool call IDs. A lost insert response is reconciled by that ID. The half-hour-to-quarter-hour transition requires draining active booking operations before deployment; the staging transition was drained. Manual Calendar edits can still race the final free/busy read. Moving or cancelling a booking in Calendar affects subsequent availability checks.
- `appointments` holds the current event reference, time and conversation ownership. `appointment_groups` prevents a new tool ID from duplicating the same caller's appointment type within that conversation, unless an additional meeting was explicitly requested. `bookings` stores immutable creation operations and `booking_moves` stores idempotent moves. Replayed completed requests report the current time after later moves.
- A move lists the booking calendar's individual events and excludes only its own event ID; it still checks other configured calendars through free/busy. This avoids hiding a different overlapping event inside a merged busy interval. Calendar PATCH preserves location and contact details, uses If-Match against concurrent edits, and marks the move for recovery after an uncertain response. Conflicts leave the original event in place. Cross-conversation changes require team assistance until caller verification is implemented. Earlier appointments without an ownership record are also handled by the team.
- Each report creates one `leads` document per call ID, plus a Brevo delivery in the same Firestore transaction. It persists name, phone, lead type, summary, timestamp, transcript and recording URL. Oversized transcripts use ordered `transcript_parts` subdocuments under the same lead. Replayed reports can fill missing artifacts. There is no TTL or deletion job.
- Firestore retains the recording reference. For indefinite audio access, configure Vapi to write recordings to a GetZelling-controlled private GCS bucket, retain the objects, and use authorized playback for expiring URLs. Test bucket access and URL expiry separately. [Vapi storage options](https://docs.vapi.ai/customization/provider-keys)
- Retrieve current recordings through Vapi's authenticated `GET /call/{id}/mono-recording` or `stereo-recording` endpoint, following its redirect to a fresh signed URL. A raw storage URL from the call report is not a durable playback link. Keep the private API key on the server. [Vapi artifact retrieval](https://docs.vapi.ai/assistants/retrieve-call-artifacts)

## Recovery and verification

After a provider outage, replay pending deliveries, bookings and moves with `uv run python -m receptionist.recover` from `backend/`. This is suitable for a Cloud Run Job; schedule it at a short interval before launch if unattended recovery is required. The webhook attempts delivery immediately. Brevo retries reuse the same UUID. An ambiguous delivery older than 25 minutes enters `review` before Brevo's documented 30-minute deduplication window expires. Inspect Brevo history before deliberately resending. Monitor pending bookings, moves, delivery reviews and endpoint failures. [Brevo idempotency](https://developers.brevo.com/docs/heterogenous-versions-batch-emails)

Run the persistence tests against a local Firestore emulator to exercise the transactional paths:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 uv run python -m unittest discover -s tests -v
```

Point this command at the emulator's actual port. Tests use the isolated demo-receptionist project with anonymous credentials. Calendar, Brevo and Secret Manager are simulated in tests. Live acceptance requires a consented English and Spanish call, a busy calendar test, an actual on-call transfer/page, and retrieval of the retained recording.

## Phone number and disclosure flow

The receptionist owns +1 (786) 977-2774 in the GetZelling Receptionist Twilio subaccount. Its verified local-number rental is $1.15/month before usage and applicable taxes. The parent account's GZ PROPTECH INC business profile is approved.

The telephony module accepts Twilio form webhooks under /telephony/twilio. It verifies the official X-Twilio-Signature against PUBLIC_BASE_URL and every form field, using twilio-auth-token fetched from Secret Manager. TWILIO_ACCOUNT_SID and TWILIO_PHONE_NUMBER pin the expected subaccount and destination. The staging runtime needs Secret Accessor on that individual secret.

The inbound response plays the versioned English/Spanish disclosure and a three-second pause, then redirects to /telephony/twilio/connect. That signed continuation writes its timestamp and stay-on-line consent basis to Firestore. It issues a two-minute, single-use random SIP gate tied to the Twilio CallSid. Twilio's own recording is disabled. The Vapi SIP entry has a signed /telephony/vapi/resolve server and no directly assigned assistant. The resolver requires the gate before returning the saved assistant ID with the post-disclosure phone configuration in receptionist/phone_assistant.json. Only that configuration enables the voice recording. Gate claims are replayable for the same Vapi call ID and rejected for another call. The voice_consents record is copied into the lead when the call report arrives.

The phone greeting is “Thank you for calling GetZelling, this is Gizelle, how can I help you today?” Phone overrides use the saved booking tools, Cartesia voice and bilingual prompt. The published assistant version remains independently managed in Vapi. Urgent transfer and on-call paging still require destination configuration.

After deployment and secret access, set the purchased number's VoiceUrl to PUBLIC_BASE_URL + /telephony/twilio/inbound with POST. Verify an actual telephone call before advertising the number. In particular, confirm the incoming SIP token reaches the resolver, hanging up during the notice creates no Vapi conversation, a connected call includes the notice-continuation audit, recording begins after the notice, and booking plus end-of-call lead delivery work. Notice text and consent basis need the previously discussed Florida legal review.

Staging verification on November 13, 2026 confirmed the number's live route, the runtime's accessor grant on only `twilio-auth-token`, signed Twilio and Vapi handoffs, and the persisted notice-continuation audit. A self-call retrieved a 33.12-second WAV recording through the authenticated Vapi endpoint, beginning after the handoff, and persisted its transcript and lead with a sent Brevo delivery. A separate self-call hung up during the announcement and created no Vapi call, transcript, or recording, with zero Twilio recordings. The first conversation ended during callback-number collection; the phone prompt now requires completing the request and checking for further questions before ending.

The final self-call passed on revision `receptionist-staging-00005-pd6` with availability tool v3. Jackie checked the caller's requested November 16, 2026, 10 am Miami slot, waited for agreement, booked that exact 30-minute appointment, confirmed it in English and Spanish, and ended after the caller said goodbye. Firestore retained the synthetic lead, transcript, recording reference and consent audit; Brevo marked the notification sent. Authenticated retrieval returned a 90.68-second WAV, with the Vapi call starting 0.872 seconds after the notice continuation. The temporary Calendar event was verified and removed. Local checks passed 16 tests, with five persistence tests skipped because the Firestore emulator was not running. Live transfer and on-call paging remain unconfigured.

## Voice refinements from caller testing

The version-two telephone notice is 30 words across English and Spanish. It retains the recording, transcription, service/training purpose and continuation wording, removes the email address, and keeps the three-second pause before connecting. The continuation carries forward the disclosure version stored when that call began, including across a deployment.

The saved staging tool configurations are checked in as `backend/staging-vapi-tools.json`. Availability and booking use Vapi's reserved `bot_say` argument for a short acknowledgment in the caller's latest language. Empty start messages suppress the default English fillers. Delayed messages have English and Spanish variants. Preserve the server settings when applying these configurations and read each tool back before testing. [Dynamic tool messages](https://docs.vapi.ai/tools/dynamic-tool-messages)

The closing uses `finish-call` with a full farewell in `bot_say`, followed by the native hang-up tool with an empty start message. Vapi finishes the dynamic farewell before calling the signed endpoint; its completion response is required by the hang-up tool's rejection plan. The endpoint needs no Calendar, Firestore or email access. The prompt keeps these steps sequential and avoids a duplicate spoken goodbye. This approach follows the caller's conversation language: Vapi's native multilingual end-message selection still chose English in a Spanish test with automatic Soniox transcription. [Tool rejection plans](https://docs.vapi.ai/tools/tool-rejection-plan)

A thank-you alone does not authorize closing. Both the prompt and finish-call tool description require an explicit goodbye, no-further-help statement, disconnect request or recording objection. Follow-up questions must be answered first. Spoken appointment times use words in the caller's language, while tool arguments retain ISO timestamps.

Voice formatting aliases pronounce MarktMind as “Market Mind” and GetZelling as “Get Zelling” while retaining the written brands. Market questions receive a short, constructive response, a report offer or an agent handoff; Gizelle does not supply current statistics, forecasts or market opinions. The client-app description is limited to the owner's confirmed capabilities: organizing appointments and open houses and tracking milestones once a property is under contract. Access instructions and further app capabilities await additional owner-provided material.

The refinements are deployed on revision `receptionist-staging-00007-lq2`. A Spanish self-call returned the intended generic market response and report/agent offer, described the three confirmed app capabilities, and said “Un momento, por favor” before checking an exact requested slot. Separate Spanish and English closing calls each delivered one complete farewell, received the completion acknowledgment, and then ended through the guarded native tool with no additional speech. The shortened notice and pause took approximately 16.9 seconds in these calls, and the audit recorded disclosure v2. No booking was attempted in these checks. Local verification passed 17 tests, with five persistence tests skipped because the Firestore emulator was not running.

## Scheduling refinements and news pilot

Revision `receptionist-staging-00008-m5x` adds quarter-hour starts and same-conversation rescheduling. All 34 backend tests passed, including the Firestore persistence cases against the local emulator. Signed live staging checks created a listing at 12:45, moved the same event to 13:15, rejected an accidental duplicate, preserved the original when another event blocked a move, and moved it again to 14:00. Replaying older requests returned the current 14:00 time. Event ID, location/contact description and one-hour reservation were preserved. All synthetic Calendar events from these checks were removed.

The phone instructions now spell money amounts in full words, retain report acceptance/decline state in the conversation, and avoid repeated report offers. Voice formatting disables dollarAmount while preserving the other configured formatters. This prevents monetary shorthand from changing “one million dollars” into an awkward reading; spoken results still require live voice acceptance.

The final prompt update is deployed on revision `receptionist-staging-00009-zbv`, with finish-call tool v2. An English self-call generated “one million dollars” and “ten thousand dollars” in the model completion, recorded report acceptance without repeating the offer, gave the generic market response and client-app explanation, and completed its farewell before hang-up. A Spanish self-call created one Plan de venta at 12:45, moved that same event to 13:15, and retained the address, callback number and hour-long calendar block without volunteering a duration. After “Gracias. ¿A qué hora quedó mi única cita?”, Jackie answered the time and stayed on the line until “Eso es todo.” The farewell completed before hang-up. Both calls persisted transcript, recording reference and notice audit, and Brevo accepted both lead emails. Synthetic Calendar entries were verified and removed; historical duplicate entries from the owner's earlier tests were not changed.

The news archive is intended for website retrieval only. `backend/knowledge/news-sample-preview-20251027-20251102.json` is a local, unindexed extraction preview of the supplied 13-page, 12-article digest. It is not a public knowledge source. Each article needs source verification and approval before ingestion. Missing or shortened URLs and conflicting stated dates are flagged. The digest period, article publication date and statistical reporting period remain separate; a 2025 archive must not answer a current-market question as though it were current.

Checking the original El Cronista article recovered its missing URL and found a material mismatch: the publisher describes domestic Argentine real estate activity, while article 5 of the digest claims Miami demand and capital flight. That digest entry is marked excluded_pending_correction. Its summary, findings and narrative must not enter the public index without correction and review. The remaining articles still require source verification.

Begin the website pilot with 20–30 articles across different dates and subjects, plus 10–15 representative questions and expected sources. Include market statistics, condos/HOA/insurance, new development, luxury transactions and later corrections or updates. Existing selectable-text PDFs are suitable. For new material, use consistent headings in Google Docs, DOCX or Markdown and retain full original source URLs. The ingestion pipeline should preserve the original document in private GCS and generate per-article UTF-8 text and structured metadata; the content owner need not prepare JSON manually.

The next implementation stages are source/date review, private GCS upload and normalization, an approved-news-only retrieval index, and website chat responses with source links and dates. Evaluate historical versus current questions, missing evidence, English/Spanish responses and corrections before public release. Lead records, call recordings, secrets and unpublished website drafts must remain outside the public retrieval corpus.

### Prepared article pilot

`backend/knowledge/news-pilot/inventory.json` catalogs the 23 consecutive weekly Google Docs from May 26 through November 2, 2025. Four source documents were read and normalized into 54 article records in `articles.json`; the remaining 19 documents have metadata inventory only, not completed content audits. Original native-document IDs, revision IDs, UTF-16 source ranges, digest periods, stated publication dates, source URLs and extraction hashes are retained. Month-only dates remain month-only, and article dates outside the digest week are flagged rather than rewritten.

`selection.json` chooses 30 articles: six from May 26–June 1, eight from July 21–27, five from September 1–7 and eleven from October 20–26. Topics include market statistics, condos, development, luxury, financing and international buyers. The selected source URLs are present and distinct; that check does not establish that the destination pages or their claims are correct. All records remain needs_source_verification, public_retrieval_allowed=false and runtime_ingestion=false. Narrative commentary is stored separately from summaries and findings. A political timeline claim in the May digest and three out-of-week publication dates are explicitly flagged for review.

`evaluation.json` contains 15 designed, unexecuted retrieval/answer checks covering English/Spanish historical questions, digest/publication/reporting dates, current-information abstention, source instructions treated as untrusted text, exclusion of CRM artifacts and AVN remaining deferred. No vector index, model call, public answer endpoint or cloud resource was created for this preparation.

AVN is deferred until its owner reports readiness and customer-approved outputs. Keep a future structured-metrics source separate from the article index; it must not supply inferred values or incomplete outputs to the website or phone. Article-based website retrieval can proceed independently while later weekly digests are added.

The preferred hosted news architecture is private GCS originals, Firestore article metadata/vector search and Google-hosted embeddings authenticated through the Cloud Run service identity. This requires API enablement and scoped IAM access when implemented, not a new API-key secret. The current local preparation requires no additional secret. Existing receptionist secrets and the telephone configuration are unchanged. See [Cloud Run service identity](https://docs.cloud.google.com/run/docs/securing/service-identity), [AI API authentication](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/gcp-auth), and [Firestore vector search](https://firebase.google.com/docs/firestore/vector-search).

### Vertex private pilot deployment

The owner selected Vertex for this project on November 13, 2026. Other applications keep their existing Gemini Developer API integrations. `receptionist/vertex.py` is the single model client: explicit Vertex selection, project/location/model configuration, ADC credentials, no API-key fallback, bounded responses and one request attempt. Staging uses `gemini-3.1-flash-lite` for structured classification/answers and `gemini-embedding-001` with 768 dimensions for retrieval. Changing the embedding model or dimensions requires a compatible new corpus; the runtime checks these pins before querying.

The Vertex API is enabled. The `news-rag-staging` service account has a custom model-invocation role (`aiplatform.endpoints.predict` and `serviceusage.services.use`) and database-conditioned `roles/datastore.viewer` for the separate `news-rag-staging` database in us-east1. It has no receptionist-secret or CRM-database grant. A one-off job under the actual runtime identity confirmed allowed news metadata reads, denied reads of a deliberately nonexistent CRM probe document, and no Secret Manager version-access permission; it did not read any secret value. Its receipt is `backend/knowledge/news-pilot/access-proof.json`.

Private GCS bucket `gz-ai-receptionist-news-staging` has uniform bucket access and public-access prevention. Immutable source captures and manifests are stored under the corpus digest, with generation preconditions and hash checks. The selected 30 articles produced 29 indexed articles: the May entry with a flagged political timeline claim was quarantined. All indexed articles remain unverified, `public_retrieval_allowed=false`. Vector indexing is not source approval.

The current pinned corpus and model settings are in `backend/news-staging.yaml` and `backend/knowledge/news-pilot/vertex-staging-receipt.json`. `backend/scripts/ingest_news.py` archives the source captures and creates review-only vectors, resumes matching chunks, and marks a corpus ready only when its complete chunk count is present. Its explicit `--gcloud-user` mode uses the operator's CLI token in memory for local ingestion. The deployed runtime uses ADC and never executes gcloud or reads a credential file.

The separate FastAPI entrypoint `receptionist.news_app:app` is deployed as `news-rag-staging-00001-z2q`, with Cloud Run IAM enforcement and no unauthenticated invocation. `/chat` accepts one bounded question. It classifies historical/current/valuation/AVN/private/unsafe requests, filters publication dates separately from digest dates, retrieves only the server-pinned news corpus and returns validated citation links. Current-market questions abstain using the historical coverage boundary. The output schema constrains citations to retrieved article IDs; the application independently checks IDs, citation numbers and URLs. Private and public corpus modes fail closed on mismatched visibility and source-approval flags. AVN, CRM and phone tools are unavailable to this service.

The live Vertex/Firestore evaluation passed 15/15 designed retrieval, language, date, citation and abstention checks. This is not independent verification of the publisher claims or a guarantee of factual accuracy. An authenticated deployed-service Spanish smoke check also passed; an unauthenticated health request received 403. All 47 backend tests passed with the local Firestore emulator, including the existing booking persistence checks. The Next.js production build passed, and seven local preview bridge checks passed.

Use the local preview instructions in `frontend/README.md` to inspect answers and original source links. The public website and telephone receptionist do not use this news corpus. Next steps are correcting/verifying the selected articles, marking an approved corpus, evaluating answer fidelity against original sources, and integrating the approved retrieval path into the website widget with public-entrypoint authentication and abuse controls.

### Source review and preview refinement

The November 13 source review accounts for all 30 selected candidates in `backend/knowledge/news-pilot/source-review.json`; the readable report is `source-review.html` in the same directory. Fifteen corrected excerpts match accessible publisher text. Fifteen candidates are excluded pending evidence because the source body was unavailable, the link expired, detailed claims were unchecked, or the original publication date could not be established. Two retained publisher articles were readable in indexed body text after direct access returned a challenge. Verification applies only to the retained excerpts, not to each original digest’s full narrative or an independent audit of the publisher’s datasets.

Material changes include corrected China search-country rankings; year-to-date scope for the older-condo days-on-market comparison; October 18 as the Fisher Island article date; and 499 apartments rather than an unsupported apartment/condo split for Calta’s proposed Health District tower. The obsolete Zillow investor link was replaced with its matching publisher release. Original Google Docs captures and normalized digest records are preserved.

The new private corpus is `3b481a3e516494dc9ae7e75d209ea7773e75f7083a71e42dff4dc19c83182a66`, pinned in `backend/news-staging.yaml` and `source-reviewed-staging-receipt.json`. The isolated Cloud Run service now serves revision `news-rag-staging-00002-lh5`. Ingestion’s explicit `--review-audit` option validates the original source hash and complete candidate coverage, replaces unchecked text with the checked excerpt only, archives the review manifest and excludes unresolved articles. The corpus remains `private_review` with public retrieval disabled.

The preview now has collapsible source lists, an Enter-to-send switch (off by default; Shift+Enter remains multiline), warmer introductory wording and revised answer-tone instructions. A narrow root-body hydration exception tolerates extension-injected attributes without suppressing hydration warnings within the app. Sixteen news/review tests and seven bridge tests passed. Five live checks passed for corrected Fisher Island publication date in Spanish, year-to-date comparison scope, corrected search-country ranking, current-market abstention and abstention on the excluded West Palm pipeline claims. Their receipt is `source-reviewed-live-checks.json`. Browser checks confirmed normal multiline entry, Shift+Enter, Enter-to-send and keyboard-operated source disclosure, with no captured console warnings/errors. The temporary builder grant was removed after deployment.

The private combined widget now opens with Gizelle at `/` or the historical news search at `/news`. Both use the same conversation view. See [widget setup](frontend/README.md) for the operator preview, consent path and public rollout dependencies. The website assistant has its own saved Vapi configuration and the phone number continues to use the telephone assistant.
