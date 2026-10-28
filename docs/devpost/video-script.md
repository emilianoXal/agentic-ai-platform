# UrbanBot video script (maximum 3:00)

Use only synthetic reports, locations, names and media. Record the WhatsApp phone and the officials portal side by side.

| Time | On-screen | Narration | Capture |
| --- | --- | --- | --- |
| 0:00–0:15 | Title card, then a resident next to a water leak. | “A leak, a pothole, a dead streetlight. Residents rarely know where to report it or what happened afterwards. UrbanBot turns WhatsApp into a direct, trackable channel to the city.” | Title card and a short phone shot. |
| 0:15–0:45 | WhatsApp chat with +1 319 271 6611: the resident sends a photo and a description. The bot replies in English and asks for consent. The resident accepts. | “The resident writes to UrbanBot and sends a photo. Before anything else, the agent asks for consent. The model records the answer with a tool, with no keyword list.” | Real conversation on the phone. |
| 0:45–1:10 | The resident shares a WhatsApp location. The bot confirms the report. | “The resident shares a location. The report is created with the photo and the place. Faces and license plates in the photo are blurred before it is stored.” | Chat, then the confirmation reply. |
| 1:10–1:45 | Officials portal: the new incident on the map, its readable title, its status, the photo and the report count. | “In the officials portal the report appears as an incident on a map, with a readable title and the right department. Nearby reports join the same incident instead of creating duplicates. The department gets an email through Amazon SES, and the portal marks it sent only once SES sent it.” | Incidents list, map pin, detail view, the email status. |
| 1:45–2:05 | Role views in the portal: admin, supervisor, department operator. | “Access is role-based: administrators, supervisors, and operators who only see their own department.” | Switch between prepared sessions. |
| 2:05–2:25 | Staff mark the incident resolved in the portal. | “When staff mark the incident resolved, the portal schedules a follow-up with Amazon EventBridge Scheduler.” | Status change control. |
| 2:25–2:45 | WhatsApp: «Is it fixed?» arrives. The resident answers in their own words, for example that it is still broken, and the portal shows the incident reopened. | “The resident gets “Is it fixed?” on WhatsApp and answers in their own words. The model reads the answer and either confirms the fix or reopens the incident.” | Chat and the reopened incident in the portal. |
| 2:45–3:00 | Architecture diagram, highlighting the path. | “Every WhatsApp message in and out goes through AWS End User Messaging Social. Amazon Bedrock runs the agent behind guardrails, tools own the data in DynamoDB, and Amazon SES reaches the department. UrbanBot closes the loop between residents and their city.” | `docs/architecture/urbanbot-architecture.png` |

## Recording notes

- Record the happy path once, in order: photo, consent, location, report, portal, resolved, «Is it fixed?», reopen.
- Keep the phone number visible, and keep identifiers out of any log or console shown.
- AgentCore Gateway and Memory are off in dev; do not show them. Conversation history is kept in DynamoDB.
