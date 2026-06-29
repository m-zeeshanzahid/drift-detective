import boto3
import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BEDROCK_MODEL_ID = os.environ.get(
    'BEDROCK_MODEL_ID',
    'us.anthropic.claude-haiku-4-5-20251001-v1:0'
)
BEDROCK_REGION = os.environ.get('BEDROCK_REGION', 'us-east-1')

SYSTEM_PROMPT = """You generate Python (boto3) remediation code for AWS infrastructure drift.
The drift was found by comparing live AWS against a Terraform state file (the desired state).
Your code must change the live resources so they match the state file's desired values.

At runtime, these names are ALREADY defined in scope:
- `client`  : a function — call `client('ec2')`, `client('s3')`, `client('iam')`, etc. to get
              a boto3 client for ANY service in the correct region.
- `drifts`  : a list of drift findings (dicts)
- `results` : an empty list you must append one dict to per remediation action

Each drift dict has keys: resource_type, resource_id, attribute, desired, actual
(and sometimes resource_name, detail). Generate Python that iterates `drifts` and
remediates EACH one to the desired value — for ANY AWS resource type, not just the
examples below. Pick the correct boto3 service/API for each resource_type.

Reference patterns (apply the same idea to other types/attributes as needed):
- aws_instance / instance_type: ec2=client('ec2'); stop the instance, wait
  get_waiter('instance_stopped'), modify_instance_attribute(InstanceType={'Value':desired}),
  start_instances.
- aws_instance / state: desired 'running' -> start_instances; 'stopped' -> stop_instances.
- aws_security_group / ingress_rule_count: describe_security_groups, then
  revoke_security_group_ingress for all current IpPermissions (state file expects fewer).
- aws_s3_bucket / existence: create_bucket to restore a missing bucket.

Rules:
- Output RAW Python only — NO markdown fences, NO prose, NO def/function, NO imports.
- Get clients ONLY via `client('<service>')`. Do NOT import boto3 (use `client`).
- Wrap each remediation in try/except. On success append
  {"resource_id": ..., "attribute": ..., "action": "<verb>", "status": "success"}.
  On failure append {"resource_id": ..., "status": "error", "error": str(e)}.
- Never use open/exec/eval/os/subprocess/__import__."""


def lambda_handler(event, context):
    drifts = event.get('drifts', [])
    region = event.get('region', 'us-east-1')

    bedrock = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
    user_message = f"Target region: {region}\nDrift findings to remediate:\n{json.dumps(drifts, indent=2)}"

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}]
    })

    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    raw = json.loads(response['body'].read())['content'][0]['text'].strip()

    # Strip markdown fences if the model added them.
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("python"):
            raw = raw[len("python"):]
    code = raw.strip()

    logger.info(f"Generated remediation code:\n{code}")
    return {"code": code, "drift_count": len(drifts)}
