"""urbanbot dashboard API Lambda (AppSync direct Lambda resolver).

Serves the officials' dashboard: paginated incident list, incident detail with
its audit timeline, status changes, comments and escalation. Status changes
write the incident + its reports, append an audit-log entry (RF-15) and emit
EXACTLY ONE EventBridge "StatusChanged" event addressed to every joined
neighbor, the same contract the compute notifier already consumes (RF-19).

Legacy statuses written by the tool Lambdas (OPEN / ESCALATED / Spanish labels)
are normalized on read to the six standard codes plus an escalated flag.
OPEN and ESCALATED become sent_to_agency only when both dependency_mail_sent_at
and routed_to are present. Either one alone keeps them received. A stored
sent_to_agency missing either one reads as pending_send, a display-only code
that is never written back. An incident routed to a dependency without an agency
mailbox is a supervisor escalation: escalated, never sent or pending send.

Authorization (server side, from Cognito claims):
  - group "agency": only incidents routed to its custom:agency_id.
  - group "official" / "admin": every incident; may escalate, reopen and mark
    not applicable without an agency scope.
Full phone numbers never leave this Lambda: neighbors are returned masked.
"""

import base64
import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

import demo_data

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE_NAME"]
REPORTS_TABLE = os.environ["REPORTS_TABLE_NAME"]
AUDIT_TABLE = os.environ["AUDIT_TABLE_NAME"]
EVENT_BUS_NAME = os.environ["EVENT_BUS_NAME"]
ROUTING_RULES_JSON = os.environ.get("ROUTING_RULES_JSON", "{}")
MAIL_CATEGORIES = frozenset(
    c.strip().lower() for c in os.environ.get("DEPENDENCY_MAIL_CATEGORIES", "").split(",") if c.strip()
)
FOLLOW_UP_DELAY_MINUTES = int(os.environ.get("FOLLOW_UP_DELAY_MINUTES", "1440"))
FOLLOW_UP_FUNCTION_ARN = os.environ.get("FOLLOW_UP_FUNCTION_ARN", "")
FOLLOW_UP_ROLE_ARN = os.environ.get("FOLLOW_UP_ROLE_ARN", "")
SCHEDULE_NAME_PREFIX = os.environ.get("SCHEDULE_NAME_PREFIX", "cdshack-urbanbot-dev-fu-")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
TIMELINE_LIMIT = 50

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

USERS_TABLE = os.environ["USERS_TABLE_NAME"]

_ddb = boto3.client("dynamodb")
_events = boto3.client("events")
_scheduler = boto3.client("scheduler")
_places = None

STATUS_CODES = ("received", "sent_to_agency", "in_progress", "resolved", "not_applicable", "reopened")

# Spanish labels the bot and the report rows use for each code.
STATUS_LABEL_ES = {
    "received": "Recibido",
    "sent_to_agency": "Enviado a dependencia",
    "in_progress": "En atencion",
    "resolved": "Resuelto",
    "not_applicable": "No procede",
    "reopened": "Reabierto",
}

_LEGACY_STATUS = {
    "recibido": "received",
    "enviado a dependencia": "sent_to_agency",
    "en atencion": "in_progress",
    "resuelto": "resolved",
    "no procede": "not_applicable",
    "reabierto": "reopened",
}

CATEGORY_LABEL = {
    "agua": "Water leak",
    "bacheo": "Pothole",
    "alumbrado": "Street lighting",
    "basura": "Trash",
    "drenaje": "Drainage",
    "arbol": "Fallen tree",
    "plagas": "Pests",
    "seguridad": "Safety",
    "otro": "Other",
}

# Mirrors the route tool's default routing map (category -> dependency).
_DEFAULT_DEPENDENCIES = {
    "alumbrado": "Servicios Publicos",
    "bacheo": "Obras Publicas",
    "basura": "Limpia Publica",
    "agua": "Organismo de Agua",
    "seguridad": "Seguridad Ciudadana",
    "drenaje": "Organismo de Agua",
    "arbol": "Servicios Publicos",
    "plagas": "Servicios Publicos",
}

SUPERVISOR_GROUPS = {"official", "admin"}

_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


