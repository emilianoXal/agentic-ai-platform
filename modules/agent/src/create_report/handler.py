"""urbanbot create_report tool Lambda.

Agent tool: intake a citizen report, persist it, and cluster it into an OPEN
incident sharing the same exact geohash cell + category within a recent window
(RF-29). The agent (caller) computes and passes the geohash; this Lambda imports
NO geohash library and does an exact-cell equality Query on the incidents
by-geohash GSI, then filters in Python. Writes an audit-log entry (RF-15).

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

# --- Config from environment -------------------------------------------------
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
INCIDENTS_GEOHASH_INDEX = os.environ.get("INCIDENTS_GEOHASH_INDEX", "by-geohash")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
PENDING_MEDIA_TABLE = os.environ.get("PENDING_MEDIA_TABLE", "")
RECENT_WINDOW_HOURS = int(os.environ.get("RECENT_WINDOW_HOURS", "72"))
MAX_TEXT_LEN = int(os.environ.get("MAX_TEXT_LEN", "4096"))
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


def _portal_folio(incident_id, created_at=""):
    year = created_at[:4] if len(created_at) >= 4 and created_at[:4].isdigit() else str(
        datetime.now(timezone.utc).year)
    token = (incident_id or "??????")[:6].upper()
    return "UB-{}-{}".format(year, token)


def _sanitized_media(media):
    if not isinstance(media, list):
        return []
    return [value for value in media if isinstance(value, str) and value.startswith("sanitized/")]


def _consume_pending_media(user_id):
    """Atomically take the citizen's unexpired pending sanitized keys."""
    if not PENDING_MEDIA_TABLE:
        return []
    try:
        resp = _ddb.delete_item(
            TableName=PENDING_MEDIA_TABLE,
            Key={"user_hash": {"S": hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()}},
            ReturnValues="ALL_OLD",
        )
    except ClientError:
        _log(logging.WARNING, "pending_media_consume_failed", user_hash=_hash_id(user_id))
        return []
    now = int(time.time())
    pending = [
        (int(value["N"]), key)
        for key, value in resp.get("Attributes", {}).items()
        if key.startswith("sanitized/") and "N" in value and int(value["N"]) > now
    ]
    return [key for _, key in sorted(pending)]


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


