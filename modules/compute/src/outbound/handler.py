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
    """Return an originationPhoneNumberId accepted by send_whatsapp_message.

    The API requires one of two shapes (per the AWS pattern
    `(^phone-number-id-.*$)|(^arn:.*:phone-number-id/[0-9a-zA-Z]+$)`):
      1. a bare id that STARTS WITH `phone-number-id-`, or
      2. the FULL ARN `arn:...:phone-number-id/<id>`.

    ingest propagates the full ARN (context.MetaPhoneNumberIds[].arn). We pass
    that ARN through UNCHANGED -- it already matches form 2. Splitting on
    ":phone-number-id/" would yield only the trailing hash (e.g.
    "e644d37f...") WITHOUT the required "phone-number-id-" prefix, which fails
    the pattern with a ValidationException -- the bug this replaces. A value
    that already starts with "phone-number-id-" (form 1) is also passed
    through. Anything else is passed through verbatim and will surface as a
    send_failed from the API.
    """
    if not value:
        return None
    return str(value)


# NOTE on Mexican numbers (521 vs 52): WhatsApp delivers the Mexican sender as a
# 13-digit wa_id starting 521... When REPLYING we must send to that exact wa_id,
# so this path intentionally does NOT rewrite 521->52 — doing so caused
# "Invalid destination phone number". A 521->52 normalization is only correct
# when INITIATING a conversation to a dialed/stored number (not this reply path),
# so no normalization helper is applied here.


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

    # Do NOT normalize the recipient for REPLIES. WhatsApp hands us the Mexican
    # sender as a 13-digit wa_id starting 521...; to reply we must use that same
    # wa_id verbatim. Rewriting 521->52 produced "Invalid destination phone
    # number" because 52... is not the wa_id WhatsApp knows this user by. The
    # 521->52 normalization only applies when INITIATING to a dialed number
    # (e.g. from a form/CRM), which this reply path never does.
    to = to.strip()
    text = text.strip()

    wa_obj = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    # The `message` blob is the WhatsApp Cloud API object as a JSON STRING, not
    # pre-encoded bytes. The AWS-documented working example passes the raw
    # json.dumps(...) string directly; adding .encode("utf-8") produced an
    # InvalidParametersException because the extra byte wrapping malformed the
    # payload EUM expects.
    message_payload = json.dumps(wa_obj)

    origination_id = _phone_number_id(origination)

    try:
        resp = _social.send_whatsapp_message(
            originationPhoneNumberId=origination_id,
            message=message_payload,
            metaApiVersion=META_API_VERSION,
        )
    except (ClientError, BotoCoreError) as exc:
        error_code = None
        error_message = None
        if isinstance(exc, ClientError):
            err = exc.response.get("Error", {})
            error_code = err.get("Code")
            # The EUM Error.Message explains WHICH parameter is invalid (e.g.
            # "Invalid message version", "Failed to parse WhatsApp message
            # request"). It's an AWS validation string, not user PII, so it is
            # safe to log and is essential for diagnosing InvalidParametersException.
            error_message = err.get("Message")
        _log(
            logging.ERROR,
            "send_failed",
            recipient=_mask_phone(to),
            origination_id=origination_id,
            error_code=error_code,
            error_message=error_message,
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
