"""Retraction harness against a scripted Bedrock client.

The scripted model follows the instructions it is given: when its system prompt
does not tell it the text-only history is trustworthy it retracts, and when the
prompt names a single city without accepting other places it questions the pin.
The real model runs separately through scripts/retraction_eval.py.
"""
import importlib.util
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
            folio = last["toolResult"]["content"][0]["json"]["reports"][0]["folio"]
            return _message({"text": "Your report %s is reopened. Anything else?" % folio})
        trusts_history = "text only" in system and "never retract" in system
        if self.always_retract or not trusts_history:
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
    assert system.startswith("You are a citizen assistant")


def test_tool_loop_executes_get_status_and_returns_the_final_reply():
    system, tools = ev.load_agent(str(HANDLER))
    model = ScriptedModel(check_status_first=True)
    reply, called = ev.run_agent(model, "m", system, ev.history("text"), tools)
    assert called == ["get_status"]
    assert ev.FOLIO in reply
    assert model.requests[-1]["messages"][-2]["content"][0]["toolResult"]["content"][0]["json"] == ev.STATUS_RESULT


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
