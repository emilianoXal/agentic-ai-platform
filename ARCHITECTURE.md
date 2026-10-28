# UrbanBot architecture

UrbanBot is an event-driven serverless system in `us-east-1`. WhatsApp ingress
is normalized by the compute module and queued for the agent tools. Those tools
store reports and incidents in DynamoDB and publish domain events to the custom
EventBridge bus. The portal reads the same incident data through AppSync and
also publishes status and escalation events. An incident title is the
category with a street or neighborhood, or the category alone; the citizen's
free text is never the title because it can carry personal data. A geohash never
appears in the title, including rows already stored as "near {geohash}". The
portal translates category titles (EN/ES). Map markers are HTML dots with MapLibre
anchor `center`, absolute positioning, and no transform of their own, so the dot
stays on the coordinate at every zoom.

Personal-data deletion is a dedicated agent tool with two-turn confirmation.
The agent asks the citizen to reply `CONFIRMO BORRAR MIS DATOS`; the wrapper
requires a configured conversation backend and that exact current inbound phrase
(ignoring case, accents, and punctuation). It always targets the inbound sender,
never a model-selected identity. The isolated Lambda deletes the citizen's user,
saved places and conversation history, removes incident subscriptions and
anonymizes reports while preserving incident counts. History deletion queries all
pages by the same HMAC citizen key and deletes each item, including expired items.
If erasure fails or time runs short, it returns `memory_erasure_failed` rather
than claiming completion. Confirmation turns load history but never persist a
new pair after the purge. Optional AgentCore events and memory records are also
erased when that backend is enabled. Audit records contain only subject hashes,
counts and erasure status.

Citizen opt-in is a dedicated `register_consent` tool. Ingest reads `users[user_id].consent` as a DynamoDB BOOL and, when it is missing or false, still enqueues the turn with `consent_pending` (it never drops the message). The model decides from free text whether the citizen accepted; it has no phrase list. On accept it calls `register_consent`, which `UpdateItem`s the users table under the exact `user_id` key ingest, `register_place`, `follow_up` and `delete_my_data` read (no normalization), setting `consent` true and `consent_at`. The wrapper clears `consent_pending` for the rest of that turn after a successful write, so a report request in the same message can proceed. The model must not claim the consent was stored until the tool returns `ok`. The tool role may `dynamodb:UpdateItem` only on the users table, plus the shared data CMK. Rejection or ambiguity must not call the tool. The live wording matrix is the manual GitLab `agent:conversations` job (`scripts/conversation_matrix.py` cases C14–C16).

