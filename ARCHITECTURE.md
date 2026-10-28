# UrbanBot architecture

UrbanBot is an event-driven serverless system in `us-east-1`. WhatsApp ingress
is normalized by the compute module and queued for the agent tools. Those tools
store reports and incidents in DynamoDB and publish domain events to the custom
EventBridge bus. The portal reads the same incident data through AppSync and
also publishes status and escalation events.

Personal-data deletion is a dedicated agent tool. After explicit confirmation,
the agent invokes `delete_my_data`, whose isolated Lambda deletes the citizen's
user and saved-place records, removes identity and phone attributes from their
reports, and leaves incidents and report counts intact. The audit table receives
only a hashed subject identifier and deletion totals. Its IAM role can access
only the users, places, reports, audit tables, reports `by-user` index, KMS key,
and its own logs.

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
