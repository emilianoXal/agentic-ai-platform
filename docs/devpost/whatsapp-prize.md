# Best WhatsApp Solution: UrbanBot

UrbanBot uses AWS End User Messaging Social as its only WhatsApp channel, for both directions. The WhatsApp Business Account and the phone number **+1 319 271 6611** are managed in End User Messaging Social. Residents write to that number and the bot answers in English.

## Inbound

**WhatsApp → End User Messaging Social → Amazon SNS → ingest Lambda → Amazon SQS FIFO → consumer Lambda → agent.**

End User Messaging Social publishes each webhook event to an SNS topic. The ingest Lambda decodes the `whatsAppWebhookEntry` (`modules/compute/src/ingest/handler.py:141`), extracts messages and delivery statuses, preserves the phone-number ARN needed to reply, applies consent and rate-limit flags, and enqueues the message. It handles text, shared locations and photos. A shared location is attached to the report, and a photo sent before the location is held for the resident and attached when the report is created. Photos are fetched with `GetWhatsAppMessageMedia` only after consent, and faces and license plates are blurred before the photo is stored.

## Outbound

Every message the bot sends goes through one outbound Lambda, the only caller of `socialmessaging` `SendWhatsAppMessage` (`modules/compute/src/outbound/handler.py:154`):

- **Agent replies.** The consumer Lambda hands each reply to the outbound Lambda (`modules/agent/src/consumer/handler.py:166`).
- **Status notices.** The notifier Lambda sends them when staff change an incident's status (`modules/compute/src/notifier/handler.py:324`).
- **«Is it fixed?» follow-up.** When staff mark an incident resolved, the portal schedules the message with EventBridge Scheduler (`modules/portal/src/dashboard_api/handler.py:454`). The follow-up Lambda sends it through the same outbound Lambda (`modules/follow_up/src/handler.py:129`).

The outbound Lambda sends to the sender's own WhatsApp ID in E.164 form (it adds the leading `+` that `SendWhatsAppMessage` requires), so replies reach Mexican numbers as WhatsApp reports them.

## One conversation, end to end

1. A resident sends a photo and a description.
2. The bot asks for consent. The model records the answer with the `register_consent` tool, with no keyword list.
3. The resident shares a WhatsApp location, and the report is created with the blurred photo and the location.
4. The department receives an email through Amazon SES, and the portal shows the incident on its map.
5. Staff mark the incident resolved. The resident gets «Is it fixed?» on WhatsApp.
6. The resident answers in their own words, and the model confirms the fix or reopens the incident.

End User Messaging Social works together with Amazon SES (email to the department), Amazon Bedrock (the agent), Amazon EventBridge Scheduler, Amazon Rekognition and AWS Step Functions (photo blurring).

Free-text delivery requires an open WhatsApp conversation window, so proactive messages outside it need an approved template.