class DashboardError(Exception):
    """Raised for request errors that must reach the caller with a clear message."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# =============================================================================
# Logging with PII masking (never the full phone number or free text).
# =============================================================================
def _log(level, event, **fields):
    logger.log(level, json.dumps({"event": event, **fields}, default=str))


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat()


def _mask_neighbor(user_id):
    """Masked suffix shown to staff: last two digits only (RNF-10)."""
    digits = re.sub(r"\D", "", str(user_id or ""))
    return "••" + (digits[-2:] if len(digits) >= 2 else "••")


def slugify(value):
    """Agency id derived from the dependency name: 'Organismo de Agua' -> 'organismo-de-agua'."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _dependency_map():
    names = dict(_DEFAULT_DEPENDENCIES)
    try:
        rules = json.loads(ROUTING_RULES_JSON or "{}")
        for category, rule in rules.items():
            if isinstance(rule, dict) and rule.get("dependency"):
                names[category] = rule["dependency"]
    except (ValueError, TypeError):
        _log(logging.WARNING, "routing_rules_parse_failed")
    return names


def _mailbox_dependencies():
    return {name for category, name in _dependency_map().items() if category in MAIL_CATEGORIES}


def _agencies():
    unique = {slugify(name): name for name in _dependency_map().values()}
    mailboxes = _mailbox_dependencies()
    return [{"id": slug, "name": name, "mailbox": name in mailboxes} for slug, name in sorted(unique.items())]


# =============================================================================
# Geohash decode (center of the cell) for incidents without explicit lat/lng.
# =============================================================================
def decode_geohash(geohash):
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for char in str(geohash or "").lower():
        idx = _GEOHASH_BASE32.find(char)
        if idx < 0:
            break
        for bit in (16, 8, 4, 2, 1):
            target = lng_range if even else lat_range
            mid = (target[0] + target[1]) / 2
            if idx & bit:
                target[0] = mid
            else:
                target[1] = mid
            even = not even
    return (lat_range[0] + lat_range[1]) / 2, (lng_range[0] + lng_range[1]) / 2


# =============================================================================
# Read model.
# =============================================================================
def _s(item, key, default=None):
    return item.get(key, {}).get("S", default)


def _n(item, key, default=0):
    try:
        return int(float(item.get(key, {}).get("N", default)))
    except (TypeError, ValueError):
        return default


def normalize_status(raw, routed, mail_sent=False):
    """Map any stored status to one of the six codes plus an escalated flag."""
    value = str(raw or "").strip()
    if value in STATUS_CODES:
        return value, False
    upper = value.upper()
    if upper in ("OPEN", "ESCALATED"):
        return ("sent_to_agency" if mail_sent and routed else "received"), upper == "ESCALATED"
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return _LEGACY_STATUS.get(plain, "received"), False


def _exposes_geohash(text, geohash):
    """True when a word of the text is the incident's geohash cell or a 4+ char prefix of it."""
    cell = str(geohash or "").strip().lower()
    if not cell:
        return False
    for word in str(text or "").lower().split():
        token = word.strip(".,;:()")
        if len(token) >= 4 and (cell.startswith(token) or token.startswith(cell)):
            return True
    return False


def public_title(item):
    """Title shown in the portal: a stored place title, else the category with a street or neighborhood, else the category. Never a geohash."""
    geohash = _s(item, "geohash", "") or ""
    label = CATEGORY_LABEL.get(_s(item, "category", "otro"), "Incident")
    stored = (_s(item, "title") or "").strip()
    if stored and not _exposes_geohash(stored, geohash):
        return stored
    address = _s(item, "address")
    if address and not _exposes_geohash(address, geohash):
        return "{} at {}".format(label, address)
    neighborhood = _s(item, "neighborhood")
    if neighborhood and not _exposes_geohash(neighborhood, geohash):
        return "{} near {}".format(label, neighborhood)
    return label


