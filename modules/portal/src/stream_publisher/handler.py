"""urbanbot incidents stream publisher Lambda.

DynamoDB Streams (incidents table) -> AppSync mutation publishIncidentChange
(AWS_IAM, SigV4). Every change to an incident, whether it comes from WhatsApp
through the tool Lambdas, from the dashboard or from the demo seed, reaches the
dashboards subscribed to onIncidentChange in real time. The payload carries only
the incident id, the change kind and the timestamp; dashboards refetch the
incident through the authorized getIncident query, so no PII travels here.
"""

import json
import logging
import os
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
GRAPHQL_URL = os.environ["GRAPHQL_URL"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

_session = boto3.Session()

MUTATION = """
mutation Publish($id: ID!, $kind: String!, $updatedAt: AWSDateTime) {
  publishIncidentChange(id: $id, kind: $kind, updatedAt: $updatedAt) { id kind updatedAt }
}
"""

_KIND = {"INSERT": "created", "MODIFY": "updated", "REMOVE": "removed"}


def _log(level, event, **fields):
    logger.log(level, json.dumps({"event": event, **fields}, default=str))


def _publish(incident_id, kind, updated_at):
    body = json.dumps({
        "query": MUTATION,
        "variables": {"id": incident_id, "kind": kind, "updatedAt": updated_at},
    }).encode("utf-8")
    request = AWSRequest(method="POST", url=GRAPHQL_URL, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(_session.get_credentials(), "appsync", REGION).add_auth(request)
    http_request = urllib.request.Request(GRAPHQL_URL, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(http_request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("AppSync rejected the change notification")


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            keys = record["dynamodb"].get("Keys", {})
            incident_id = keys.get("incident_id", {}).get("S")
            if not incident_id:
                continue
            image = record["dynamodb"].get("NewImage") or {}
            updated_at = image.get("updated_at", {}).get("S")
            _publish(incident_id, _KIND.get(record.get("eventName"), "updated"), updated_at)
        except Exception:  # Report the record so the stream retries only what failed.
            logger.exception(json.dumps({"event": "publish_failed"}))
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    _log(logging.INFO, "published", records=len(event.get("Records", [])), failed=len(failures))
    return {"batchItemFailures": failures}
