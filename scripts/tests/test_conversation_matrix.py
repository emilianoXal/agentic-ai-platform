"""Exercise follow-up fixtures and persisted-state verdicts without model calls."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("conversation_matrix_tested", ROOT / "scripts/conversation_matrix.py")
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for table, key, sort in (
            (matrix.INCIDENTS_TABLE, "incident_id", None),
            (matrix.REPORTS_TABLE, "report_id", None),
            (matrix.PLACES_TABLE, "user_id", "place_id"),
            (matrix.AUDIT_TABLE, "entity_id", "ts"),
        ):
            attrs = [{"AttributeName": key, "AttributeType": "S"}]
            keys = [{"AttributeName": key, "KeyType": "HASH"}]
            if sort:
                attrs.append({"AttributeName": sort, "AttributeType": "S"})
                keys.append({"AttributeName": sort, "KeyType": "RANGE"})
            config = dict(TableName=table, KeySchema=keys, AttributeDefinitions=attrs,
                          BillingMode="PAY_PER_REQUEST")
            if table == matrix.REPORTS_TABLE:
                attrs += [{"AttributeName": "user_id", "AttributeType": "S"},
                          {"AttributeName": "created_at", "AttributeType": "S"}]
                config["GlobalSecondaryIndexes"] = [{
                    "IndexName": "by-user", "Projection": {"ProjectionType": "ALL"},
                    "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"},
                                  {"AttributeName": "created_at", "KeyType": "RANGE"}],
                }]
            ddb.create_table(**config)
        for key, value in {"INCIDENTS_TABLE": matrix.INCIDENTS_TABLE,
                           "REPORTS_TABLE": matrix.REPORTS_TABLE,
                           "USERS_TABLE": "unused-users", "AUDIT_TABLE": matrix.AUDIT_TABLE,
                           "OUTBOUND_FUNCTION_NAME": "never-call"}.items():
            monkeypatch.setenv(key, value)
        tool_spec = importlib.util.spec_from_file_location("matrix_real_follow_up_tool", ROOT / "modules/follow_up/src/handler.py")
        tool = importlib.util.module_from_spec(tool_spec)
        tool_spec.loader.exec_module(tool)
        tool._ddb = ddb
        tool._lambda = Mock()
        yield ddb, tool
        tool._lambda.invoke.assert_not_called()


@pytest.mark.parametrize("decision", ["confirm", "reopen", None])
def test_seeded_question_is_visible_to_real_tool_and_verdict_tracks_state(database, decision):
    ddb, tool = database
    case = next(case for case in matrix.CASES if case.get("follow_up") and case["expected_decision"] == decision)
    user = matrix.fake_number(case["id"], 1)
    ids = matrix.seed_follow_up(ddb, case, 1, user, "unit-run")
    pending = tool.lambda_handler({"action": "pending", "user_id": user}, None)["pending"]
    assert [item["incident_id"] for item in pending] == [ids["incident_id"]]
    before = matrix.data_snapshot(ddb, user, **ids)
    if decision:
        result = tool.lambda_handler({"action": "respond", "user_id": user, **pending[0], "decision": decision}, None)
        assert result["ok"] is True
    after = matrix.data_snapshot(ddb, user, **ids)
    run = {"user_id": user, "ddb_before": before, "ddb_after": after,
           "turns": [{"response": {"ok": True, "reply": "Gracias por responder."}, "tool_evidence": []}]}
    assert matrix.follow_up_state_matches(case, run)
    assert matrix.verdicts(case, run, "CloudWatch unavailable")["accion_correcta"]["pass"] is True
    wrong = dict(after["linked_incident"], status="OPEN")
    run["ddb_after"] = dict(after, linked_incident=wrong)
    assert matrix.verdicts(case, run, None)["accion_correcta"]["pass"] is False


def test_confirmation_claim_without_audit_is_not_evidence(database):
    ddb, _ = database
    case = next(case for case in matrix.CASES if case.get("expected_decision") == "confirm")
    user = matrix.fake_number(case["id"], 1)
    ids = matrix.seed_follow_up(ddb, case, 1, user, "missing-audit")
    before = matrix.data_snapshot(ddb, user, **ids)
    after = dict(before, linked_incident=dict(before["linked_incident"]))
    subject = matrix.hashlib.sha256(user.encode()).hexdigest()
    after["linked_incident"]["follow_up_deliveries"] = {subject: "confirm"}
    run = {"user_id": user, "ddb_before": before, "ddb_after": after}
    assert matrix.follow_up_state_matches(case, run) is False


def test_empty_and_partial_cells_cannot_be_green():
    case = next(case for case in matrix.CASES if case.get("follow_up"))
    empty = matrix.aggregate_cases([case], [])[0]
    assert empty["pass"] is False and empty["executed"] == 0
    partial = {"case_id": case["id"], "verdicts": {"accion_correcta": {"pass": True}}}
    summary = matrix.aggregate_cases([case], [partial])[0]
    assert summary["pass"] is False and summary["action_pass"] == 1


def test_cli_selects_follow_up_corpus_and_each_cell_has_three_trials(monkeypatch):
    monkeypatch.setenv("CONVERSATION_SUITE", "follow-up")
    monkeypatch.setattr(sys, "argv", ["conversation_matrix.py"])
    assert matrix.parse_args().suite == "follow-up"
    cases = [case for case in matrix.CASES if case.get("follow_up")]
    assert len(cases) == 32
    assert {(case["locale"], case["input_channel"]) for case in cases} == {
        (locale, channel) for locale in ("MX", "COL") for channel in ("webchat", "voice_transcript")}
    runs = [{"case_id": case["id"], "verdicts": {"accion_correcta": {"pass": trial != 3}}}
            for case in cases for trial in range(1, 4)]
    summary = matrix.aggregate_cases(cases, runs)
    assert all(cell["executed"] == 3 and cell["action_pass"] == 2 and cell["action_fail"] == 1 for cell in summary)