def to_incident(item, neighbors=None, timeline=None):
    incident_id = _s(item, "incident_id")
    routed_to = _s(item, "routed_to")
    mail_sent = bool(_s(item, "dependency_mail_sent_at"))
    status, legacy_escalated = normalize_status(
        _s(item, "status"), bool(routed_to), mail_sent
    )
    if status == "sent_to_agency" and not (mail_sent and routed_to):
        status = "pending_send"
    escalated = item.get("escalated", {}).get("BOOL", False) or legacy_escalated
    if routed_to and routed_to not in _mailbox_dependencies():
        escalated = True
        if status in ("sent_to_agency", "pending_send"):
            status = "received"
    category = _s(item, "category", "otro")
    geohash = _s(item, "geohash", "")
    if "lat" in item and "lng" in item:
        lat, lng = float(item["lat"]["N"]), float(item["lng"]["N"])
    else:
        lat, lng = decode_geohash(geohash)
    created_at = _s(item, "created_at", _now_iso())
    neighborhood = _s(item, "neighborhood")
    title = public_title(item)
    return {
        "id": incident_id,
        "folio": _s(item, "folio") or "UB-{}-{}".format(created_at[:4], incident_id[:6].upper()),
        "category": category,
        "title": title,
        "neighborhood": neighborhood,
        "geohash": geohash,
        "location": {"lat": lat, "lng": lng},
        "status": status,
        "escalated": bool(escalated),
        "severity": (_s(item, "max_severity") or _s(item, "severity") or "medium").lower(),
        "reportCount": _n(item, "report_count", 1),
        "agencyId": slugify(routed_to) if routed_to else None,
        "agencyName": routed_to,
        "agencyCaseId": _s(item, "agency_case_id"),
        "photoCount": _n(item, "photo_count", 0),
        "neighbors": neighbors or [],
        "createdAt": created_at,
        "updatedAt": _s(item, "updated_at", created_at),
        "followUpPending": status == "resolved" and bool(_s(item, "follow_up_due_at")) and (
            _s(item, "follow_up_ran") != _s(item, "follow_up_due_at") or any(
                value.get("S") == "pending"
                for value in item.get("follow_up_deliveries", {}).get("M", {}).values()
            )
        ),
        "timeline": timeline or [],
    }


def _timeline_entry(item, mail_sent=False):
    kind = _s(item, "kind", "")
    at = _s(item, "ts", _now_iso())
    entry_id = "{}#{}".format(_s(item, "entity_id", ""), at)
    mapping = {
        "create_report": ("status", "First report received from WhatsApp", "whatsapp", "received"),
        "join_incident": ("joined", "A neighbor joined from WhatsApp", "whatsapp", None),
        "route": ("routed", "Assigned to {} by routing rule; agency email {}".format(_s(item, "dependency") or _s(item, "authority") or "the agency", "sent" if mail_sent else "pending"), "routing", None),
        "dependency_mail_sent": ("status", "Agency email sent" + (" to " + _s(item, "dependency") if _s(item, "dependency") else ""), "email", "sent_to_agency"),
        "supervisor_mail_sent": ("escalated", "Escalated to the supervisor: no agency mailbox", "email", None),
        "escalate": ("escalated", "Escalated: over the report or age threshold", "bot", None),
        "citizen_confirmed": ("follow_up", "A neighbor confirmed it is fixed from WhatsApp", "whatsapp", None),
        "citizen_reopened": ("status", "A neighbor reopened it from WhatsApp", "whatsapp", "reopened"),
    }
    if kind in mapping:
        tl_kind, text, source, status = mapping[kind]
        return {"id": entry_id, "at": at, "kind": tl_kind, "text": text, "source": source, "status": status, "actor": None}
    if kind.startswith("dashboard_"):
        return {
            "id": entry_id,
            "at": at,
            "kind": _s(item, "timeline_kind", "comment"),
            "text": _s(item, "text", ""),
            "source": _s(item, "source", "dashboard"),
            "status": _s(item, "to_status"),
            "actor": _s(item, "actor"),
        }
    return {"id": entry_id, "at": at, "kind": "comment", "text": kind.replace("_", " ").capitalize(), "source": "bot", "status": None, "actor": None}


def _load_timeline(incident_id, mail_sent=False):
    resp = _ddb.query(
        TableName=AUDIT_TABLE,
        KeyConditionExpression="entity_id = :e",
        ExpressionAttributeValues={":e": {"S": "incident#" + incident_id}},
        ScanIndexForward=False,
        Limit=TIMELINE_LIMIT,
    )
    return [_timeline_entry(item, mail_sent) for item in resp.get("Items", [])]


def _report_ids(item):
    return [v.get("S") for v in item.get("report_ids", {}).get("L", []) if v.get("S")]


