# UrbanBot architecture

UrbanBot is an event-driven serverless system in `us-east-1`. WhatsApp ingress
is normalized by the compute module and queued for the agent tools. Those tools
store reports and incidents in DynamoDB and publish domain events to the custom
EventBridge bus. The portal reads the same incident data through AppSync and
also publishes status and escalation events.

The compute module has two outbound event consumers. `notifier` handles citizen
notification events for the WhatsApp channel. `dependency-mailer` handles an
incident's initial route (`StatusChanged` from `urbanbot.agent`) and portal
escalations (`IncidentEscalated`). It enriches each event from the incidents
table, conditionally records the EventBridge event id in the audit table, and
sends a Spanish agency notice with SES v2. The mail contains operational
incident fields only; citizen identity, phone, and saved places never enter the
message. Terraform provisions the Lambda, EventBridge rule, SES identities, and
least-privilege IAM policy.
