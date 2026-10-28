"""urbanbot outbound Lambda.

The ONE and only place that imports the AWS End User Messaging Social
`socialmessaging` SDK and holds the `socialmessaging:SendWhatsAppMessage`
permission (hackathon rule RB-01). Both the consumer (conversational reply)
and the notifier (proactive notifications) reach it via lambda.invoke.

Invoked with a JSON payload:
    {"to": "<recipient wa id>",
     "text": "<reply text>",
     "origination_phone_number_id": "<arn-or-id>"}

Returns (never raises for ordinary failures -- mirrors the agent/tool contract):
    success          -> {"ok": True,  "message_id": "<id if present>"}
    validation fail  -> {"ok": False, "error": "invalid_input"}
    send fail        -> {"ok": False, "error": "send_failed"}

Uses only the stdlib + boto3 (bundled in the python3.12 Lambda runtime; the
bundled boto3 includes the socialmessaging client).
"""

import hashlib
import json
import logging
import os
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# --- Config from environment -------------------------------------------------
META_API_VERSION = os.environ.get("META_API_VERSION", "v20.0")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
# RB-01: the CDS SDK import + client. send_whatsapp_message is called below.
_social = boto3.client("socialmessaging")

# --- Structured JSON-line logger ---------------------------------------------
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


def _phone_number_id(value):
    """Normalize an EUM phone-number ARN to the bare phone-number id.

    send_whatsapp_message wants the id; ingest propagates the full ARN
    (context.MetaPhoneNumberIds[].arn). Split on the specific delimiter the
    ingest handler already proves (":phone-number-id/"), NOT a blind
    last-segment split -- the id contains no "/". A bare id (or an unknown
    shape) is passed through unchanged (VP-3).
    """
    if not value:
        return None
    s = str(value)
    if ":phone-number-id/" in s:
        return s.split(":phone-number-id/", 1)[1]
    return s


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    to = event.get("to")
    text = event.get("text")
    origination = event.get("origination_phone_number_id")

    # --- Validation: closed error set, never raise ---------------------------
    if not (isinstance(to, str) and to.strip()):
        _log(logging.WARNING, "invalid_input", recipient=_mask_phone(to), field="to")
        return {"ok": False, "error": "invalid_input"}
    if not (isinstance(text, str) and text.strip()):
        _log(logging.WARNING, "invalid_input", recipient=_mask_phone(to), field="text")
        return {"ok": False, "error": "invalid_input"}
    if not (isinstance(origination, str) and origination.strip()):
        _log(
            logging.WARNING,
            "invalid_input",
            recipient=_mask_phone(to),
            field="origination_phone_number_id",
        )
        return {"ok": False, "error": "invalid_input"}

    to = to.strip()
    text = text.strip()

    wa_obj = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    # TODO(confirm-on-first-send): raw UTF-8 JSON bytes, not base64 (botocore
    # base64-encodes the blob automatically) - VP-1.
    message_bytes = json.dumps(wa_obj).encode("utf-8")

    origination_id = _phone_number_id(origination)

    try:
        resp = _social.send_whatsapp_message(
            originationPhoneNumberId=origination_id,
            message=message_bytes,
            # TODO(confirm-on-first-send): META_API_VERSION default "v20.0";
            # bump the env var (no code change) if the first send returns a
            # version error - VP-2.
            metaApiVersion=META_API_VERSION,
        )
    except (ClientError, BotoCoreError) as exc:
        error_code = None
        if isinstance(exc, ClientError):
            error_code = exc.response.get("Error", {}).get("Code")
        _log(
            logging.ERROR,
            "send_failed",
            recipient=_mask_phone(to),
            origination_id=origination_id,
            error_code=error_code,
        )
        return {"ok": False, "error": "send_failed"}
    except Exception:  # noqa: BLE001 - never let an exception escape the handler
        logger.exception(json.dumps({"event": "send_error"}))
        return {"ok": False, "error": "send_failed"}

    message_id = resp.get("messageId") if isinstance(resp, dict) else None
    _log(
        logging.INFO,
        "sent",
        recipient=_mask_phone(to),
        origination_id=origination_id,
        text_len=len(text),
    )
    return {"ok": True, "message_id": message_id}
