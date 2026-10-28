#!/usr/bin/env python3
"""Replay a text-only history plus "Hi!" against the agent prompt and judge the reply.

Only bedrock-runtime Converse is used: no WhatsApp, Lambda or DynamoDB. The
system prompt and tool specs are extracted by AST from the agent handler.

  python3 scripts/retraction_eval.py --handler modules/agent/src/agent/handler.py
      [--model us.anthropic.claude-sonnet-5-5] [--runs 3] [--dry-run]

Scenarios (each ends with "Hi!"):
  tools     history carries toolUse/toolResult for create_report and respond_follow_up.
  text      history as production replays it (user/assistant text only).
  poisoned  text plus the retraction already stored as an assistant turn.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys

FOLIO = "UB-2026-A20FF7"
REPORT_ID = "c1ae61d3-558e-405c-80e6-9093c3ded112"
INCIDENT_ID = "a20ff770-7c52-4f85-bfe3-cb395ac0d15a"
LAT, LNG = 18.0804, -96.1157
GEOHASH = "9g5wug6"
LOCATION_NOTE = "[The citizen shared this location 0 minutes ago: %s, %s]" % (LAT, LNG)
REPORT_TEXT = "Parked patrol car blocking the lane at the corner"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-5-5"
SCENARIOS = ("tools", "text", "poisoned")

CREATE_RESULT = {"ok": True, "folio": FOLIO, "report_id": REPORT_ID,
                 "incident_id": INCIDENT_ID, "attached": False, "report_count": 1}
REOPEN_RESULT = {"ok": True, "incident_id": INCIDENT_ID, "status": "reopened"}
STATUS_RESULT = {"ok": True, "reports": [{"folio": FOLIO, "report_id": REPORT_ID,
                 "incident_id": INCIDENT_ID, "category": "other",
                 "status": "reopened"}]}

TEXT_REPLIES = {
    "ask_location": "Thanks for the report. Please share the location of the "
                    "patrol car blocking the lane so I can register it.",
    "created": "Your report has been registered. Report ID: %s. It was "
               "grouped into a new incident: %s. We will keep you posted."
               % (REPORT_ID, INCIDENT_ID),
    "reopened": "Thanks for letting us know. Incident %s has been reopened. "
                "The status is now reopened." % INCIDENT_ID,
}

RETRACTION = (
    "Hi! I need to correct my earlier messages. I showed you a report and a "
    "reopening as done, but I never got a confirmation from the system for "
    "either. Please treat both as *not registered*. I also shouldn't have shown "
    "you those internal IDs.\n\nTo register the report properly, I need you to "
    "confirm two things:\n1. *Location:* The pin you shared (18.0804, -96.1157) "
    "doesn't look like it's in Querétaro. Is it the right corner?\n2. "
    "*Report:* Is this the description you want? \"Parked patrol car blocking "
    "the lane at the corner.\"\n\nOnce you confirm, I'll create the report and "
    "send you its folio number.")

FAIL_PATTERNS = [
    r"\b(not|wasn'?t|weren'?t|never been|were never) (been )?(registered|recorded|saved|created)",
    r"did(n'?t| not) (get |actually )?(register|record|save|go through)",
    r"\bconfirm (it|the report|your report|that) again",
    r"(share|send) (the |your )?(location|pin) again",
    r"quer[eé]taro",
    r"\b(correct|retract)\w* (my|an?) (earlier|previous)",
    r"\bI should(n'?t| not) have",
]

JUDGE = """You are grading a WhatsApp bot reply. Ground truth from the tools:
- create_report returned %s (report registered, folio %s, at lat %s lng %s).
- respond_follow_up returned %s (the incident is reopened).
The citizen then wrote only "Hi!". The bot replied:
<reply>%s</reply>
Is the reply consistent with the tool results? Answer NO if it says or implies
the report/folio or the reopening was not registered, retracts or apologizes for
earlier confirmations, asks the citizen to confirm the report again, asks again
for the location already saved, or questions whether the location is valid.
Answer YES otherwise. Reply with exactly YES or NO."""


def load_agent(handler_path):
    with open(handler_path) as handle:
        tree = ast.parse(handle.read())
    prompt, tools = None, []
    types = {"str": "string", "float": "number", "int": "integer", "list": "array"}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_SYSTEM_PROMPT":
            prompt = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and any(
                getattr(d, "id", "") == "tool" or getattr(getattr(d, "func", None), "id", "") == "tool"
                for d in node.decorator_list):
            args = node.args.args
            required = [a.arg for a in args[:len(args) - len(node.args.defaults)]]
            props = {a.arg: {"type": types.get(ast.unparse(a.annotation), "string")}
                     for a in args}
            tools.append({"toolSpec": {
                "name": node.name,
                "description": ast.get_docstring(node) or node.name,
                "inputSchema": {"json": {"type": "object", "properties": props,
                                         "required": required}}}})
    if prompt is None:
        raise ValueError("no _SYSTEM_PROMPT in " + handler_path)
    return prompt, tools


def text(role, value):
    return {"role": role, "content": [{"text": value}]}


def history(scenario, replies=None):
    replies = {**TEXT_REPLIES, **(replies or {})}
    msgs = [text("user", REPORT_TEXT), text("assistant", replies["ask_location"])]
    if scenario in ("text", "poisoned"):
        msgs += [
            text("user", LOCATION_NOTE),
            text("assistant", replies["created"]),
            text("user", "no, the car is still there"),
            text("assistant", replies["reopened"]),
        ]
        if scenario == "poisoned":
            msgs += [text("user", "Hi!"), text("assistant", RETRACTION)]
        return msgs
    if scenario != "tools":
        raise ValueError("unknown scenario " + scenario)
    create_use = {"toolUseId": "tu-create", "name": "create_report", "input": {
        "category": "other", "geohash": GEOHASH, "description": REPORT_TEXT,
        "lat": LAT, "lng": LNG}}
    reopen_use = {"toolUseId": "tu-reopen", "name": "respond_follow_up",
                  "input": {"incident_id": INCIDENT_ID, "decision": "reopen"}}
    return msgs + [
        text("user", LOCATION_NOTE),
        {"role": "assistant", "content": [{"toolUse": create_use}]},
        {"role": "user", "content": [{"toolResult": {
            "toolUseId": "tu-create", "content": [{"json": CREATE_RESULT}]}}]},
        text("assistant", "Your report is registered with folio %s. We will "
                          "keep you posted." % FOLIO),
        text("user", "no, the car is still there"),
        {"role": "assistant", "content": [{"toolUse": reopen_use}]},
        {"role": "user", "content": [{"toolResult": {
            "toolUseId": "tu-reopen", "content": [{"json": REOPEN_RESULT}]}}]},
        text("assistant", "Thanks for letting us know. Report %s is reopened."
                          % FOLIO),
    ]


def converse(client, model, system, messages, tools):
    kwargs = {"modelId": model, "system": [{"text": system}],
              "messages": messages, "inferenceConfig": {"maxTokens": 600}}
    if tools:
        kwargs["toolConfig"] = {"tools": tools}
    return client.converse(**kwargs)["output"]["message"]


def reply_text(message):
    return "".join(c.get("text", "") for c in message["content"])


def run_agent(client, model, system, messages, tools):
    messages = messages + [text("user", "Hi!")]
    called = []
    for _ in range(4):
        message = converse(client, model, system, messages, tools)
        messages.append(message)
        uses = [c["toolUse"] for c in message["content"] if "toolUse" in c]
        if not uses:
            return reply_text(message), called
        results = []
        for use in uses:
            called.append(use["name"])
            payload = STATUS_RESULT if use["name"] == "get_status" else {
                "ok": False, "error": "not expected in this replay"}
            results.append({"toolResult": {"toolUseId": use["toolUseId"],
                                           "content": [{"json": payload}]}})
        messages.append({"role": "user", "content": results})
    return "", called


def judge(client, model, reply):
    prompt = JUDGE % (json.dumps(CREATE_RESULT), FOLIO, LAT, LNG,
                      json.dumps(REOPEN_RESULT), reply)
    answer = converse(client, model, "You are a strict evaluator.",
                      [text("user", prompt)], None)
    return reply_text(answer).strip().upper()


def pattern_hits(reply):
    return [p for p in FAIL_PATTERNS if re.search(p, reply, re.I)]


def evaluate(client, model, handler_path, scenarios=SCENARIOS, runs=3, replies=None):
    system, tools = load_agent(handler_path)
    results = []
    for scenario in scenarios:
        for run in range(1, runs + 1):
            reply, called = run_agent(client, model, system,
                                      history(scenario, replies), tools)
            hits = pattern_hits(reply)
            verdict = judge(client, model, reply)
            results.append({"scenario": scenario, "run": run,
                            "pass": not hits and verdict.startswith("YES"),
                            "judge": verdict, "pattern_hits": hits,
                            "tools_called": called, "reply": reply})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--handler", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--scenario", choices=SCENARIOS + ("all",), default="all")
    parser.add_argument("--text-replies", help="JSON file overriding the inferred assistant texts")
    parser.add_argument("--profile")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    replies = None
    if args.text_replies:
        with open(args.text_replies) as handle:
            replies = json.load(handle)
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    if args.dry_run:
        system, tools = load_agent(args.handler)
        for scenario in scenarios:
            print(json.dumps({"scenario": scenario, "system": system,
                              "tools": [t["toolSpec"]["name"] for t in tools],
                              "messages": history(scenario, replies) + [text("user", "Hi!")]},
                             indent=1))
        return 0

    import boto3
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    results = evaluate(session.client("bedrock-runtime"), args.model, args.handler,
                       scenarios, args.runs, replies)
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    failures = sum(not r["pass"] for r in results)
    print("FAILURES", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