The compute module has two outbound event consumers. `notifier` handles citizen
WhatsApp notices in English with the portal short folio (`UB-YYYY-XXXXXX`) and
the concrete status (for example `Your report UB-2026-A20FF7 is now In progress`).
It claims each notice in the audit table so EventBridge retries do not repeat
it: the agent's route event (`urbanbot.agent`) is claimed once per
incident+status+citizen, while portal `StatusChanged` events add the EventBridge
event `id`, so a later `in_progress` or `reopened` after a reopen cycle still notifies.
Resolved status is owned by the follow-up Lambda (`Is it fixed?`), not the
notifier. `dependency-mailer` handles an
incident's initial route (`StatusChanged` from `urbanbot.agent`), portal
escalations (`IncidentEscalated`), and automatic agent escalations
(`IncidentNearby` from `urbanbot.agent` with status `ESCALATED`). It enriches
each event from the incidents table, conditionally records both the EventBridge
event id and the incident change (creation or escalation) in the audit table, so
retries and agent/portal events for the same escalation send one notice, and
sends a Spanish agency notice with SES v2. The mailer's IAM role uses the same
data CMK (`kms:Decrypt`, `kms:GenerateDataKey`) as ingest and the notifier so
encrypted DynamoDB reads and the dedupe `PutItem` can succeed. After SES accepts
a mail to the category's agency it sets only `dependency_mail_sent_at` (status
stays `OPEN` for the agent tools) plus an audit line `dependency_mail_sent`; a
fallback-supervisor send records only `supervisor_mail_sent`. Marking failures
after SES are logged (`dependency_mail_mark_failed`), not retried. The portal
maps `OPEN` to `received` until both `routed_to` and `dependency_mail_sent_at`
are present; only then does the read model become `sent_to_agency`. A supervisor
fallback keeps `received` and the timeline text `Escalated to the supervisor: no
agency mailbox`.
A supervisor "Send to agency" click must name an agency whose category has a
mailbox in `dependency_email_map` (the dialog lists only those); it sets
`routed_to` and emits `StatusChanged` (source `urbanbot.dashboard`, no
neighbors) that the dependency mailer sends to that agency's mailbox. Only after
an agency send writes `dependency_mail_sent_at` does the mailer label the report
rows `Enviado a dependencia` and emit one `StatusChanged` (source
`urbanbot.mailer`, with the neighbors' user ids) that the mailer itself ignores.
An incident routed to an agency without a mailbox (Seguridad Ciudadana,
Supervisor municipal) is a supervisor escalation: escalated, never sent or
pending send. A stored `sent_to_agency` missing `routed_to`
or `dependency_mail_sent_at` reads as the display-only `pending_send`
("Received, pending send"); the item is not rewritten.
`create_report` stores only the closed catalog `agua`, `bacheo`, `alumbrado`,
`basura`, `drenaje`, `arbol`, `plagas`, `seguridad`, and `otro` (the explicit
fallback). Any other code,
including ones the model invents, is rejected with `unknown_category` and is
not written, so the model chooses again from `allowed`. The agent wrapper calls
`route` after a successful create or a create-and-join, with the incident's
stored category; it passes the incident id (writing `routed_to`) only when the
incident has no `routed_to` yet, so an attach still gets the route reply. `otro` resolves to
`Supervisor municipal` and the mailer sends that notice to the supervisor
fallback. `route` returns `has_mailbox` (category in `dependency_email_map`)
and a `reply_instruction`: without a mailbox the bot says the notice went to the
municipal supervisor, never to the dependency. The short live matrix is the `category_probe` cases inside the manual
GitLab `agent:conversations` job; its markdown counts the category the model
chose and whether the incident was routed.
The mail contains operational incident fields only; citizen identity, phone, and
saved places never enter the message. Terraform provisions the Lambda,
EventBridge rule, SES identities, and least-privilege IAM policy.

The manual GitLab `agent:conversations` job invokes the deployed dev agent with
the consumer's normalized event contract. It records three runs per Sonnet
conversation case, correlates tool Lambda logs and DynamoDB observations, and
publishes JSON and Markdown transcripts as CI artifacts; it never sends a real
WhatsApp message.

The agent Lambda loads the latest ten completed conversation turns from the
CMK-encrypted DynamoDB conversation-history table into Strands `messages` before
invoking the model. Each item holds one user/assistant pair, keyed by HMAC-SHA256
citizen identity and an ordered timestamp. Pairs are written only after a valid
reply; failed, timed-out and empty replies leave no orphan turn to restore.
Items expire after seven days with DynamoDB TTL; reads also exclude expired
items while asynchronous TTL deletion catches up. Read or write failures log
metadata only and allow the current response to continue without history.
`consent_pending` turns neither load nor save conversation history. Only dev
sets `enable_conversation_history = true`; QA and production create no history
table and keep the agent stateless unless their environment flag is set.

The HMAC key is held in a CMK-encrypted Secrets Manager secret and encrypted
Terraform state; Lambdas receive its ARN. Agent and erasure IAM grants are scoped
to the history table (Query/PutItem and Query/DeleteItem respectively), the
identity secret and project key. Dev sets `enable_agentcore_memory = false` so
its apply creates no AgentCore Memory. The optional AgentCore session backend
remains available when no DynamoDB history table is configured; its restore
still discards messages newer than the last final assistant reply.

The consumer's read timeout exceeds the agent timeout and its batch size is one.
The queue visibility timeout covers six consumer timeouts, preventing duplicate
in-flight turns from one SQS delivery. Terraform preconditions enforce these
relationships. Runtime history and erasure regressions run with
`python3 -m pytest -q modules/agent/tests/test_conversation_history.py`; mocked
Terraform plans assert the table configuration and disabled memory resource.

Inbound WhatsApp images take a privacy-gated path before their references reach
the agent. Images from users without opt-in consent or over the rate limit are
never downloaded. Otherwise ingest starts the compute module's Step Functions
workflow and queues only a deterministic `sanitized/` S3 key. When the image is
not processed, ingest still queues the message with no media reference and a
PII-free `media_dropped` reason (`consent_pending`, `rate_limited`, or
`processing_error` when media preparation fails, including missing pipeline
configuration or origination number and AWS `StartExecution` errors); the agent prompt then asks for
opt-in or explains the reason and asks the citizen to resend the photo, even
when the photo had no caption. Report media is attached server-side and only
as `sanitized/` keys; the model cannot supply or omit media. Ingest also records each started `sanitized/` key in the
pending-media table, keyed only by a SHA-256 of the sender's `user_id`, with a
one-hour per-key expiry plus DynamoDB TTL cleanup. `create_report`, and
`join_incident` when it creates a report from `category`+`geohash`, receive the
current message's `sanitized/` keys and atomically consume (`DeleteItem` with `ALL_OLD`) the unexpired pending keys, so a photo sent alone or before the location still lands on the citizen's next report. Creating a report with media sets `photo_count` on the incident so the portal Photos section is non-empty. The media-download Lambda passes the full origination phone-number ARN into `GetWhatsAppMessageMedia` (the same contract as outbound send). A sanitized key is attached even when the Step Functions blur has not finished writing the object. A photo without a caption is valid input: the agent asks for the description and location. WhatsApp `location` messages (including forwarded ones) enqueue a
structured `location` object with `lat`, `lng`, and optional `name`/`address`,
plus a readable `[Shared location: …]` text. The agent stores that location
only on the conversation-history item of the turn that shared it, as pending
data: it expires after 30 minutes or when a report is created, whichever comes
first. While pending, the prompt says how many minutes ago it was shared and
`create_report` uses it only when the model sends no `lat`/`lng`. Likewise, the sender's `user_id` comes from the inbound
event and is injected server-side into `create_report`, `join_incident`,
`get_status`, `register_consent`, and `register_place`; it is not a model-facing tool parameter. The workflow downloads the WhatsApp
asset into the KMS-encrypted media bucket, calls Rekognition `DetectFaces` and
`DetectText`, and invokes the media Lambda to blur face boxes and plate-shaped
alphanumeric text lines. Images with no sensitive regions are copied unchanged.
Raw objects and every noncurrent raw version expire after one day; sanitized
objects and their noncurrent versions expire after 30 days. The bucket is
private and blocks all public access. The download call follows AWS End User
Messaging Social's `GetWhatsAppMessageMedia` contract: `mediaId` and
`originationPhoneNumberId` are required, while `destinationS3File` supplies the
S3 `bucketName` and key prefix. The service writes `raw/<mediaId>.<ext>`, so the
download Lambda derives the raw key from the returned `mimeType`. See the [AWS API reference](https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_GetWhatsAppMessageMedia.html)
and [download guide](https://docs.aws.amazon.com/social-messaging/latest/userguide/receive-message-image.html).

When staff mark an incident resolved, the portal first creates a one-time UTC
EventBridge Scheduler schedule in the default group (`cdshack-*`, deleted after
completion). The configurable delay is two minutes in dev and 60 minutes in QA
and production. Its execution role can invoke only the follow-up Lambda. The portal
conditionally records the due timestamp and an empty delivery map on the
incident; a failed write leaves a harmless schedule whose generation check skips
the send. A later resolution gets a fresh generation, so old schedules and old
citizen answers cannot affect it.

The follow-up Lambda reads the incident's reports, deduplicates their citizens,
checks current consent and pause preferences, and synchronously invokes the
existing outbound Lambda. It adds no WhatsApp client or channel permission.
Conditional per-citizen reservations on the incident prevent duplicate sends;
an uncertain channel outcome remains reserved rather than risking another
message. Only an acknowledged send becomes a pending question; a failure the
outbound Lambda reports releases the reservation for the Scheduler retry. The
reservation keys are hashes and contain no new phone attributes; recipient
identity remains in the existing reports/users records. Delayed free-text WhatsApp messages still
require an open WhatsApp service conversation window; the demo delay stays short.

Before a consenting agent turn, the agent queries that sender's pending follow-ups
through the follow-up Lambda. Sonnet interprets free text and calls
`respond_follow_up` to confirm the resolution or reopen the incident. Ambiguous
answers request clarification; unrelated messages and injected instructions do
not authorize changes. The wrapper binds the sender and resolution generation
outside model arguments, and the Lambda rechecks report ownership and pending
state before a conditional update. Confirmation retains `resolved`; reopening
stores the portal's existing `reopened` status and relabels the report rows.
Both answers append a `citizen_confirmed` or `citizen_reopened` audit entry to
the incident timeline. The portal shows a follow-up as pending until the
schedule has run and afterwards only while an acknowledged question awaits an
answer. No new UI is needed.
See `docs/oficios/tester.md` for local tests and the deferred post-apply model
matrix, which runs against the deployed agent with team test numbers only.
