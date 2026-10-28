from pathlib import Path

import hcl2


POLICY_FILE = Path(__file__).parents[1] / "modules" / "agent" / "main.tf"
MODEL_ARN = "arn:aws:bedrock:*::foundation-model/${var.bedrock_model_id}"
INFERENCE_PROFILE = "${local.inference_profile_arn}"
INVOKE_ACTIONS = {
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
}


def _agent_policies():
    with POLICY_FILE.open() as policy_file:
        document = hcl2.load(policy_file)

    policies = {}
    for data_block in document["data"]:
        policy = data_block.get('"aws_iam_policy_document"')
        if policy:
            policies.update(
                {name.strip('"'): _normalize(document) for name, document in policy.items()}
            )
    return policies


def _normalize(value):
    if isinstance(value, str):
        return value.strip('"')
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in value.items()
            if key != "__is_block__"
        }
    return value


def _profile_region_statement(policy):
    return next(
        statement
        for statement in policy["statement"]
        if statement.get("sid") == "BedrockInvokeInProfileRegions"
    )


def test_agent_roles_allow_only_the_profile_model_in_profile_regions():
    policies = _agent_policies()

    for role in ("agent", "agentcore_exec"):
        statement = _profile_region_statement(policies[role])

        assert set(statement["actions"]) == INVOKE_ACTIONS
        assert statement["resources"] == [MODEL_ARN]
        assert statement["condition"] == [
            {
                "test": "ArnEquals",
                "variable": "bedrock:InferenceProfileArn",
                "values": [INFERENCE_PROFILE],
            }
        ]


def test_agent_role_model_permissions_do_not_wildcard_the_model_id():
    for policy in _agent_policies().values():
        for statement in policy.get("statement", []):
            for resource in statement.get("resources", []):
                if "foundation-model/" in resource:
                    assert resource.endswith("${var.bedrock_model_id}")
