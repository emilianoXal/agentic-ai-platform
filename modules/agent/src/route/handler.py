"""urbanbot route tool Lambda.

Agent tool: resolve a report category to its responsible dependency + delivery
channel (RF-11/RF-12). Routing rules are DATA, not code (RNF-19): parsed from the
ROUTING_RULES_JSON env var (a JSON map category -> {dependency, channel}) at
module load, with a sane built-in default. When an incident_id is supplied and the
category is known, records routed_to/routed_at on the incident and emits EXACTLY
ONE EventBridge event (detail-type "StatusChanged", the string the compute
notifier rule matches). Unknown category -> no_route, no event. Audit entry logs
the routing decision (RF-12/RF-15).

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
ROUTING_RULES_JSON = os.environ.get("ROUTING_RULES_JSON", "{}")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
EVENTS_BUS_NAME = os.environ.get("EVENTS_BUS_NAME", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")
_events = boto3.client("events")

# --- Structured JSON-line logger (PII-masking; mirrors compute/ingest) -------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Sane default routing map (category -> dependency + delivery channel), used
# when ROUTING_RULES_JSON is empty or does not list the category.
_DEFAULT_RULES = {
    "alumbrado": {"dependency": "Servicios Publicos", "channel": "panel"},
    "bacheo": {"dependency": "Obras Publicas", "channel": "panel"},
    "basura": {"dependency": "Limpia Publica", "channel": "panel"},
    "agua": {"dependency": "Organismo de Agua", "channel": "api"},
    "seguridad": {"dependency": "Seguridad Ciudadana", "channel": "email"},
}


def _load_rules():
    try:
        parsed = json.loads(ROUTING_RULES_JSON) if ROUTING_RULES_JSON else {}
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        logger.warning(json.dumps({"event": "routing_rules_parse_failed"}))
        return {}


_RULES = _load_rules()


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


def _resolve(category):
    """Look up the routing target: env rules first, then built-in defaults."""
    rule = _RULES.get(category) or _DEFAULT_RULES.get(category)
    if not isinstance(rule, dict):
        return None
    dependency = rule.get("dependency") or rule.get("authority")
    channel = rule.get("channel", "panel")
    if not dependency:
        return None
    return {"dependency": dependency, "channel": channel}


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    category = event.get("category")
    incident_id = event.get("incident_id")
    user_ids = event.get("user_ids")

    if not category:
        _log(logging.WARNING, "invalid_input", reason="missing_category")
        return {"ok": False, "error": "invalid_input",
                "message": "A category is required."}

    target = _resolve(category)
    if not target:
        _log(logging.WARNING, "no_route", category=category)
        return {"ok": False, "error": "no_route",
                "message": "No agency is configured for this category."}

    dependency = target["dependency"]
    channel = target["channel"]

    try:
        routed = False
        if incident_id:
            now = _now_iso()
            _ddb.update_item(
                TableName=INCIDENTS_TABLE,
                Key={"incident_id": {"S": incident_id}},
                UpdateExpression="SET routed_to = :d, routed_at = :t, delivery_channel = :c",
                ExpressionAttributeValues={
                    ":d": {"S": dependency},
                    ":t": {"S": now},
                    ":c": {"S": channel},
                },
            )
            routed = True

            detail = {
                "incident_id": incident_id,
                "category": category,
                "authority": dependency,
                "channel": channel,
            }
            if user_ids:
                detail["user_ids"] = user_ids
            _events.put_events(
                Entries=[{
                    "Source": "urbanbot.agent",
                    "DetailType": "StatusChanged",
                    "Detail": json.dumps(detail, default=str),
                    "EventBusName": EVENTS_BUS_NAME,
                }]
            )

        _audit(
            "incident#" + incident_id if incident_id else "route#" + category,
            "route",
            category=category,
            dependency=dependency,
            channel=channel,
        )
        _log(logging.INFO, "routed", category=category, dependency=dependency,
             channel=channel, incident_id=incident_id, routed=routed)
        return {
            "ok": True,
            "category": category,
            "authority": dependency,
            "channel": channel,
            "routed": routed,
        }
    except ClientError:
        logger.exception(json.dumps({"event": "route_failed",
                                     "category": category}))
        return {"ok": False, "error": "internal"}
