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

SYSTEM_PROMPT = """You generate Python (boto3) remediation code for AWS Terraform drift.

At runtime, three names are ALREADY defined in scope:
- `ec2`     : a boto3 EC2 client for the correct region
- `drifts`  : a list of drift findings (dicts)
- `results` : an empty list you must append one dict to per remediation action

Each drift dict has keys: resource_type, resource_id, attribute, desired, actual.
Generate Python statements that iterate `drifts` and remediate each to restore the
desired state. Handle these cases:
- resource_type 'aws_instance', attribute 'instance_type': if the instance is not
  stopped, ec2.stop_instances then wait with ec2.get_waiter('instance_stopped'); then
  ec2.modify_instance_attribute(InstanceId=..., InstanceType={'Value': desired}); then
  ec2.start_instances.
- resource_type 'aws_instance', attribute 'state': desired 'running' -> ec2.start_instances;
  desired 'stopped' -> ec2.stop_instances.
- resource_type 'aws_security_group', attribute 'ingress_rule_count': describe the group
  and ec2.revoke_security_group_ingress for all existing IpPermissions.

Rules:
- Output RAW Python only — NO markdown fences, NO prose, NO function/def, NO imports.
- Use ONLY `ec2`, `drifts`, `results` (boto3 is NOT importable; `ec2` is provided).
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