def _find_open_incident(geohash, category):
    """Exact-cell equality Query on the by-geohash GSI + in-Python filter.

    Clustering (RF-29): group reports by the shared precomputed geohash cell.
    Precision assumption: the agent computes a precision-7 geohash (~153 m cell),
    so same-corner reports collapse to the same cell string. NO neighbour-cell
    expansion, NO proximity math, NO geohash decode/encode here. The in-Python
    filter keeps only incidents of the same category that are still OPEN and were
    active (updated_at) within RECENT_WINDOW_HOURS.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_WINDOW_HOURS)
    resp = _ddb.query(
        TableName=INCIDENTS_TABLE,
        IndexName=INCIDENTS_GEOHASH_INDEX,
        KeyConditionExpression="geohash = :g",
        ExpressionAttributeValues={":g": {"S": geohash}},
        ScanIndexForward=False,
    )
    for item in resp.get("Items", []):
        if item.get("category", {}).get("S") != category:
            continue
        if item.get("status", {}).get("S") != "OPEN":
            continue
        updated_at = item.get("updated_at", {}).get("S")
        if not updated_at:
            continue
        try:
            when = datetime.fromisoformat(updated_at)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            return item
    return None


def _attach_report(incident_id, report_id, photo_count=0):
    """Attach the report to an existing OPEN incident (ADD report_count 1)."""
    now = _now_iso()
    add_expr = "ADD report_count :one"
    values = {
        ":one": {"N": "1"},
        ":now": {"S": now},
        ":rid": {"L": [{"S": report_id}]},
        ":empty": {"L": []},
    }
    if photo_count:
        add_expr += ", photo_count :photos"
        values[":photos"] = {"N": str(int(photo_count))}
    resp = _ddb.update_item(
        TableName=INCIDENTS_TABLE,
        Key={"incident_id": {"S": incident_id}},
        UpdateExpression=(
            add_expr +
            " SET updated_at = :now, report_ids = "
            "list_append(if_not_exists(report_ids, :empty), :rid)"
        ),
        ExpressionAttributeValues=values,
        ReturnValues="UPDATED_NEW",
    )
    return int(resp.get("Attributes", {}).get("report_count", {}).get("N", "1"))


def _create_incident(geohash, category, report_id, photo_count=0):
    """Create a new OPEN incident with this report as the first member."""
    incident_id = str(uuid.uuid4())
    now = _now_iso()
    item = {
        "incident_id": {"S": incident_id},
        "geohash": {"S": geohash},
        "category": {"S": category},
        "status": {"S": "OPEN"},
        "report_count": {"N": "1"},
        "report_ids": {"L": [{"S": report_id}]},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }
    if photo_count:
        item["photo_count"] = {"N": str(int(photo_count))}
    _ddb.put_item(
        TableName=INCIDENTS_TABLE,
        Item=item,
    )
    return incident_id


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    category = event.get("category")
    geohash = event.get("geohash")
    description = event.get("description")

    if not user_id or not category or not geohash:
        _log(logging.WARNING, "invalid_input", user=_mask_phone(user_id))
        return {"ok": False, "error": "invalid_input",
                "message": "Missing required report details."}
    if not description or not str(description).strip():
        _log(logging.WARNING, "invalid_input_description", user=_mask_phone(user_id))
        return {"ok": False, "error": "invalid_input",
                "message": "A report description is required."}

    description = str(description)
    if len(description) > MAX_TEXT_LEN:
        description = description[:MAX_TEXT_LEN]

    report_id = str(uuid.uuid4())
    now = _now_iso()
    media = list(dict.fromkeys(
        _sanitized_media(event.get("media")) + _consume_pending_media(user_id)
    ))
    lat = event.get("lat")
    lng = event.get("lng")
    severity = event.get("severity")

    try:
        item = {
            "report_id": {"S": report_id},
            "user_id": {"S": str(user_id)},
            "category": {"S": category},
            "geohash": {"S": geohash},
            "description": {"S": description},
            "status": {"S": "Recibido"},
            "created_at": {"S": now},
            "updated_at": {"S": now},
        }
        if lat is not None:
            item["lat"] = {"S": str(lat)}
        if lng is not None:
            item["lng"] = {"S": str(lng)}
        if severity is not None:
            item["severity"] = {"S": str(severity)}
        if media:
            item["media"] = {"L": [{"S": str(m)} for m in media]}
        _ddb.put_item(TableName=REPORTS_TABLE, Item=item)

        existing = _find_open_incident(geohash, category)
        photo_count = len(media)
        if existing:
            incident_id = existing["incident_id"]["S"]
            created_at = existing.get("created_at", {}).get("S") or now
            report_count = _attach_report(incident_id, report_id, photo_count)
            attached = True
        else:
            incident_id = _create_incident(geohash, category, report_id, photo_count)
            created_at = now
            report_count = 1
            attached = False

        _ddb.update_item(
            TableName=REPORTS_TABLE,
            Key={"report_id": {"S": report_id}},
            UpdateExpression="SET incident_id = :i",
            ExpressionAttributeValues={":i": {"S": incident_id}},
        )

        _audit(
            "report#" + report_id,
            "create_report",
            user_hash=_hash_id(user_id),
            incident_id=incident_id,
            attached=str(attached),
        )

        _log(
            logging.INFO,
            "report_created",
            report_id=report_id,
            incident_id=incident_id,
            user=_mask_phone(user_id),
            user_hash=_hash_id(user_id),
            category=category,
            attached=attached,
            report_count=report_count,
            desc_len=len(description),
        )
        return {
            "ok": True,
            "folio": _portal_folio(incident_id, created_at),
            "report_id": report_id,
            "incident_id": incident_id,
            "attached": attached,
            "report_count": report_count,
        }
    except ClientError:
        logger.exception(json.dumps({"event": "create_report_failed",
                                     "user": _mask_phone(user_id)}))
        return {"ok": False, "error": "internal"}
