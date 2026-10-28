# Urbanbot video script (maximum 3:00)

| Time | On-screen | Narration | Capture |
| --- | --- | --- | --- |
| 0:00–0:20 | A short title, then a resident facing a pothole/leak report on a phone. | “Urban issues are reported every day, but residents often have no clear path to report them or learn what happened next. Urbanbot turns WhatsApp into a direct, trackable civic channel.” | Phone close-up and title card. |
| 0:20–0:40 | WhatsApp conversation: resident describes an issue and sends location/photo. | “A resident starts where they already are: WhatsApp. Urbanbot is designed to capture a description, location, and media, then turn that message into an operational workflow.” | Real inbound WhatsApp message to +1 319 271 6611, with synthetic data only. |
| 0:40–1:05 | The ingest/queue flow and a report/incident appearing in the portal. | “Inbound WhatsApp events flow through AWS End User Messaging Social, SNS, Lambda, and a FIFO queue. The agent uses constrained tools to create a report or join a nearby incident rather than writing data directly.” | CloudWatch-safe logs with identifiers masked; then portal incident and cluster view. |
| 1:05–1:30 | Portal incident list, cluster/detail view, map, and report count. | “Instead of creating disconnected tickets, Urbanbot groups nearby reports into an incident. Teams can see the cluster, its priority, and the evidence needed to coordinate a response.” | Incidents page, select a clustered incident, show map and report count. |
| 1:30–1:55 | Change incident status in the portal, then show updated state. | “An authorized official changes the incident status in the portal. That creates a domain event for the notifier flow, giving the platform a path to proactive resident updates.” | Status-change control and resulting updated incident. Do not claim a WhatsApp delivery. |
| 1:55–2:20 | Brief role comparison: admin, supervisor, operator views/permissions. | “The portal separates responsibilities: administrators manage the demo and access, supervisors coordinate work, and agency operators work only within their assigned scope.” | Sign in or switch between prepared role sessions; show allowed versus restricted action. |
| 2:20–2:40 | WhatsApp screen beside portal state. | “The agent conversation and the officials portal are two views of the same workflow: residents report simply, while teams gain actionable, shared context.” | Split screen of the inbound conversation and corresponding portal incident. |
| 2:40–3:00 | Architecture diagram with the highlighted end-to-end path. | “This serverless architecture keeps the model behind guardrails and scoped Lambda tools, stores operational state in DynamoDB, and connects the portal with AppSync and Amplify. Urbanbot makes civic reporting more visible, coordinated, and accountable.” | `docs/architecture/urbanbot-architecture.png`, zooming across the inbound, agent, portal, and EventBridge paths. |

## Recording notes

- Use only synthetic reports, locations, names, and media.
- The outgoing WhatsApp response is **pending recording**: the committed runtime code does not yet call `SendWhatsAppMessage`. Show the generated/returned agent reply only if it is clearly labeled “pending outbound handoff”; do not portray it as delivered.
- AgentCore Gateway and Memory are disabled in dev. Do not show them as active services.
