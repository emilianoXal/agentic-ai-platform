# UrbanBot architecture

UrbanBot is an event-driven serverless system in `us-east-1`. WhatsApp ingress
is normalized by the compute module and queued for the agent tools. Those tools
store reports and incidents in DynamoDB and publish domain events to the custom
EventBridge bus. The portal reads the same incident data through AppSync and
also publishes status and escalation events.

Personal-data deletion is a dedicated agent tool with a two-turn confirmation
that relies on AgentCore Memory conversation history. The agent asks the citizen
to reply `CONFIRMO BORRAR MIS DATOS`; the `delete_my_data` wrapper refuses unless
`AGENTCORE_MEMORY_ID` is set and the current inbound message is that phrase
(ignoring case, accents, and punctuation), and it always targets the event's sender `user_id`, never a value chosen
by the model. Its isolated Lambda deletes the citizen's user and saved-place
records, removes the phone from `incidents.subscribers`, removes identity and
phone attributes from their reports, and leaves incidents and report counts
intact. The audit table receives only a hashed subject identifier and deletion
totals. Its IAM role can access only the users, places, reports, audit tables,
reports `by-user` index, incident subscriber scan and updates, KMS key, and its own logs.

The compute module has two outbound event consumers. `notifier` handles citizen
notification events for the WhatsApp channel. `dependency-mailer` handles an
incident's initial route (`StatusChanged` from `urbanbot.agent`), portal
escalations (`IncidentEscalated`), and automatic agent escalations
(`IncidentNearby` from `urbanbot.agent` with status `ESCALATED`). It enriches
each event from the incidents table, conditionally records both the EventBridge
event id and the incident change (creation or escalation) in the audit table, so
retries and agent/portal events for the same escalation send one notice, and
sends a Spanish agency notice with SES v2. The mail contains operational
incident fields only; citizen identity, phone, and saved places never enter the
message. Terraform provisions the Lambda, EventBridge rule, SES identities, and
least-privilege IAM policy.

The manual GitLab `agent:conversations` job invokes the deployed dev agent with
the consumer's normalized event contract. It records three runs per Sonnet
conversation case, correlates tool Lambda logs and DynamoDB observations, and
publishes JSON and Markdown transcripts as CI artifacts; it never sends a real
WhatsApp message.

In dev, the agent Lambda persists each consenting citizen's conversation through
the Strands AgentCore Memory session manager. While `consent_pending` is true the
agent runs without a session manager, so nothing from that turn is persisted.
Actor and session identifiers are HMAC-SHA256 of the citizen number keyed by a
Terraform-created Secrets Manager secret (generated write-only, never in state;
the Lambda receives only its ARN), so the phone number cannot be recovered from
them by brute force. The memory is encrypted with the project CMK and expires
events after 7 days. Before each turn the agent deletes any persisted messages
after the last final assistant reply, so a retried failure cannot leave an
unanswered turn that breaks role alternation. QA and production keep the
integration disabled unless their environment flag is set.
