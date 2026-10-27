"""urbanbot register_place tool Lambda.

Agent tool: register (or update) a place of interest for a user (RF-23/25).
Enforces max 3 places/user (RF-23): Query the user's places first; if the count
is at/over the cap and this is a NEW place, return an error without writing.
Requires opt_in=true on the user (RF-25) else returns consent-needed. Places
table key is (user_id, place_id); place_id=uuid4 when absent. Writes an audit
entry (RF-15).

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- Config from environment -------------------------------------------------
PLACES_TABLE = os.environ.get("PLACES_TABLE", "")
USERS_TABLE = os.environ.get("USERS_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
MAX_PLACES_PER_USER = int(os.environ.get("MAX_PLACES_PER_USER", "3"))
DEFAULT_PLACE_RADIUS_M = int(os.environ.get("DEFAULT_PLACE_RADIUS_M", "500"))
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


def _audit(entity_id, kind, **extra):
    """Write a lightweight audit-log entry (entity_id + ts), RF-15."""
    item = {
        "entity_id": {"S": entity_id},
        "ts": {"S": _now_iso()},
        "kind": {"S": kind},
    }
    for key, val in extra.items():
        if val is not None:
            item[key] = {"S": str(val)}
    _ddb.put_item(TableName=AUDIT_TABLE, Item=item)


def _has_opt_in(user_id):
    """RF-25: require explicit opt_in / consent on the user record."""
    resp = _ddb.get_item(
        TableName=USERS_TABLE,
        Key={"user_id": {"S": str(user_id)}},
    )
    item = resp.get("Item")
    if not item:
        return False
    if item.get("opt_in", {}).get("BOOL") is True:
        return True
    return item.get("consent", {}).get("BOOL") is True


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    alias = event.get("alias") or event.get("label")
    geohash = event.get("geohash")
    lat = event.get("lat")
    lng = event.get("lng")
    place_id = event.get("place_id")
    radius_m = event.get("radius_m", DEFAULT_PLACE_RADIUS_M)

    if not user_id or not alias or (not geohash and (lat is None or lng is None)):
        _log(logging.WARNING, "invalid_input", user=_mask_phone(user_id))
        return {"ok": False, "error": "invalid_input",
                "message": "Faltan datos obligatorios del lugar."}

    try:
        radius_m = int(radius_m)
        if radius_m <= 0:
            radius_m = DEFAULT_PLACE_RADIUS_M
    except (TypeError, ValueError):
        radius_m = DEFAULT_PLACE_RADIUS_M

    try:
        if not _has_opt_in(user_id):
            _log(logging.WARNING, "consent_needed", user=_mask_phone(user_id))
            return {"ok": False, "error": "consent_needed",
                    "message": "Necesitamos tu consentimiento para guardar lugares."}

        resp = _ddb.query(
            TableName=PLACES_TABLE,
            KeyConditionExpression="user_id = :u",
            ExpressionAttributeValues={":u": {"S": str(user_id)}},
            Select="COUNT",
        )
        places_count = int(resp.get("Count", 0))

        is_new = not place_id
        if is_new and places_count >= MAX_PLACES_PER_USER:
            _log(logging.WARNING, "place_limit_reached",
                 user=_mask_phone(user_id), count=places_count)
            return {"ok": False, "error": "place_limit_reached",
                    "message": "Alcanzaste el maximo de lugares permitidos."}

        if is_new:
            place_id = str(uuid.uuid4())
        now = _now_iso()
        item = {
            "user_id": {"S": str(user_id)},
            "place_id": {"S": place_id},
            "alias": {"S": str(alias)},
            "radius_m": {"N": str(radius_m)},
            "updated_at": {"S": now},
        }
        if geohash:
            item["geohash"] = {"S": str(geohash)}
        if lat is not None:
            item["lat"] = {"S": str(lat)}
        if lng is not None:
            item["lng"] = {"S": str(lng)}
        if is_new:
            item["created_at"] = {"S": now}
        _ddb.put_item(TableName=PLACES_TABLE, Item=item)

        new_count = places_count + 1 if is_new else places_count
        _audit(
            "place#" + place_id,
            "register_place",
            user_hash=_hash_id(user_id),
            is_new=str(is_new),
        )
        _log(logging.INFO, "place_registered", user=_mask_phone(user_id),
             user_hash=_hash_id(user_id), place_id=place_id,
             places_count=new_count, is_new=is_new)
        return {"ok": True, "place_id": place_id, "places_count": new_count}
    except ClientError:
        logger.exception(json.dumps({"event": "register_place_failed",
                                     "user": _mask_phone(user_id)}))
        return {"ok": False, "error": "internal"}
