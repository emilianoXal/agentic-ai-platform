"""urbanbot SQS consumer Lambda.

Drains the data module's FIFO ingest queue (SQS event-source mapping). Parses the
normalized message the compute ingest Lambda enqueued, logs it with PII masking,
writes a lightweight inbound audit record. FEAT-002 adds the synchronous
invoke of the agent Lambda (AGENT_FUNCTION_NAME); today this is a no-op after
the audit write.

Error handling is the SQS ESM partial-batch-failure contract (NOT the ingest
swallow-and-continue): per-record try/except, failed messageIds returned in
batchItemFailures so only those ride the existing ingest-queue redrive to the DLQ.

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
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
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
AGENT_FUNCTION_NAME = os.environ.get("AGENT_FUNCTION_NAME", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")

# --- Structured JSON-line logger (PII-masking; mirrors compute/ingest) -------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


def _log(level, event, **fields):
    """Emit one structured JSON log line. Never logs raw PII."""
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))


def _mask_phone(value):
    """PII masking: keep only the last 4 digits of a phone/user id."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
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


def _process_record(record):
    body = record.get("body", "")
    try:
        msg = json.loads(body) if body else {}
    except (ValueError, TypeError):
        msg = {}
    if not isinstance(msg, dict):
        msg = {}

    user_id = msg.get("user_id")
    message_id = msg.get("message_id") or record.get("messageId")
    msg_type = msg.get("type", "text")
    text = msg.get("text")

    # Lightweight inbound audit record (same-key overwrite keeps retries
    # idempotent). Never store or log raw text — length only.
    _ddb.put_item(
        TableName=AUDIT_TABLE,
        Item={
            "entity_id": {"S": "inbound#" + str(message_id)},
            "ts": {"S": _now_iso()},
            "kind": {"S": "consumer"},
            "user_hash": {"S": _hash_id(user_id) or "none"},
            "type": {"S": str(msg_type)},
        },
    )

    _log(
        logging.INFO,
        "inbound_consumed",
        message_id=message_id,
        user=_mask_phone(user_id),
        user_hash=_hash_id(user_id),
        type=msg_type,
        text_len=len(text) if text else 0,
        consent_pending=msg.get("consent_pending"),
        rate_limited=msg.get("rate_limited"),
    )

    # FEAT-002 adds the synchronous invoke of AGENT_FUNCTION_NAME here.


def lambda_handler(event, context):
    records = event.get("Records", []) if isinstance(event, dict) else []
    failures = []

    for record in records:
        try:
            _process_record(record)
        except (ClientError, ValueError, TypeError):
            message_id = record.get("messageId")
            logger.exception(json.dumps({"event": "record_failed",
                                         "messageId": message_id}))
            if message_id:
                failures.append({"itemIdentifier": message_id})

    _log(logging.INFO, "batch_done", total=len(records), failed=len(failures))
    return {"batchItemFailures": failures}