def _load_reports(report_ids):
    reports = []
    for start in range(0, len(report_ids), 100):
        keys = [{"report_id": {"S": rid}} for rid in report_ids[start:start + 100]]
        resp = _ddb.batch_get_item(RequestItems={REPORTS_TABLE: {"Keys": keys}})
        reports.extend(resp.get("Responses", {}).get(REPORTS_TABLE, []))
    return reports


def _recipients(item):
    """Full user ids of every neighbor joined to the incident (used only for the event)."""
    seen, ordered = set(), []
    for report in _load_reports(_report_ids(item)):
        user_id = _s(report, "user_id")
        if user_id and user_id not in seen:
            seen.add(user_id)
            ordered.append(user_id)
    return ordered


def _get_item(incident_id):
    resp = _ddb.get_item(TableName=INCIDENTS_TABLE, Key={"incident_id": {"S": incident_id}})
    item = resp.get("Item")
    if not item:
        raise DashboardError("not_found", "The incident does not exist.")
    return item


def _detail(item):
    recipients = _recipients(item)
    return to_incident(item, [_mask_neighbor(u) for u in recipients], _load_timeline(_s(item, "incident_id"), bool(_s(item, "dependency_mail_sent_at"))))


# =============================================================================
# Authorization.
# =============================================================================
def _caller(event):
    claims = (event.get("identity") or {}).get("claims") or {}
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    return {
        "name": claims.get("name") or claims.get("email") or claims.get("cognito:username") or claims.get("username") or "Staff",
        "groups": set(groups),
        "agency_id": claims.get("custom:agency_id"),
    }


def _is_supervisor(caller):
    return bool(caller["groups"] & SUPERVISOR_GROUPS)


def _require_access(caller, item):
    if _is_supervisor(caller):
        return
    if "agency" not in caller["groups"] or not caller["agency_id"]:
        raise DashboardError("forbidden", "Your account has no dashboard role. Ask an administrator to add you to a group.")
    if slugify(_s(item, "routed_to")) != caller["agency_id"]:
        raise DashboardError("forbidden", "This incident belongs to another agency.")


def allowed_transitions(status, supervisor):
    """Same rules the dashboard UI shows; enforced here as the source of truth."""
    table = {
        "received": ["sent_to_agency", "not_applicable"] if supervisor else ["in_progress", "not_applicable"],
        "pending_send": ["sent_to_agency", "not_applicable"] if supervisor else ["in_progress", "not_applicable"],
        "sent_to_agency": ["in_progress", "not_applicable"],
        "in_progress": ["resolved"],
        "reopened": ["in_progress"],
        "resolved": ["reopened"] if supervisor else [],
        "not_applicable": ["reopened"] if supervisor else [],
    }
    return table.get(status, [])


# =============================================================================
# Writes.
# =============================================================================
def _audit(incident_id, timeline_kind, text, actor, to_status=None, **extra):
    item = {
        "entity_id": {"S": "incident#" + incident_id},
        "ts": {"S": _now_iso()},
        "kind": {"S": "dashboard_" + timeline_kind},
        "timeline_kind": {"S": timeline_kind},
        "text": {"S": text},
        "source": {"S": "dashboard"},
        "actor": {"S": actor},
    }
    if to_status:
        item["to_status"] = {"S": to_status}
    for key, val in extra.items():
        if val is not None:
            item[key] = {"S": str(val)}
    _ddb.put_item(TableName=AUDIT_TABLE, Item=item)


def _emit(detail_type, detail):
    _events.put_events(
        Entries=[{
            "Source": "urbanbot.dashboard",
            "DetailType": detail_type,
            "EventBusName": EVENT_BUS_NAME,
            "Detail": json.dumps(detail),
        }]
    )


