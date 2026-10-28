"""urbanbot ingest Lambda.

SNS inbound (AWS End User Messaging Social WhatsApp events, plus the flat
simulator JSON) -> normalized message -> SQS FIFO ingest queue.
Real-but-minimal glue: idempotency dedup, consent check, rate limit, input
guard, then enqueue. Messages are NEVER dropped for consent or rate-limit
reasons -- they are annotated with flags and still enqueued. Status receipts
are logged and not enqueued.

Uses only the stdlib + boto3 (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# --- Config from environment -------------------------------------------------
INGEST_QUEUE_URL = os.environ.get("INGEST_QUEUE_URL", "")
USERS_TABLE = os.environ.get("USERS_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
MEDIA_STATE_MACHINE_ARN = os.environ.get("MEDIA_STATE_MACHINE_ARN", "")
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "60"))
MAX_TEXT_LEN = int(os.environ.get("MAX_TEXT_LEN", "4096"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_sqs = boto3.client("sqs")
_ddb = boto3.client("dynamodb")
_sfn = boto3.client("stepfunctions")

# --- Structured JSON-line logger ---------------------------------------------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Strip ASCII control chars (except common whitespace) as an input guard.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _log(level, event, **fields):
    """Emit one structured JSON log line. Never logs raw PII."""
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))


def _mask_phone(value):
    """PII masking: keep only the last 4 digits of a phone/user id."""
    if not value:
        return None
    s = str(value)
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 4:
        return "****" + digits[-4:]
    return "****"


def _hash_id(value):
    """Stable, non-reversible id for correlating logs without exposing PII."""
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Media objects in Meta's messages webhook carry the asset id under the type key
# (image.id, audio.id, …). Documented for EUM inbound media at:
# https://docs.aws.amazon.com/social-messaging/latest/userguide/managing-event-destination-dlrs.html
_MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")


def _sns_envelope(record):
    """Return (parsed SNS Message, SNS attributes) for one Lambda SNS record."""
    sns = record.get("Sns", {}) or {}
    raw = sns.get("Message", "")
    try:
        msg = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        msg = {"text": raw}
    if not isinstance(msg, dict):
        msg = {"text": str(msg)}
    return msg, sns


def _origination_phone_number_id(envelope):
    """AWS phone-number resource ARN used as SendWhatsAppMessage origination.

    EUM SNS has no top-level originationPhoneNumberId; it lives on
    context.MetaPhoneNumberIds[].arn.
    """
    context = envelope.get("context")
    phones = context.get("MetaPhoneNumberIds") if isinstance(context, dict) else None
    if isinstance(phones, list) and phones and isinstance(phones[0], dict):
        arn = phones[0].get("arn")
        if isinstance(arn, str) and ":phone-number-id/" in arn:
            return arn
    return None


def _text_from_wa(message):
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if isinstance(text, dict):
        return text.get("body")
    if isinstance(text, str):
        return text
    mtype = message.get("type")
    blob = message.get(mtype) if mtype in _MEDIA_TYPES else None
    if isinstance(blob, dict):
        return blob.get("caption")
    return None


def _media_from_wa(message):
    if not isinstance(message, dict):
        return None
    if message.get("media") is not None:
        return message.get("media")
    mtype = message.get("type")
    blob = message.get(mtype) if mtype in _MEDIA_TYPES else None
    if isinstance(blob, dict) and blob.get("id"):
        out = {"id": blob["id"]}
        if blob.get("mime_type"):
            out["mime_type"] = blob["mime_type"]
        return out
    return None


def _decode_webhook_entry(envelope):
    """Parse whatsAppWebhookEntry (JSON string of one Meta webhook entry)."""
    raw = envelope.get("whatsAppWebhookEntry")
    if not isinstance(raw, str):
        raise ValueError("whatsAppWebhookEntry is not JSON")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("whatsAppWebhookEntry is not an object")
    return parsed


def _iter_eum_items(envelope, entry, fallback_id):
    origin = _origination_phone_number_id(envelope)
    changes = entry.get("changes") or []
    if not isinstance(changes, list):
        return
    for change in changes:
        if not isinstance(change, dict):
            continue
        value = change.get("value") or {}
        if not isinstance(value, dict):
            continue
        messages = value.get("messages") or []
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                yield {
                    "kind": "message",
                    "user_id": message.get("from"),
                    "message_id": message.get("id") or fallback_id,
                    "type": message.get("type") or "text",
                    "text": _text_from_wa(message),
                    "media": _media_from_wa(message),
                    "origination_phone_number_id": origin,
                }
        statuses = value.get("statuses") or []
        if isinstance(statuses, list):
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                yield {
                    "kind": "status",
                    "user_id": status.get("recipient_id"),
                    "message_id": status.get("id") or fallback_id,
                    "status": status.get("status"),
                    "origination_phone_number_id": origin,
                }


def _parse_message(record):
    """Yield normalized items from one SNS record.

    Flat simulator JSON (`from` / `text`) stays one inbound message.
    AWS End User Messaging Social publishes context + whatsAppWebhookEntry
    (JSON string of a Meta webhook entry with changes[].value.messages[]
    and changes[].value.statuses[]):
    https://docs.aws.amazon.com/social-messaging/latest/userguide/managing-event-destination-dlrs.html
    """
    envelope, sns = _sns_envelope(record)
    fallback_id = sns.get("MessageId")

    if "whatsAppWebhookEntry" in envelope:
        try:
            entry = _decode_webhook_entry(envelope)
        except (ValueError, TypeError):
            _log(logging.WARNING, "webhook_parse_failed")
            return
        if not entry:
            _log(logging.WARNING, "webhook_parse_failed")
            return
        yield from _iter_eum_items(envelope, entry, fallback_id)
        return

    yield {
        "kind": "message",
        "user_id": envelope.get("from") or envelope.get("user_id"),
        "message_id": envelope.get("message_id") or fallback_id,
        "type": envelope.get("type", "text"),
        "text": _text_from_wa(envelope),
        "media": envelope.get("media"),
        "origination_phone_number_id": _origination_phone_number_id(envelope),
    }


def _already_processed(message_id):
    """Idempotency (RNF-05): conditional PutItem dedup marker in the audit log.

    Also serves as the RF-15 audit trail for inbound messages. Returns True if
    the message_id was seen before (ConditionalCheckFailedException).
    """
    if not message_id:
        return False
    try:
        _ddb.put_item(
            TableName=AUDIT_TABLE,
            Item={
                "entity_id": {"S": "msgid#" + str(message_id)},
                "ts": {"S": _now_iso()},
                "kind": {"S": "ingest"},
            },
            ConditionExpression="attribute_not_exists(entity_id)",
        )
        return False
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def _check_consent(user_id):
    """Consent / opt-in (RF-38). Returns True if consent is granted.

    Missing record or ungranted consent returns False -- the caller still
    enqueues the message with consent_pending=true (never drops it).
    """
    if not user_id:
        return False
    try:
        resp = _ddb.get_item(
            TableName=USERS_TABLE,
            Key={"user_id": {"S": str(user_id)}},
        )
    except ClientError:
        return False
    item = resp.get("Item")
    if not item:
        return False
    consent = item.get("consent", {})
    return consent.get("BOOL") is True


def _check_rate_limit(user_id):
    """Rate limit (RF-10/RNF-04). Non-blocking: increments a per-hour counter
    and returns True if the user is now over the configured limit."""
    if not user_id:
        return False
    bucket = "rate_" + datetime.now(timezone.utc).strftime("%Y%m%d%H")
    try:
        resp = _ddb.update_item(
            TableName=USERS_TABLE,
            Key={"user_id": {"S": str(user_id)}},
            UpdateExpression="ADD #c :one",
            ExpressionAttributeNames={"#c": bucket},
            ExpressionAttributeValues={":one": {"N": "1"}},
            ReturnValues="UPDATED_NEW",
        )
    except ClientError:
        return False
    count = int(resp.get("Attributes", {}).get(bucket, {}).get("N", "0"))
    return count > RATE_LIMIT_PER_HOUR


def _sanitize_text(text):
    """Input guard (RNF-07): truncate to MAX_TEXT_LEN and strip control chars."""
    if text is None:
        return None
    s = str(text)
    if len(s) > MAX_TEXT_LEN:
        s = s[:MAX_TEXT_LEN]
    return _CONTROL_CHARS.sub("", s)


def _prepare_media(item):
    media = item.get("media")
    if item.get("type") != "image" or not isinstance(media, dict) or not media.get("id"):
        return media
    if not MEDIA_BUCKET or not MEDIA_STATE_MACHINE_ARN or not item.get("origination_phone_number_id"):
        raise ValueError("image media pipeline is not configured")
    media_id = str(media["id"])
    message_id = str(item.get("message_id") or media_id)
    object_id = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]
    sanitized_key = "sanitized/" + object_id
    payload = {
        "bucket": MEDIA_BUCKET,
        "mediaId": media_id,
        "originationPhoneNumberId": item["origination_phone_number_id"],
        "sanitizedKey": sanitized_key,
    }
    _sfn.start_execution(
        stateMachineArn=MEDIA_STATE_MACHINE_ARN,
        name=object_id,
        input=json.dumps(payload),
    )
    return [sanitized_key]


def _process_item(item):
    if item.get("kind") == "status":
        _log(
            logging.INFO,
            "whatsapp_status",
            message_id=item.get("message_id"),
            status=item.get("status"),
            user=_mask_phone(item.get("user_id")),
            user_hash=_hash_id(item.get("user_id")),
        )
        return "status"

    user_id = item.get("user_id")
    message_id = item.get("message_id")

    if _already_processed(message_id):
        _log(
            logging.INFO,
            "duplicate_skipped",
            message_id=message_id,
            user=_mask_phone(user_id),
        )
        return "duplicate"

    consent_granted = _check_consent(user_id)
    rate_limited = _check_rate_limit(user_id)
    safe_text = _sanitize_text(item.get("text"))
    media_dropped = None
    media = []
    if item.get("type") == "image" and not consent_granted:
        media_dropped = "consent_pending"
    elif item.get("type") == "image" and rate_limited:
        media_dropped = "rate_limited"
    else:
        try:
            media = _prepare_media(item)
        except (BotoCoreError, ClientError):
            media_dropped = "processing_error"
    if media_dropped:
        _log(
            logging.INFO,
            "media_dropped",
            message_id=message_id,
            user_hash=_hash_id(user_id),
            reason=media_dropped,
        )

    normalized = {
        "user_id": user_id,
        "message_id": message_id,
        "type": item.get("type") or "text",
        "text": safe_text,
        "media": media,
        "media_dropped": media_dropped,
        "origination_phone_number_id": item.get("origination_phone_number_id"),
        "received_at": _now_iso(),
        "consent_pending": not consent_granted,
        "rate_limited": rate_limited,
    }

    # MessageGroupId/DeduplicationId require non-empty values on a FIFO queue.
    group_id = str(user_id) if user_id else "unknown"
    dedup_id = str(message_id) if message_id else _hash_id(json.dumps(normalized))

    _sqs.send_message(
        QueueUrl=INGEST_QUEUE_URL,
        MessageBody=json.dumps(normalized, default=str),
        MessageGroupId=group_id,
        MessageDeduplicationId=dedup_id,
    )

    _log(
        logging.INFO,
        "enqueued",
        message_id=message_id,
        user=_mask_phone(user_id),
        user_hash=_hash_id(user_id),
        type=normalized["type"],
        text_len=len(safe_text) if safe_text else 0,
        consent_pending=normalized["consent_pending"],
        rate_limited=rate_limited,
    )
    if rate_limited:
        _log(
            logging.WARNING,
            "rate_limited",
            user=_mask_phone(user_id),
            limit=RATE_LIMIT_PER_HOUR,
        )
    return "enqueued"


def _process_record(record):
    outcomes = []
    for item in _parse_message(record):
        outcomes.append(_process_item(item))
    return outcomes


def lambda_handler(event, context):
    records = event.get("Records", []) if isinstance(event, dict) else []
    results = {"enqueued": 0, "duplicate": 0, "error": 0, "status": 0}

    for record in records:
        try:
            for outcome in _process_record(record):
                results[outcome] = results.get(outcome, 0) + 1
        except Exception:  # noqa: BLE001 - log and continue; do not drop batch
            results["error"] += 1
            logger.exception(json.dumps({"event": "record_failed"}))

    _log(logging.INFO, "batch_done", **results)
    return results
