"""Retraction harness against a scripted Bedrock client.

The scripted model retracts unless its system prompt says not to retract, and
questions the pin unless the prompt accepts any location. Given a location note
after a description it creates the report from both turns. When get_status
contradicts the history it limits its offers only if the prompt says so.
The real model runs separately through scripts/retraction_eval.py.
"""
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parents[3]
HANDLER = REPO / "modules" / "agent" / "src" / "agent" / "handler.py"


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "retraction_eval", REPO / "scripts" / "retraction_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_eval()


def _message(*blocks):
    return {"output": {"message": {"role": "assistant", "content": list(blocks)}}}


class ScriptedModel:
    def __init__(self, always_retract=False, check_status_first=False):
        self.always_retract = always_retract
        self.check_status_first = check_status_first
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        system = kwargs["system"][0]["text"].lower()
        if "toolConfig" not in kwargs:
            reply = kwargs["messages"][0]["content"][0]["text"].split("<reply>")[1].split("</reply>")[0].lower()
            return _message({"text": "NO" if "not registered" in reply or "querétaro" in reply else "YES"})
        messages = kwargs["messages"]
        last = messages[-1]["content"][0]
        if "toolResult" in last:
            result = last["toolResult"]["content"][0]["json"]
            if "reports" not in result:
                return _message({"text": "Your report %s is registered." % result["folio"]})
            if not result["reports"]:
                if "create the report only if" not in system:
                    return _message({"text": "Your report %s is registered." % ev.FOLIO})
                return _message({"text": "get_status shows no report under your number, so %s is not in "
                                         "the system. Do you want me to create the report now?" % ev.FOLIO})
            report = result["reports"][0]
            if report["status"] != "reopened":
                if "reopen only through a pending" not in system:
                    return _message({"text": "get_status shows %s as %s. Do you want me to reopen it or "
                                             "create a new report?" % (report["folio"], report["status"])})
                return _message({"text": "get_status shows %s as %s. What would you like to do?"
                                         % (report["folio"], report["status"])})
            return _message({"text": "Your report %s is reopened. Anything else?" % report["folio"]})
        note = re.match(r"\[The citizen shared this location .*: (\S+), (\S+)\]$", last["text"])
        if note:
            return _message({"toolUse": {"toolUseId": "tu-create", "name": "create_report", "input": {
                "category": "other", "geohash": ev.GEOHASH, "description": messages[-3]["content"][0]["text"],
                "lat": float(note.group(1)), "lng": float(note.group(2))}}})
        if self.always_retract or "do not retract" not in system:
            reply = ev.RETRACTION
            if "accept any location" not in system:
                reply += " The pin doesn't look like it's in Querétaro."
            return _message({"text": reply})
        if self.check_status_first:
            return _message({"toolUse": {"toolUseId": "tu-status", "name": "get_status",
                                         "input": {"incident_id": ev.INCIDENT_ID}}})
        return _message({"text": "Hi! Your report %s is reopened. Anything else?" % ev.FOLIO})


def test_scenario_histories_have_the_production_shapes():
    tools = ev.history("tools")
    text = ev.history("text")
    poisoned = ev.history("poisoned")
    blocks = [list(block)[0] for m in tools for block in m["content"]]
    assert blocks.count("toolUse") == 2 and blocks.count("toolResult") == 2
    assert all(list(block)[0] == "text" for m in text for block in m["content"])
    assert text == poisoned[:len(text)]
    assert poisoned[-1]["role"] == "assistant" and "not registered" in poisoned[-1]["content"][0]["text"]
    assert ev.FOLIO not in " ".join(m["content"][0].get("text", "") for m in text)


def test_agent_prompt_and_tools_come_from_the_handler():
    system, tools = ev.load_agent(str(HANDLER))
    names = {t["toolSpec"]["name"] for t in tools}
    assert {"create_report", "respond_follow_up", "get_status"} <= names
    assert system


def test_tool_loop_executes_get_status_and_returns_the_final_reply():
    system, tools = ev.load_agent(str(HANDLER))
    model = ScriptedModel(check_status_first=True)
    reply, called = ev.run_agent(model, "m", system, ev.history("text"), tools)
    assert called == ["get_status"]
    assert ev.FOLIO in reply
    assert model.requests[-1]["messages"][-2]["content"][0]["toolResult"]["content"][0]["json"] == ev.STATUS_RESULT


def test_location_after_description_creates_the_report_from_history():
    system, tools = ev.load_agent(str(HANDLER))
    model = ScriptedModel()
    reply, called = ev.run_agent(model, "m", system, ev.history("text")[:2], tools,
                                 user=ev.LOCATION_NOTE, results={"create_report": ev.CREATE_RESULT})
    assert called == ["create_report"]
    use = next(c["toolUse"] for m in model.requests[-1]["messages"] for c in m["content"] if "toolUse" in c)
    assert use["input"]["description"] == ev.REPORT_TEXT
    assert (use["input"]["lat"], use["input"]["lng"]) == (ev.LAT, ev.LNG)
    assert ev.FOLIO in reply
    assert not ev.pattern_hits(reply)


def test_status_contradicting_a_confirmation_is_reported_with_an_offer_to_create():
    system, tools = ev.load_agent(str(HANDLER))
    model = ScriptedModel(check_status_first=True)
    reply, called = ev.run_agent(model, "m", system, ev.history("text"), tools,
                                 results={"get_status": {"ok": True, "reports": []}})
    assert called == ["get_status"]
    assert "get_status shows no report" in reply
    assert "create the report" in reply
    assert "is registered" not in reply


def test_status_contradicting_a_reopening_without_a_notice_offers_no_action():
    system, tools = ev.load_agent(str(HANDLER))
    model = ScriptedModel(check_status_first=True)
    resolved = {"ok": True, "reports": [{**ev.STATUS_RESULT["reports"][0], "status": "resolved"}]}
    reply, called = ev.run_agent(model, "m", system, ev.history("text"), tools,
                                 results={"get_status": resolved})
    assert called == ["get_status"]
    assert "%s as resolved" % ev.FOLIO in reply
    assert "What would you like to do?" in reply
    assert "reopen" not in reply and "new report" not in reply


def test_verdict_rejects_retraction_and_accepts_confirmation():
    model = ScriptedModel()
    assert ev.judge(model, "m", ev.RETRACTION) == "NO"
    assert ev.pattern_hits(ev.RETRACTION)
    ok = "Your report %s is reopened." % ev.FOLIO
    assert ev.judge(model, "m", ok) == "YES"
    assert ev.pattern_hits(ok) == []


def test_harness_fails_every_run_when_the_model_retracts():
    results = ev.evaluate(ScriptedModel(always_retract=True), "m", str(HANDLER), runs=1)
    assert [r["pass"] for r in results] == [False, False, False]


@pytest.mark.parametrize("scenario", ev.SCENARIOS)
def test_agent_does_not_retract_after_hi(scenario):
    results = ev.evaluate(ScriptedModel(), "m", str(HANDLER), (scenario,), runs=3)
    assert len(results) == 3
    assert all(r["pass"] for r in results), [r["reply"] for r in results]
