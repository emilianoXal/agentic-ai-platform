"""Exercise follow-up fixtures and persisted-state verdicts without model calls."""

import importlib.util
import io
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
    ids = matrix.seed_follow_up(ddb, case, 1, user, "unit-run", [])
    pending = tool.lambda_handler({"action": "pending", "user_id": user}, None)["pending"]
    assert [item["incident_id"] for item in pending] == [ids["incident_id"]]
    before = matrix.data_snapshot(ddb, user, **ids)
    if decision:
        result = tool.lambda_handler({"action": "respond", "user_id": user, **pending[0], "decision": decision}, None)
        assert result["ok"] is True
    after = matrix.data_snapshot(ddb, user, **ids)
    run = {"user_id": user, "ddb_before": before, "ddb_after": after,
           "turns": [{"response": {"ok": True, "reply": "Gracias por responder."}, "tool_evidence": []}]}
    assert matrix.verdicts(case, run, None)["veracidad"]["pass"] is True
    assert matrix.follow_up_state_matches(case, run)
    assert matrix.verdicts(case, run, "CloudWatch unavailable")["accion_correcta"]["pass"] is True
    wrong = dict(after["linked_incident"], status="OPEN")
    run["ddb_after"] = dict(after, linked_incident=wrong)
    assert matrix.verdicts(case, run, None)["accion_correcta"]["pass"] is False


def test_confirmation_claim_without_audit_is_not_evidence(database):
    ddb, _ = database
    case = next(case for case in matrix.CASES if case.get("expected_decision") == "confirm")
    user = matrix.fake_number(case["id"], 1)
    ids = matrix.seed_follow_up(ddb, case, 1, user, "missing-audit", [])
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


def run_with_reply(user, snapshot, reply):
    return {"user_id": user, "ddb_before": snapshot, "ddb_after": snapshot,
            "turns": [{"response": {"ok": True, "reply": reply}, "tool_evidence": []}]}


@pytest.mark.parametrize("decision,reply", [
    (None, "Listo, marqué tu reporte como resuelto."),
    (None, "Entendido, lo reabrí para que la dependencia regrese."),
    ("confirm", "Gracias, lo reabrí para revisarlo."),
    ("reopen", "Perfecto, quedó resuelto tu reporte."),
])
def test_false_decision_claim_fails_veracity_even_when_state_is_right(database, decision, reply):
    ddb, tool = database
    case = next(case for case in matrix.CASES if case.get("follow_up") and case["expected_decision"] == decision)
    user = matrix.fake_number(case["id"], 1)
    ids = matrix.seed_follow_up(ddb, case, 1, user, "false-claim", [])
    if decision:
        pending = tool.lambda_handler({"action": "pending", "user_id": user}, None)["pending"]
        tool.lambda_handler({"action": "respond", "user_id": user, **pending[0], "decision": decision}, None)
    after = matrix.data_snapshot(ddb, user, **ids)
    verdict = matrix.verdicts(case, run_with_reply(user, after, reply), None)
    assert verdict["accion_correcta"]["pass"] is (decision is None)
    assert verdict["veracidad"]["pass"] is False


def test_question_about_decision_is_not_a_claim(database):
    ddb, _ = database
    case = next(case for case in matrix.CASES if case.get("scenario") == "ambiguous")
    user = matrix.fake_number(case["id"], 1)
    ids = matrix.seed_follow_up(ddb, case, 1, user, "question", [])
    after = matrix.data_snapshot(ddb, user, **ids)
    reply = "Entiendo. ¿Ya quedó resuelto o quieres que lo reabra? Dime sí o no."
    assert matrix.verdicts(case, run_with_reply(user, after, reply), None)["veracidad"]["pass"] is True


def seed_unrelated(ddb):
    ddb.put_item(TableName=matrix.INCIDENTS_TABLE, Item={
        "incident_id": {"S": "other-synthetic"}, "synthetic": {"BOOL": True}, "status": {"S": "resolved"}})
    ddb.put_item(TableName=matrix.REPORTS_TABLE, Item={
        "report_id": {"S": "other-real"}, "user_id": {"S": "52155"}, "created_at": {"S": "t"}})
    ddb.put_item(TableName=matrix.AUDIT_TABLE, Item={
        "entity_id": {"S": "incident#other-synthetic"}, "ts": {"S": "t"}, "kind": {"S": "kept"}})


def table_keys(ddb):
    return {table: sorted(str(item) for item in ddb.scan(TableName=table)["Items"])
            for table in (matrix.INCIDENTS_TABLE, matrix.REPORTS_TABLE, matrix.AUDIT_TABLE)}


def fake_agent(tool, decision):
    def invoke(**kwargs):
        event = matrix.json.loads(kwargs["Payload"])
        if decision:
            pending = tool.lambda_handler({"action": "pending", "user_id": event["user_id"]}, None)["pending"]
            tool.lambda_handler({"action": "respond", "user_id": event["user_id"], **pending[0],
                                 "decision": decision}, None)
        body = matrix.json.dumps({"ok": True, "reply": "Gracias por avisar."}).encode()
        return {"Payload": io.BytesIO(body)}
    return invoke


def run_main(monkeypatch, tmp_path, ddb, lambda_client):
    logs = Mock()
    logs.get_paginator.return_value.paginate.return_value = []
    clients = {"dynamodb": ddb, "lambda": lambda_client, "logs": logs}
    session = Mock()
    session.client.side_effect = lambda name, **_: clients[name]
    monkeypatch.setattr(matrix.boto3, "Session", lambda **_: session)
    monkeypatch.setattr(matrix.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["conversation_matrix.py", "--suite", "follow-up",
                                      "--output-dir", str(tmp_path)])
    status = matrix.main()
    return status, matrix.json.loads((tmp_path / "conversation_matrix.json").read_text())


def test_successful_run_deletes_only_its_fixtures_and_their_audit(database, monkeypatch, tmp_path):
    ddb, tool = database
    seed_unrelated(ddb)
    untouched = table_keys(ddb)
    lambda_client = Mock()
    lambda_client.invoke.side_effect = fake_agent(tool, "reopen")
    status, result = run_main(monkeypatch, tmp_path, ddb, lambda_client)
    assert status == 0 and len(result["runs"]) == 96
    cleanup = result["follow_up_cleanup"]
    assert len(cleanup["fixtures"]) == 96 and cleanup["errors"] == []
    assert sum(entry.startswith(matrix.AUDIT_TABLE) for entry in cleanup["deleted"]) == 96
    assert table_keys(ddb) == untouched


def test_partially_seeded_run_still_deletes_what_it_created(database, monkeypatch, tmp_path):
    ddb, tool = database
    seed_unrelated(ddb)
    untouched = table_keys(ddb)
    real_put = ddb.put_item
    calls = {"reports": 0}

    def flaky_put(**kwargs):
        if kwargs["TableName"] == matrix.REPORTS_TABLE:
            calls["reports"] += 1
            if calls["reports"] == 3:
                raise matrix.ClientError({"Error": {"Code": "ProvisionedThroughputExceededException",
                                                    "Message": "boom"}}, "PutItem")
        return real_put(**kwargs)

    monkeypatch.setattr(ddb, "put_item", flaky_put)
    lambda_client = Mock()
    lambda_client.invoke.side_effect = fake_agent(tool, "confirm")
    status, result = run_main(monkeypatch, tmp_path, ddb, lambda_client)
    assert status == 2 and "boom" in result["fatal_error"]
    assert len(result["follow_up_cleanup"]["fixtures"]) == 3
    assert result["follow_up_cleanup"]["errors"] == []
    assert table_keys(ddb) == untouched
