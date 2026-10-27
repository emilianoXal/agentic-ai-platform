"""urbanbot ingest Lambda.

SNS inbound (fan-out of inbound WhatsApp events) -> normalized message -> SQS
FIFO ingest queue. Real-but-minimal glue: idempotency dedup, consent check,
rate limit, input guard, then enqueue. Messages are NEVER dropped for consent
or rate-limit reasons -- they are annotated with flags and still enqueued.

Uses only the stdlib + boto3 (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- Config from environment -------------------------------------------------
INGEST_QUEUE_URL = os.environ.get("INGEST_QUEUE_URL", "")
USERS_TABLE = os.environ.get("USERS_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "60"))
MAX_TEXT_LEN = int(os.environ.get("MAX_TEXT_LEN", "4096"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_sqs = boto3.client("sqs")
_ddb = boto3.client("dynamodb")

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


def _parse_message(record):
    """Extract the inner message JSON from an SNS record, tolerating gaps."""
    sns = record.get("Sns", {}) or {}
    raw = sns.get("Message", "")
    try:
        msg = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        # Non-JSON payload: treat the raw string as the text body.
        msg = {"text": raw}
    if not isinstance(msg, dict):
        msg = {"text": str(msg)}

    user_id = msg.get("from") or msg.get("user_id")
    return {
        "user_id": user_id,
        "message_id": msg.get("message_id") or sns.get("MessageId"),
        "type": msg.get("type", "text"),
        "text": msg.get("text"),
        "media": msg.get("media"),
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


def _process_record(record):
    msg = _parse_message(record)
    user_id = msg["user_id"]
    message_id = msg["message_id"]

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
    safe_text = _sanitize_text(msg["text"])

    normalized = {
        "user_id": user_id,
        "message_id": message_id,
        "type": msg["type"],
        "text": safe_text,
        "media": msg["media"],
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
        type=msg["type"],
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


def lambda_handler(event, context):
    records = event.get("Records", []) if isinstance(event, dict) else []
    results = {"enqueued": 0, "duplicate": 0, "error": 0}

    for record in records:
        try:
            outcome = _process_record(record)
            results[outcome] = results.get(outcome, 0) + 1
        except Exception:  # noqa: BLE001 - log and continue; do not drop batch
            results["error"] += 1
            logger.exception(json.dumps({"event": "record_failed"}))

    _log(logging.INFO, "batch_done", **results)
    return results
