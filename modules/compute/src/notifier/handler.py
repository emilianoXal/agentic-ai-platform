"""urbanbot notifier Lambda.

EventBridge (StatusChanged / IncidentNearby on the custom bus) -> look up the
affected users -> quiet-hours / daily-cap gate -> STUBBED WhatsApp send. The
real CDS End User Messaging Social SendWhatsAppMessage call is left as a
clearly-marked TODO; no CDS SDK is imported here.

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
USERS_TABLE = os.environ.get("USERS_TABLE", "")
PLACES_TABLE = os.environ.get("PLACES_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
DAILY_CAP_DEFAULT = int(os.environ.get("DAILY_CAP_DEFAULT", "10"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

SUPPORTED_DETAIL_TYPES = ("StatusChanged", "IncidentNearby")

# --- Clients created at module load ------------------------------------------
_ddb = boto3.client("dynamodb")

# --- Structured JSON-line logger ---------------------------------------------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


def _log(level, event, **fields):
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))


def _mask_phone(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 4:
        return "****" + digits[-4:]
    return "****"


def _hash_id(value):
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat()


def _affected_user_ids(detail):
    """Resolve affected users from the event detail by id references only.

    No geohash proximity math -- that belongs to a later module. We read any
    user id references the producer put in the detail; for place-scoped events
    we look up the owning user via the places table.
    """
    ids = set()

    for key in ("user_id", "user_ids", "recipients"):
        val = detail.get(key)
        if isinstance(val, str):
            ids.add(val)
        elif isinstance(val, list):
            ids.update(str(v) for v in val if v)

    place_id = detail.get("place_id")
    if place_id:
        ids.update(_users_for_place(place_id))

    return [i for i in ids if i]


def _users_for_place(place_id):
    """Look up the user(s) that own a place via the places GSI/Query.

    The places table is keyed (user_id, place_id); we Query by place_id over a
    by-place index if present, else fall back to no users (never guesses).
    """
    try:
        resp = _ddb.query(
            TableName=PLACES_TABLE,
            IndexName="by-place",
            KeyConditionExpression="place_id = :p",
            ExpressionAttributeValues={":p": {"S": str(place_id)}},
        )
    except ClientError:
        return []
    return [
        item["user_id"]["S"]
        for item in resp.get("Items", [])
        if "user_id" in item
    ]


def _get_user(user_id):
    try:
        resp = _ddb.get_item(
            TableName=USERS_TABLE,
            Key={"user_id": {"S": str(user_id)}},
        )
    except ClientError:
        return None
    return resp.get("Item")


def _is_paused(user_item):
    return user_item.get("paused", {}).get("BOOL") is True


def _in_quiet_hours(user_item, now):
    """RF-25 quiet hours. Expects users.quiet_hours = {start, end} as "HH" or
    "HH:MM" strings (local-naive, compared against UTC hour for the stub).
    Returns True if 'now' falls inside the quiet window."""
    qh = user_item.get("quiet_hours", {}).get("M")
    if not qh:
        return False
    try:
        start = int(qh["start"]["S"].split(":")[0])
        end = int(qh["end"]["S"].split(":")[0])
    except (KeyError, ValueError, TypeError):
        return False
    hour = now.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # Window wraps midnight (e.g. 22 -> 7).
    return hour >= start or hour < end


def _daily_cap(user_item):
    cap = user_item.get("daily_cap", {}).get("N")
    try:
        return int(cap) if cap is not None else DAILY_CAP_DEFAULT
    except (ValueError, TypeError):
        return DAILY_CAP_DEFAULT


def _bump_daily_count(user_id, now):
    bucket = "notif_" + now.strftime("%Y%m%d")
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
        return 0
    return int(resp.get("Attributes", {}).get(bucket, {}).get("N", "0"))


def _audit_notification(user_id, template_id, detail_type):
    try:
        _ddb.put_item(
            TableName=AUDIT_TABLE,
            Item={
                "entity_id": {"S": "notif#" + str(user_id)},
                "ts": {"S": _now_iso()},
                "kind": {"S": "notify"},
                "detail": {"S": str(template_id or detail_type)},
                "detail_type": {"S": str(detail_type)},
            },
        )
    except ClientError:
        _log(logging.WARNING, "audit_write_failed", user_hash=_hash_id(user_id))


def _notify_user(user_id, detail_type, template_id, now):
    user_item = _get_user(user_id)
    if not user_item:
        _log(logging.INFO, "skipped_unknown_user", user=_mask_phone(user_id))
        return "skipped"

    if _is_paused(user_item):
        _log(logging.INFO, "skipped_paused", user=_mask_phone(user_id))
        return "skipped"

    if _in_quiet_hours(user_item, now):
        _log(logging.INFO, "skipped_quiet_hours", user=_mask_phone(user_id))
        return "skipped"

    count = _bump_daily_count(user_id, now)
    cap = _daily_cap(user_item)
    over_cap = count > cap

    phone = user_item.get("phone", {}).get("S") or user_id

    # --- STUBBED SEND --------------------------------------------------------
    # TODO: replace this WOULD_SEND log with the real CDS End User Messaging
    # Social SendWhatsAppMessage call (socialmessaging client). That belongs to
    # a later channel/agent module; do NOT import a CDS SDK here.
    if over_cap:
        _log(
            logging.INFO,
            "WOULD_SEND_DIGEST",
            recipient=_mask_phone(phone),
            template=template_id,
            detail_type=detail_type,
            daily_count=count,
            daily_cap=cap,
            note="over daily cap -- batched into digest instead of individual send",
        )
        outcome = "digest"
    else:
        _log(
            logging.INFO,
            "WOULD_SEND",
            recipient=_mask_phone(phone),
            template=template_id,
            detail_type=detail_type,
            daily_count=count,
            daily_cap=cap,
        )
        outcome = "sent"

    _audit_notification(user_id, template_id, detail_type)
    return outcome


def lambda_handler(event, context):
    detail_type = event.get("detail-type") if isinstance(event, dict) else None
    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    if not isinstance(detail, dict):
        detail = {}

    if detail_type not in SUPPORTED_DETAIL_TYPES:
        _log(logging.INFO, "ignored_detail_type", detail_type=detail_type)
        return {"ignored": True, "detail_type": detail_type}

    template_id = detail.get("template_id") or detail.get("template")
    now = _now()

    results = {"sent": 0, "digest": 0, "skipped": 0, "error": 0}
    for user_id in _affected_user_ids(detail):
        try:
            outcome = _notify_user(user_id, detail_type, template_id, now)
            results[outcome] = results.get(outcome, 0) + 1
        except Exception:  # noqa: BLE001 - log and continue
            results["error"] += 1
            logger.exception(json.dumps({"event": "notify_failed"}))

    _log(logging.INFO, "batch_done", detail_type=detail_type, **results)
    return results
