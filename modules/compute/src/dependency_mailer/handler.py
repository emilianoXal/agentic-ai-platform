"""Send incident creation and escalation notices to the responsible agency."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "antonio.miguel@xaldigital.com")
FALLBACK_EMAIL = os.environ.get(
    "DEPENDENCY_FALLBACK_EMAIL",
    "antonio.miguel+supervisor@xaldigital.com",
)
PORTAL_URL = os.environ.get("PORTAL_URL") or "https://main.d1taemvhj3go47.amplifyapp.com/incidents"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def _email_map():
    try:
        value = json.loads(os.environ.get("DEPENDENCY_EMAIL_MAP", "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


DEPENDENCY_EMAIL_MAP = _email_map()

_ddb = boto3.client("dynamodb")
_ses = boto3.client("sesv2")

logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


def _log(level, event, **fields):
    logger.log(level, json.dumps({"event": event, **fields}, default=str))


def _hash_id(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _mark_mail_sent(incident_id, item, message_id, to_agency):
    now = _now_iso()
    if to_agency:
        _ddb.update_item(
            TableName=INCIDENTS_TABLE,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression="SET dependency_mail_sent_at = :t",
            ExpressionAttributeValues={":t": {"S": now}},
        )
    audit = {
        "entity_id": {"S": "incident#" + incident_id},
        "ts": {"S": now},
        "kind": {"S": "dependency_mail_sent" if to_agency else "supervisor_mail_sent"},
    }
    dependency = _text(item, "routed_to") or _text(item, "dependency")
    if to_agency and dependency:
        audit["dependency"] = {"S": dependency}
    if message_id:
        audit["message_id"] = {"S": str(message_id)}
    _ddb.put_item(TableName=AUDIT_TABLE, Item=audit)


def _is_creation(event, detail_type, detail):
    return (
        detail_type == "StatusChanged"
        and event.get("source") == "urbanbot.agent"
        and not detail.get("status")
    )


def _is_escalation(event, detail_type, detail):
    if detail_type == "IncidentEscalated":
        return True
    return (
        detail_type == "IncidentNearby"
        and event.get("source") == "urbanbot.agent"
        and detail.get("status") == "ESCALATED"
    )


def _claim(key):
    try:
        _ddb.put_item(
            TableName=AUDIT_TABLE,
            Item={
                "entity_id": {"S": "dependency-mail#" + key},
                "ts": {"S": "dedup"},
                "kind": {"S": "dependency_mail"},
            },
            ConditionExpression="attribute_not_exists(entity_id)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _release(key):
    _ddb.delete_item(
        TableName=AUDIT_TABLE,
        Key={
            "entity_id": {"S": "dependency-mail#" + key},
            "ts": {"S": "dedup"},
        },
    )


def _incident(incident_id):
    response = _ddb.get_item(
        TableName=INCIDENTS_TABLE,
        Key={"incident_id": {"S": incident_id}},
        ConsistentRead=True,
    )
    return response.get("Item", {})


def _text(item, key):
    value = item.get(key, {})
    return value.get("S") or value.get("N") or ""


def _field(detail, item, *keys):
    for key in keys:
        value = detail.get(key)
        if value not in (None, ""):
            return str(value)
        value = _text(item, key)
        if value:
            return value
    return "No especificada"


def _recipient(category):
    agency = DEPENDENCY_EMAIL_MAP.get(category.strip().lower())
    return (agency, True) if agency else (FALLBACK_EMAIL, False)


def _message(action, incident_id, category, neighborhood, priority, report_count):
    subject = "Incidente {}: {}".format(action, incident_id)
    body = "\n".join([
        "Aviso de incidente {}.".format(action),
        "ID del incidente: {}".format(incident_id),
        "Categoría: {}".format(category),
        "Colonia: {}".format(neighborhood),
        "Prioridad: {}".format(priority),
        "Reportes agrupados: {}".format(report_count),
        "Portal de atención: {}".format(PORTAL_URL),
    ])
    return subject, body


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    detail = event.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    detail_type = event.get("detail-type")
    is_creation = _is_creation(event, detail_type, detail)
    is_escalation = _is_escalation(event, detail_type, detail)
    if not (is_creation or is_escalation):
        return {"ignored": True, "detail_type": detail_type}

    event_id = str(event.get("id") or "")
    incident_id = str(detail.get("incident_id") or "")
    if not event_id or not incident_id:
        _log(logging.WARNING, "invalid_event", detail_type=detail_type)
        return {"ignored": True, "reason": "missing_id"}

    if not _claim(event_id):
        _log(logging.INFO, "duplicate_event", event_hash=_hash_id(event_id))
        return {"duplicate": True}

    action = "creado" if is_creation else "escalado"
    change_key = action + "#" + incident_id
    try:
        claimed_change = _claim(change_key)
    except Exception:
        _release(event_id)
        raise
    if not claimed_change:
        _log(logging.INFO, "duplicate_change", incident_id=incident_id, action=action)
        return {"duplicate": True}

    try:
        item = _incident(incident_id)
        category = _field(detail, item, "category")
        neighborhood = _field(detail, item, "neighborhood", "address", "geohash")
        priority = _field(detail, item, "max_severity", "severity")
        report_count = _field(detail, item, "report_count")
        recipient, to_agency = _recipient(category)
        if not recipient or not MAIL_FROM:
            raise ValueError("dependency mail sender or recipient is not configured")
        subject, body = _message(
            action,
            incident_id,
            category,
            neighborhood,
            priority,
            report_count,
        )
        response = _ses.send_email(
            FromEmailAddress=MAIL_FROM,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
    except Exception:
        _release(change_key)
        _release(event_id)
        raise

    message_id = response.get("MessageId")
    try:
        _mark_mail_sent(incident_id, item, message_id, to_agency)
    except Exception as exc:
        _log(
            logging.ERROR,
            "dependency_mail_mark_failed",
            incident_id=incident_id,
            message_id=message_id,
            error=type(exc).__name__,
        )
    _log(
        logging.INFO,
        "dependency_mail_sent",
        event_hash=_hash_id(event_id),
        incident_id=incident_id,
        detail_type=detail_type,
        to_agency=to_agency,
    )
    return {"sent": True, "message_id": message_id}
