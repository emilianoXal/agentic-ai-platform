# UrbanBot

## Inspiration

Reporting a pothole, a water leak, a broken streetlight or a trash pile should not mean navigating a portal, repeating the same issue to different people, or never learning what happened next. UrbanBot meets residents in WhatsApp, the app they already use, groups nearby reports into one shared incident, routes it to the right municipal department, and tells the resident when it is resolved.

## What it does

A resident writes to **+1 319 271 6611** on WhatsApp. The bot answers in English and, using Amazon Bedrock, walks the resident through one report:

- **Consent first.** The model asks for consent in its own words and records the answer with the `register_consent` tool; there is no keyword list.
- **Photo and location.** A WhatsApp shared location is attached to the report, and so is a photo sent before the location. Faces and license plates are blurred before the photo is stored.
- **One incident, many reports.** Nearby reports of the same category join the same incident instead of creating separate tickets.
- **The right department.** Each category in the catalog maps to a municipal department. When a report is created or escalated, that department receives an email through Amazon SES, and the portal marks the notice as `sent` only after SES accepted it.
- **Officials portal.** An Amplify-hosted portal shows incidents on a map with readable titles built from category and place, statuses, report counts and role-based access (admin, supervisor, department operator).
- **Closing the loop.** When staff mark an incident resolved, the portal schedules an «Is it fixed?» WhatsApp message with Amazon EventBridge Scheduler. The model interprets the resident's answer in their own words and either confirms the fix or reopens the incident.

The demo uses synthetic data and does not replace emergency services.

## How we built it

Everything runs in one AWS account in `us-east-1` and is defined as Terraform.

**WhatsApp in and out with AWS End User Messaging Social.** Inbound messages arrive as events on Amazon SNS. An ingest Lambda validates them, applies consent and rate-limit flags and places them on an Amazon SQS FIFO queue. A consumer Lambda invokes the agent. Every outbound message, whether an agent reply, a status notice or the «Is it fixed?» question, goes through a single outbound Lambda, the only caller of `socialmessaging` `SendWhatsAppMessage`.

**Agent.** A Strands agent on AWS Lambda uses Claude Sonnet 5.5 on Amazon Bedrock with Bedrock Guardrails. It can act only through narrowly scoped tool Lambdas (create report, join incident, get status, register consent, register place, route, escalate); those tools own all DynamoDB access. Conversation history is kept in Amazon DynamoDB.

**Photos.** WhatsApp media is downloaded only after consent into a KMS-encrypted Amazon S3 bucket. An AWS Step Functions workflow calls Amazon Rekognition to detect faces and plate-shaped text, and an image Lambda blurs them. Reports reference only the blurred copy.

**Portal.** Amazon Cognito, AWS AppSync, AWS Amplify Hosting, Amazon Location Service and a dashboard API Lambda. Status changes emit Amazon EventBridge events to the notifier and the dependency mailer.

**Delivery.** A GitLab pipeline authenticates to AWS with OIDC, runs Terraform validation and plans on every branch and limits manual deployment jobs to `main`.

## Challenges we ran into

The central challenge was keeping an agent useful without letting it write directly to operational data. We combined deterministic checks before the model runs, Bedrock Guardrails, typed tools, least-privilege IAM and tool-owned data access. Privacy shaped the design too: consent precedes any action, logs mask identifiers, and photos are blurred before they are stored.

WhatsApp itself taught us a lot. `SendWhatsAppMessage` only accepts recipients in E.164 form, a photo can arrive before the location it belongs to, and free-text replies only deliver inside WhatsApp's open conversation window. We also made the portal honest about delivery: the department email is marked `sent` only when SES actually sent it, and a department is shown only when the category really maps to one.

## Accomplishments that we're proud of

- A complete loop from WhatsApp to the department's inbox and back to the resident: report, incident, email, resolution, «Is it fixed?», confirm or reopen.
- Consent, interpretation of the follow-up answer and routing decided by the model through typed tools, with no phrase lists.
- Faces and plates blurred before a photo is stored.
- Both CDS services integrated in running code: End User Messaging Social for WhatsApp and Amazon SES for email.
- Everything described here is deployed from Terraform through a pipeline without long-lived AWS keys.

## What we learned

Letting the model decide, but only through small tools that own the data, is easier to test and to trust than a long prompt. Real WhatsApp traffic differs from fixtures: photos before locations, number formats and conversation windows all need explicit handling. Testing outbound messages in simulated mode first made the final real sends uneventful.

## What's next

- Voice-note transcription with Amazon Transcribe and multimodal classification with Amazon Nova.
- Amazon Bedrock AgentCore Gateway and Memory, which are feature-flagged and off today; conversation history currently lives in DynamoDB.
- Measuring classification quality on a synthetic evaluation set and publishing the results.
- Onboarding real municipal departments, with their own verified mailboxes and WhatsApp templates.

## Built with

**AWS services:** AWS End User Messaging Social (WhatsApp), Amazon SES, Amazon Bedrock (Claude Sonnet 5.5) and Bedrock Guardrails, AWS Lambda, Amazon SNS, Amazon SQS (FIFO), Amazon DynamoDB, Amazon S3, AWS KMS, AWS Step Functions, Amazon Rekognition, Amazon EventBridge and EventBridge Scheduler, AWS AppSync, Amazon Cognito, AWS Amplify Hosting, Amazon Location Service, AWS WAF, Amazon CloudWatch.

**Languages and frameworks:** Python, TypeScript, Angular, GraphQL, Strands Agents SDK, MapLibre GL, Terraform, GitLab CI/CD.
