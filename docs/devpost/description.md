# UrbanBot

## Inspiration

Reporting a pothole, leak, broken streetlight, or trash pile should not mean navigating a portal, repeating the same issue to different people, or losing track of what happened next. UrbanBot meets residents in WhatsApp, groups nearby reports into a shared incident, and gives municipal teams a focused operational view.

## What it does

UrbanBot accepts citizen messages through WhatsApp, normalizes inbound events, and queues them for an agentic workflow. The agent uses Amazon Bedrock and narrowly scoped Lambda tools to create reports, join an existing incident, look up status, register a place, route a request, or escalate an incident. Operational data lives in DynamoDB.

Officials use an AWS Amplify-hosted dashboard backed by AppSync to view incidents, inspect report clusters, change status, and work within role-based permissions. Status changes emit domain events for the notifier flow. The MVP uses synthetic municipal data and does not replace emergency services.

## How we built it

The platform is Terraform infrastructure in AWS account `636487155766`, region `us-east-1`. Amazon End User Messaging Social publishes WhatsApp inbound events to Amazon SNS; an ingest Lambda applies deterministic validation, consent and rate-limit flags, then places work on an Amazon SQS FIFO queue. A consumer Lambda invokes the Strands agent Lambda. The agent uses Amazon Bedrock Claude Sonnet 5.5 with Guardrails and invokes six Lambda tools; those tools own DynamoDB access.

The officials portal uses Amazon Cognito, AWS AppSync, AWS Amplify Hosting, Amazon Location, Lambda, and DynamoDB. EventBridge carries domain events to the notifier Lambda. CI/CD is a GitLab pipeline using AWS OIDC, Terraform validation and plans on branches, with manual deployment jobs limited to `main`.

## Challenges we ran into

The important challenge was keeping an agent useful without allowing it to write directly to operational data. We addressed it with deterministic checks before model use, Bedrock Guardrails, explicit typed tools, least-privilege IAM, and tool-owned data access. We also designed for privacy: consent precedes actions, logs mask identifiers, and the media pipeline is deliberately marked as future work.

The outbound WhatsApp handoff is not complete today: the notifier records what it would send, but it does not yet create a `socialmessaging` client or call `SendWhatsAppMessage` at runtime. This is planned work, not a demonstrated capability. AgentCore Gateway is also flag-gated and disabled in dev, as is AgentCore Memory. Consenting citizens' conversation history is kept in DynamoDB for 7 days.

## What's next

We will complete the runtime End User Messaging Social outbound call, connect agent replies to that channel, and validate it with controlled test messages. We will add the planned media workflow for retrieval, face/plate blurring, transcription, and multimodal classification. We also plan to enable and secure AgentCore Gateway when the identity-provider configuration is ready, while continuing to measure classification quality on a synthetic evaluation set.
