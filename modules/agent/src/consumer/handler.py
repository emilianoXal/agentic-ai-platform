"""urbanbot SQS consumer Lambda.

Drains the data module's FIFO ingest queue (SQS event-source mapping). Parses the
normalized message the compute ingest Lambda enqueued, logs it with PII masking,
writes a lightweight inbound audit record, then synchronously invokes the Strands
agent Lambda (AGENT_FUNCTION_NAME) and classifies its response.

Error handling is the SQS ESM partial-batch-failure contract (NOT the ingest
swallow-and-continue): per-record try/except, failed messageIds returned in
batchItemFailures so only those ride the existing ingest-queue redrive to the DLQ.
A retriable agent outcome is signaled by raising ValueError inside the record so
it fails ONLY that record and never escapes lambda_handler.

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
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
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
AGENT_FUNCTION_NAME = os.environ.get("AGENT_FUNCTION_NAME", "")
OUTBOUND_FUNCTION_NAME = os.environ.get("OUTBOUND_FUNCTION_NAME", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Agent error codes worth a redrive; everything else (incl. invalid_input,
# tool_invoke_failed, and unknown values) is terminal.
RETRIABLE_AGENT_ERRORS = {"bedrock_throttled", "internal"}

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")
_lambda = boto3.client("lambda")

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
    origination_phone_number_id = msg.get("origination_phone_number_id")

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
        origination_phone_number_id=origination_phone_number_id,
    )

    # Synchronously invoke the agent with the FULL parsed msg (Decision 2 shape:
    # do not reconstruct field-by-field, so no field is silently dropped).
    resp = _lambda.invoke(
        FunctionName=AGENT_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(msg).encode(),
    )

    raw = resp["Payload"].read()
    try:
        payload = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        payload = {}

    # Classification order (Decision 6 + resolved points): a FunctionError or any
    # retriable/garbled outcome raises ValueError to fail ONLY this record.
    if resp.get("FunctionError"):
        _log(logging.WARNING, "agent_invoked", message_id=message_id,
             user_hash=_hash_id(user_id), ok=None,
             function_error=resp.get("FunctionError"))
        raise ValueError("agent_function_error")

    ok = payload.get("ok")
    error = payload.get("error")

    _log(logging.INFO, "agent_invoked", message_id=message_id,
         user_hash=_hash_id(user_id), ok=ok, error=error)

    if ok is True:
        # Dispatch the agent's reply to the WhatsApp outbound Lambda,
        # fire-and-forget (InvocationType="Event") so a transient send hiccup
        # never redrives this record and re-invokes the (expensive, possibly
        # state-mutating) agent turn. The reply MUST come from the AGENT
        # response payload, never from the inbound msg.get("text").
        #
        # NOTE: invalid_input canned replies are intentionally NOT delivered
        # this iteration — dispatch happens only when ok is True AND reply is a
        # non-empty string. (Backlog: deliver the invalid_input canned prompt.)
        reply = payload.get("reply")
        if reply and reply.strip() and OUTBOUND_FUNCTION_NAME:
            try:
                _lambda.invoke(
                    FunctionName=OUTBOUND_FUNCTION_NAME,
                    InvocationType="Event",
                    Payload=json.dumps({
                        "to": user_id,
                        "text": reply,
                        "origination_phone_number_id": origination_phone_number_id,
                    }).encode(),
                )
                _log(logging.INFO, "outbound_dispatched",
                     user=_mask_phone(user_id), reply_len=len(reply))
            except (ClientError, BotoCoreError, TypeError, ValueError):
                # Fire-and-forget: the agent turn already succeeded, so swallow
                # a dispatch failure and do NOT re-raise — this must not alter
                # the agent-invoke classification or batchItemFailures.
                _log(logging.WARNING, "outbound_dispatch_failed",
                     user=_mask_phone(user_id))
        elif not OUTBOUND_FUNCTION_NAME:
            _log(logging.INFO, "outbound_skipped_unconfigured",
                 user=_mask_phone(user_id))
        return  # processed
    if ok is False and error in RETRIABLE_AGENT_ERRORS:
        raise ValueError("agent_retry")
    if ok is False:
        return  # terminal error (e.g. invalid_input, tool_invoke_failed)
    # ok missing/None or body empty/garbled -> retriable.
    raise ValueError("agent_retry")


def lambda_handler(event, context):
    records = event.get("Records", []) if isinstance(event, dict) else []
    failures = []

    for record in records:
        try:
            _process_record(record)
        except (ClientError, BotoCoreError, ValueError, TypeError):
            message_id = record.get("messageId")
            logger.exception(json.dumps({"event": "record_failed",
                                         "messageId": message_id}))
            if message_id:
                failures.append({"itemIdentifier": message_id})

    _log(logging.INFO, "batch_done", total=len(records), failed=len(failures))
    return {"batchItemFailures": failures}
