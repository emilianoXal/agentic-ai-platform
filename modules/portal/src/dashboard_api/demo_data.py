"""Synthetic demo data for the dashboard (RB-08: simulated and labeled as such).

Builds 30 citizen reports clustered into 4 incidents around a point, so the
demo happens wherever the presenter is. Every item carries synthetic=true;
reset deletes only those items. Phone numbers use the reserved test range
+52 999 000 00xx and never belong to real people.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone

GEOHASH_PRECISION = 7
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# (category, reports, severity, dependency, status, escalated, north_m, east_m, photos, description es)
INCIDENT_PLAN = [
    ("agua", 12, "high", "Organismo de Agua", "sent_to_agency", False, 120, -80, 3, "Hay una fuga de agua enorme en la banqueta"),
    ("bacheo", 9, "medium", "Obras Publicas", "reopened", False, -260, 310, 2, "Bache profundo, ya se poncharon dos llantas"),
    ("alumbrado", 6, "medium", "Servicios Publicos", "in_progress", True, 430, -390, 1, "Tres luminarias apagadas desde hace dias"),
    ("basura", 3, "low", "Limpia Publica", "received", False, -160, -460, 2, "Contenedores llenos y basura en la calle"),
]

# Age of each incident's first report, in minutes before now.
_AGE_MINUTES = [130, 60 * 30, 60 * 24 * 4, 12]

STATUS_LABEL_ES = {
    "received": "Recibido",
    "sent_to_agency": "Enviado a dependencia",
    "in_progress": "En atencion",
    "resolved": "Resuelto",
    "reopened": "Reabierto",
}


def encode_geohash(lat, lng, precision=GEOHASH_PRECISION):
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    chars, bits, bit, even = [], 0, 0, True
    while len(chars) < precision:
        target, value = (lng_range, lng) if even else (lat_range, lat)
        mid = (target[0] + target[1]) / 2
        if value >= mid:
            bits = (bits << 1) | 1
            target[0] = mid
        else:
            bits <<= 1
            target[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            chars.append(_BASE32[bits])
            bits, bit = 0, 0
    return "".join(chars)


def offset(lat, lng, north_m, east_m):
    """Move a point by meters (good enough at city scale)."""
    dlat = north_m / 111_320.0
    dlng = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def build(lat, lng, place_for, now=None):
    """Return (incidents, reports, audit_entries, users) as DynamoDB items.

    place_for(lat, lng) -> {"address": str|None, "neighborhood": str|None}
    resolves a human-readable place (reverse geocoding), or Nones.
    """
    now = now or datetime.now(timezone.utc)
    incidents, reports, audit, users = [], [], [], {}
    phone_seq = 0

    for idx, (category, count, severity, dependency, status, escalated, north, east, photos, description) in enumerate(INCIDENT_PLAN):
        i_lat, i_lng = offset(lat, lng, north, east)
        geohash = encode_geohash(i_lat, i_lng)
        incident_id = str(uuid.uuid4())
        created = now - timedelta(minutes=_AGE_MINUTES[idx])
        updated = now - timedelta(minutes=max(5, _AGE_MINUTES[idx] // 2))
        place = place_for(i_lat, i_lng)
        report_ids = []

        for n in range(count):
            phone_seq += 1
            user_id = "52999000{:04d}".format(phone_seq)
            users[user_id] = {
                "user_id": {"S": user_id},
                "consent": {"BOOL": True},
                "opt_in": {"BOOL": True},
                "synthetic": {"BOOL": True},
                "created_at": {"S": _iso(created)},
            }
            report_id = str(uuid.uuid4())
            report_ids.append(report_id)
            r_lat, r_lng = offset(i_lat, i_lng, (n % 3 - 1) * 12, (n % 4 - 1.5) * 10)
            reported = created + timedelta(minutes=n * 3)
            reports.append({
                "report_id": {"S": report_id},
                "user_id": {"S": user_id},
                "incident_id": {"S": incident_id},
                "category": {"S": category},
                "geohash": {"S": encode_geohash(r_lat, r_lng)},
                "description": {"S": description},
                "severity": {"S": severity},
                "status": {"S": STATUS_LABEL_ES[status]},
                "created_at": {"S": _iso(reported)},
                "updated_at": {"S": _iso(updated)},
                "synthetic": {"BOOL": True},
            })
            kind = "create_report" if n == 0 else "join_incident"
            audit.append({
                "entity_id": {"S": "incident#" + incident_id},
                "ts": {"S": _iso(reported)},
                "kind": {"S": kind},
                "synthetic": {"S": "true"},
            })

        if dependency:
            audit.append({
                "entity_id": {"S": "incident#" + incident_id},
                "ts": {"S": _iso(created + timedelta(minutes=count * 3 + 1))},
                "kind": {"S": "route"},
                "dependency": {"S": dependency},
                "synthetic": {"S": "true"},
            })
        if status in ("in_progress", "reopened"):
            audit.append(_simulated(incident_id, created + timedelta(hours=2), "status", "Marked in progress by {} (simulated)".format(dependency), "in_progress", dependency))
        if status == "reopened":
            audit.append(_simulated(incident_id, created + timedelta(hours=10), "status", "Marked resolved by {} (simulated)".format(dependency), "resolved", dependency))
            audit.append(_simulated(incident_id, updated, "reply", 'A neighbor answered "No, sigue igual": the incident is reopened', "reopened", "WhatsApp"))
        if escalated:
            audit.append({
                "entity_id": {"S": "incident#" + incident_id},
                "ts": {"S": _iso(updated)},
                "kind": {"S": "escalate"},
                "synthetic": {"S": "true"},
            })

        label = {"agua": "Water leak", "bacheo": "Pothole", "alumbrado": "Street lights out", "basura": "Overflowing bins"}[category]
        where = place.get("address") or place.get("neighborhood")
        item = {
            "incident_id": {"S": incident_id},
            "folio": {"S": "UB-{}-{:06d}".format(now.year, 214 + idx * 17)},
            "category": {"S": category},
            "title": {"S": "{} at {}".format(label, where) if where else "{} near the demo point".format(label)},
            "geohash": {"S": geohash},
            "lat": {"N": "{:.6f}".format(i_lat)},
            "lng": {"N": "{:.6f}".format(i_lng)},
            "status": {"S": status},
            "escalated": {"BOOL": escalated},
            "max_severity": {"S": severity},
            "report_count": {"N": str(count)},
            "report_ids": {"L": [{"S": rid} for rid in report_ids]},
            "photo_count": {"N": str(photos)},
            "created_at": {"S": _iso(created)},
            "updated_at": {"S": _iso(updated)},
            "synthetic": {"BOOL": True},
        }
        if dependency:
            item["routed_to"] = {"S": dependency}
            item["delivery_channel"] = {"S": "panel"}
            if status != "received":
                item["dependency_mail_sent_at"] = {"S": _iso(created + timedelta(minutes=count * 3 + 1))}
        if place.get("address"):
            item["address"] = {"S": place["address"]}
        if place.get("neighborhood"):
            item["neighborhood"] = {"S": place["neighborhood"]}
        incidents.append(item)

    return incidents, reports, audit, list(users.values())


def _simulated(incident_id, at, timeline_kind, text, status, actor):
    return {
        "entity_id": {"S": "incident#" + incident_id},
        "ts": {"S": _iso(at)},
        "kind": {"S": "dashboard_" + timeline_kind},
        "timeline_kind": {"S": timeline_kind},
        "text": {"S": text},
        "source": {"S": "simulated"},
        "actor": {"S": actor},
        "to_status": {"S": status},
        "synthetic": {"S": "true"},
    }
