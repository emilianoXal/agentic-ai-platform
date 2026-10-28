# Best WhatsApp Solution: UrbanBot

UrbanBot is designed around WhatsApp as the citizen channel for urban-infrastructure reports. A resident can send a text, location, or media message to the project WhatsApp number; the inbound path is implemented as **WhatsApp → AWS End User Messaging Social → Amazon SNS → ingest Lambda → Amazon SQS FIFO**.

## End User Messaging Social and WABA

The WhatsApp Business Account (WABA) and the WhatsApp phone number are managed through AWS End User Messaging Social. The configured project number for judges is **+1 319 271 6611**. End User Messaging Social publishes inbound webhook events to the project SNS topic. `modules/compute/src/ingest/handler.py:141` decodes the `whatsAppWebhookEntry`; `:152` extracts messages and delivery statuses; `:96` preserves the originating phone-number ARN required by the outbound API.

## Inbound implementation

The SNS subscription invokes the ingest Lambda. It normalizes the event, records idempotency and audit information, applies consent/rate-limit flags, and sends a normalized message to the FIFO queue. The consumer Lambda invokes the Bedrock-powered agent, whose tool Lambdas persist reports and incidents in DynamoDB.

## Outbound implementation status

AWS End User Messaging Social's `SendWhatsAppMessage` API is the intended outbound mechanism for both agent replies and proactive status notifications. The notifier Lambda already receives EventBridge events and evaluates recipients, quiet hours, and daily caps in `modules/compute/src/notifier/handler.py:187`.

However, the runtime call is **planned, not implemented** in this revision: `modules/compute/src/notifier/handler.py:207` is an explicit stub; it does not import the `socialmessaging` client or invoke `SendWhatsAppMessage`. Likewise, `modules/agent/src/agent/handler.py:688` returns the generated reply without handing it to the outbound channel. The next implementation step is to create a regional `boto3.client("socialmessaging")` and call `send_whatsapp_message` with the WABA phone-number ARN, recipient, and approved message payload, then test it with controlled messages.

This distinction is intentional: the project does not claim a WhatsApp send that the committed runtime code does not perform.