def update_status(event, caller):
    args = event.get("arguments") or {}
    incident_id, target = args.get("id"), args.get("status")
    comment, reason = (args.get("comment") or "").strip(), (args.get("reason") or "").strip()
    if target not in STATUS_CODES:
        raise DashboardError("invalid_input", "Unknown status.")
    if target == "not_applicable" and not reason:
        raise DashboardError("invalid_input", "A reason is required to mark an incident not applicable.")
    dependency = (args.get("dependency") or "").strip()
    dependency_categories = []
    if target == "sent_to_agency":
        dependency_categories = sorted(
            c for c, name in _dependency_map().items() if name == dependency and c in MAIL_CATEGORIES
        )
        if not dependency_categories:
            raise DashboardError("invalid_input", "Choose the agency to send this incident to.")

    item = _get_item(incident_id)
    _require_access(caller, item)
    current = to_incident(item)["status"]
    if target not in allowed_transitions(current, _is_supervisor(caller)):
        raise DashboardError("invalid_transition", "That status change is not allowed from {}.".format(current))

    now = _now()
    names = {"#s": "status"}
    values = {":s": {"S": target}, ":u": {"S": now.isoformat()}, ":by": {"S": caller["name"]},
              ":previous": item["status"]}
    expression = "SET #s = :s, updated_at = :u, last_status_by = :by"
    routed_to = _s(item, "routed_to")
    if target == "sent_to_agency":
        routed_to = dependency
        expression += ", routed_to = :rt"
        values[":rt"] = {"S": routed_to}
    if target == "resolved":
        due = now + timedelta(minutes=FOLLOW_UP_DELAY_MINUTES)
        due_at = due.isoformat()
        schedule_name = SCHEDULE_NAME_PREFIX + hashlib.sha256(
            (incident_id + due_at).encode()
        ).hexdigest()[:32]
        _scheduler.create_schedule(
            Name=schedule_name, GroupName="default",
            ScheduleExpression="at({})".format(due.strftime("%Y-%m-%dT%H:%M:%S")),
            ScheduleExpressionTimezone="UTC", FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={"Arn": FOLLOW_UP_FUNCTION_ARN, "RoleArn": FOLLOW_UP_ROLE_ARN,
                    "Input": json.dumps({"action": "send", "incident_id": incident_id,
                                         "due_at": due_at}),
                    "RetryPolicy": {"MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 2}},
        )
        expression += ", follow_up_due_at = :f, follow_up_deliveries = :empty"
        values[":f"] = {"S": due_at}
        values[":empty"] = {"M": {}}
    else:
        expression += " REMOVE follow_up_due_at"
    if target == "not_applicable":
        expression = expression.replace(" REMOVE", ", status_reason = :r REMOVE")
        values[":r"] = {"S": reason}
    _ddb.update_item(
        TableName=INCIDENTS_TABLE,
        Key={"incident_id": {"S": incident_id}},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="#s = :previous",
    )

    # Keep each report row in step so the bot's get_status reads the same status.
    # A send waits for the dependency mailer before anyone is told it was sent.
    for report_id in ([] if target == "sent_to_agency" else _report_ids(item)):
        try:
            _ddb.update_item(
                TableName=REPORTS_TABLE,
                Key={"report_id": {"S": report_id}},
                UpdateExpression="SET #s = :s, updated_at = :u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": {"S": STATUS_LABEL_ES[target]}, ":u": {"S": now.isoformat()}},
                ConditionExpression="attribute_exists(report_id)",
            )
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    reason_text = ". Reason: {}".format(reason) if reason else ""
    if target == "sent_to_agency":
        _audit(incident_id, "status", "Send to {} requested by {}; agency email pending".format(dependency, caller["name"]), caller["name"], to_status="pending_send", from_status=current)
    else:
        _audit(incident_id, "status", "Marked {} by {}{}".format(target.replace("_", " "), caller["name"], reason_text), caller["name"], to_status=target, from_status=current)
    if comment:
        _audit(incident_id, "comment", comment, caller["name"])
    if target == "resolved":
        _audit(incident_id, "follow_up", '"Is it fixed?" scheduled for neighbors in {} min'.format(FOLLOW_UP_DELAY_MINUTES), "UrbanBot")

    recipients = [] if target == "sent_to_agency" else _recipients(item)
    _emit("StatusChanged", {
        "incident_id": incident_id,
        "category": _s(item, "category"),
        "status": target,
        "status_label": STATUS_LABEL_ES[target],
        "previous_status": current,
        "authority": routed_to,
        "reason": reason or None,
        "user_ids": recipients,
        "dependency_categories": dependency_categories or None,
        "source": "dashboard",
    })
    _audit(incident_id, "notified", "StatusChanged sent to the notifier for {} neighbors".format(len(recipients)), "UrbanBot")
    _log(logging.INFO, "status_changed", incident_id=incident_id, to=target, recipients=len(recipients))
    return {"incident": _detail(_get_item(incident_id)), "notified": len(recipients)}


def add_comment(event, caller):
    args = event.get("arguments") or {}
    incident_id, text = args.get("id"), (args.get("text") or "").strip()
    if not text:
        raise DashboardError("invalid_input", "The comment is empty.")
    if len(text) > 1000:
        raise DashboardError("invalid_input", "Comments are limited to 1000 characters.")
    item = _get_item(incident_id)
    _require_access(caller, item)
    _audit(incident_id, "comment", text, caller["name"])
    return _detail(item)


def escalate(event, caller):
    incident_id = (event.get("arguments") or {}).get("id")
    if not _is_supervisor(caller):
        raise DashboardError("forbidden", "Only municipal supervisors can escalate.")
    item = _get_item(incident_id)
    now = _now_iso()
    _ddb.update_item(
        TableName=INCIDENTS_TABLE,
        Key={"incident_id": {"S": incident_id}},
        UpdateExpression="SET escalated = :t, escalated_at = :u, updated_at = :u",
        ExpressionAttributeValues={":t": {"BOOL": True}, ":u": {"S": now}},
    )
    _audit(incident_id, "escalated", "Escalated to the next level of government by {}".format(caller["name"]), caller["name"])
    _emit("IncidentEscalated", {"incident_id": incident_id, "category": _s(item, "category"), "authority": _s(item, "routed_to"), "source": "dashboard"})
    return _detail(_get_item(incident_id))


# =============================================================================
# Reads.
# =============================================================================
def _encode_token(key):
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode() if key else None


def _decode_token(token):
    try:
        return json.loads(base64.urlsafe_b64decode(token.encode()).decode())
    except (ValueError, TypeError):
        raise DashboardError("invalid_input", "The pagination token is not valid.")


def list_incidents(event, caller):
    args = event.get("arguments") or {}
    limit = args.get("limit") or DEFAULT_PAGE_SIZE
    if not 1 <= int(limit) <= MAX_PAGE_SIZE:
        raise DashboardError("invalid_input", "limit must be between 1 and {}.".format(MAX_PAGE_SIZE))
    params = {"TableName": INCIDENTS_TABLE, "Limit": int(limit)}
    if args.get("nextToken"):
        params["ExclusiveStartKey"] = _decode_token(args["nextToken"])
    # Scan is acceptable here: one municipality's open incidents (tens to low
    # hundreds). A status/updated_at GSI replaces it before multi-tenant use.
    resp = _ddb.scan(**params)
    items = resp.get("Items", [])
    if not _is_supervisor(caller):
        agency = caller["agency_id"]
        items = [i for i in items if agency and slugify(_s(i, "routed_to")) == agency]
    token = _encode_token(resp.get("LastEvaluatedKey"))
    incidents = [to_incident(i) for i in items]
    return {"items": incidents, "nextToken": token, "hasMore": token is not None, "count": len(incidents)}


def get_incident(event, caller):
    item = _get_item((event.get("arguments") or {}).get("id"))
    _require_access(caller, item)
    return _detail(item)


# =============================================================================
# Demo data (admin only).
# =============================================================================
def _place_for(lat, lng):
    """Reverse-geocode a point with Amazon Location Places; Nones if unavailable."""
    global _places
    try:
        if _places is None:
            _places = boto3.client("geo-places")
        resp = _places.reverse_geocode(QueryPosition=[lng, lat], Language="es", MaxResults=1)
        items = resp.get("ResultItems") or []
        if not items:
            return {"address": None, "neighborhood": None}
        address = items[0].get("Address") or {}
        street = address.get("Street")
        number = address.get("AddressNumber")
        return {
            "address": " ".join(p for p in (street, number) if p) or address.get("Label"),
            "neighborhood": address.get("District") or address.get("SubDistrict") or address.get("Locality"),
        }
    except (ClientError, BotoCoreError, ValueError):
        _log(logging.WARNING, "reverse_geocode_failed")
        return {"address": None, "neighborhood": None}


def _require_admin(caller):
    if "admin" not in caller["groups"]:
        raise DashboardError("forbidden", "Only administrators can load or reset demo data.")


def _batch_write(table, requests):
    for start in range(0, len(requests), 25):
        pending = {table: requests[start:start + 25]}
        for _ in range(5):
            resp = _ddb.batch_write_item(RequestItems=pending)
            pending = resp.get("UnprocessedItems") or {}
            if not pending:
                break


def seed_demo(event, caller):
    _require_admin(caller)
    args = event.get("arguments") or {}
    lat, lng = float(args.get("lat")), float(args.get("lng"))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise DashboardError("invalid_input", "The demo point is outside valid coordinates.")
    reset_demo(event, caller)
    incidents, reports, audit, users = demo_data.build(lat, lng, _place_for)
    _batch_write(USERS_TABLE, [{"PutRequest": {"Item": i}} for i in users])
    _batch_write(REPORTS_TABLE, [{"PutRequest": {"Item": i}} for i in reports])
    _batch_write(AUDIT_TABLE, [{"PutRequest": {"Item": i}} for i in audit])
    _batch_write(INCIDENTS_TABLE, [{"PutRequest": {"Item": i}} for i in incidents])
    _log(logging.INFO, "demo_seeded", incidents=len(incidents), reports=len(reports))
    items = [to_incident(i) for i in incidents]
    return {"items": items, "nextToken": None, "hasMore": False, "count": len(items)}


def _scan_synthetic(table, key_names):
    keys, params = [], {
        "TableName": table,
        "FilterExpression": "synthetic = :t",
        "ExpressionAttributeValues": {":t": {"BOOL": True}},
        "ProjectionExpression": ", ".join(key_names),
    }
    while True:
        resp = _ddb.scan(**params)
        keys.extend({k: item[k] for k in key_names} for item in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return keys
        params["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def reset_demo(event, caller):
    _require_admin(caller)
    incident_keys = _scan_synthetic(INCIDENTS_TABLE, ["incident_id"])
    audit_keys = []
    for key in incident_keys:
        entity = "incident#" + key["incident_id"]["S"]
        params = {
            "TableName": AUDIT_TABLE,
            "KeyConditionExpression": "entity_id = :e",
            "ExpressionAttributeValues": {":e": {"S": entity}},
            "ProjectionExpression": "entity_id, ts",
        }
        while True:
            resp = _ddb.query(**params)
            audit_keys.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            params["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    _batch_write(AUDIT_TABLE, [{"DeleteRequest": {"Key": k}} for k in audit_keys])
    _batch_write(REPORTS_TABLE, [{"DeleteRequest": {"Key": k}} for k in _scan_synthetic(REPORTS_TABLE, ["report_id"])])
    _batch_write(USERS_TABLE, [{"DeleteRequest": {"Key": k}} for k in _scan_synthetic(USERS_TABLE, ["user_id"])])
    _batch_write(INCIDENTS_TABLE, [{"DeleteRequest": {"Key": k}} for k in incident_keys])
    _log(logging.INFO, "demo_reset", incidents=len(incident_keys))
    return len(incident_keys)


HANDLERS = {
    ("Query", "listIncidents"): list_incidents,
    ("Query", "getIncident"): get_incident,
    ("Query", "listAgencies"): lambda event, caller: _agencies(),
    ("Mutation", "updateIncidentStatus"): update_status,
    ("Mutation", "addIncidentComment"): add_comment,
    ("Mutation", "escalateIncident"): escalate,
    ("Mutation", "seedDemoData"): seed_demo,
    ("Mutation", "resetDemoData"): reset_demo,
}


def lambda_handler(event, context):
    info = event.get("info") or {}
    key = (info.get("parentTypeName"), info.get("fieldName"))
    handler = HANDLERS.get(key)
    if handler is None:
        raise DashboardError("unknown_field", "Unsupported operation.")
    caller = _caller(event)
    try:
        return handler(event, caller)
    except DashboardError as err:
        _log(logging.WARNING, "request_rejected", field=key[1], code=err.code)
        raise Exception("{}: {}".format(err.code, err.message))
    except ClientError:
        logger.exception(json.dumps({"event": "dashboard_api_failed", "field": key[1]}))
        raise Exception("internal: The request could not be completed. Try again.")
