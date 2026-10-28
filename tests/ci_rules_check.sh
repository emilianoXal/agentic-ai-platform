#!/usr/bin/env bash
# Contract check for the GitLab CI YAML: workflow switch, shared resource_group
# on plan/apply, and -lock-timeout on terraform commands that take the state lock.
set -euo pipefail

CI_FILE="${1:-.gitlab-ci.yml}"

if [[ ! -f "$CI_FILE" ]]; then
  echo "ci_rules_check: missing file: $CI_FILE" >&2
  exit 1
fi

python3 - "$CI_FILE" <<'PY'
import shlex
import sys

import yaml


LOCK_TAKING = {"plan", "apply", "destroy", "untaint", "refresh", "import"}
REQUIRED_JOBS = ("terraform:plan", "terraform:apply")
LOCK_TIMEOUT = "5m"


class GitLabLoader(yaml.SafeLoader):
    pass


def _unknown_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


GitLabLoader.add_multi_constructor("!", _unknown_tag)


def fail(msg):
    print(f"ci_rules_check: {msg}", file=sys.stderr)
    sys.exit(1)


def load_ci(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=GitLabLoader)
    if not isinstance(data, dict):
        fail(f"{path} is not a YAML mapping")
    return data


def script_lines(script):
    if script is None:
        return []
    if isinstance(script, str):
        return script.splitlines()
    if isinstance(script, list):
        lines = []
        for item in script:
            lines.extend(script_lines(item))
        return lines
    return []


def tokenize(line):
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.split()


def lock_commands(lines):
    cmds = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = tokenize(line)
        if len(tokens) >= 2 and tokens[0] == "terraform" and tokens[1] in LOCK_TAKING:
            cmds.append(tokens)
    return cmds


def lock_timeout_value(tokens):
    for i, tok in enumerate(tokens):
        if tok.startswith("-lock-timeout="):
            return tok.split("=", 1)[1]
        if tok == "-lock-timeout" and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def workflow_switch(rules):
    allow_mr = False
    skip_when_open = False
    allow_branch = False
    allow_tag = False
    if not isinstance(rules, list) or not rules:
        return allow_mr, skip_when_open, allow_branch, allow_tag
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        cond = str(rule.get("if") or "")
        when = rule.get("when")
        if "merge_request_event" in cond and when != "never":
            allow_mr = True
        if "CI_OPEN_MERGE_REQUESTS" in cond and when == "never":
            skip_when_open = True
        if (
            "CI_COMMIT_BRANCH" in cond
            and "CI_OPEN_MERGE_REQUESTS" not in cond
            and when != "never"
        ):
            allow_branch = True
        if "CI_COMMIT_TAG" in cond and when != "never":
            allow_tag = True
    return allow_mr, skip_when_open, allow_branch, allow_tag


def main(path):
    data = load_ci(path)

    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        fail("workflow mapping is missing")
    rules = workflow.get("rules")
    allow_mr, skip_when_open, allow_branch, allow_tag = workflow_switch(rules)
    if not allow_mr:
        fail("workflow:rules must allow merge_request_event pipelines")
    if not skip_when_open:
        fail("workflow:rules must skip branch pipelines while an MR is open")
    if not allow_branch:
        fail("workflow:rules must still allow branch pipelines (main)")
    if not allow_tag:
        fail("workflow:rules must still allow tag pipelines")

    groups = {}
    for name in REQUIRED_JOBS:
        job = data.get(name)
        if not isinstance(job, dict):
            fail(f"job {name} is missing")
        group = job.get("resource_group")
        if not isinstance(group, str) or not group.strip():
            fail(f"{name} is missing resource_group")
        groups[name] = group.strip()
        cmds = lock_commands(script_lines(job.get("script")))
        if not cmds:
            fail(f"{name} has no terraform command that takes the state lock")
        for tokens in cmds:
            value = lock_timeout_value(tokens)
            if value is None:
                fail(f"{name} terraform {tokens[1]} is missing -lock-timeout")
            if value != LOCK_TIMEOUT:
                fail(
                    f"{name} terraform {tokens[1]} -lock-timeout is {value!r}, expected {LOCK_TIMEOUT!r}"
                )

    values = set(groups.values())
    if len(values) != 1:
        fail(f"resource_group values differ: {groups}")

    apply_job = data["terraform:apply"]
    environment = apply_job.get("environment")
    env_name = None
    if isinstance(environment, str):
        env_name = environment
    elif isinstance(environment, dict):
        env_name = environment.get("name")
    if env_name != "dev":
        fail("terraform:apply must declare environment dev")

    saved_plan = False
    for tokens in lock_commands(script_lines(apply_job.get("script"))):
        if tokens[1] == "apply" and "tfplan" in tokens:
            saved_plan = True
    if not saved_plan:
        fail("terraform:apply must apply the saved tfplan from the same pipeline")

    print(
        "ci_rules_check: ok "
        f"resource_group={next(iter(values))} lock-timeout={LOCK_TIMEOUT}"
    )


if __name__ == "__main__":
    main(sys.argv[1])
PY
