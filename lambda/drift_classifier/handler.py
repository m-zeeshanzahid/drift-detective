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

SYSTEM_PROMPT = """You are a Terraform infrastructure drift classifier for a DevOps team.
Classify each environment's drift as one of three categories:

SAFE: No drift, or trivial expected changes (timestamps, metadata).
SUSPICIOUS: Unexpected resource changes needing review but not immediately dangerous
  (instance type change, tag modification, scaling changes).
CRITICAL: Security-relevant or stability-threatening changes (security group ingress
  rules added, IAM policy changes, instance stopped unexpectedly, resources deleted).

Respond in JSON only. No prose. No markdown fences. Raw JSON only. Structure:
{
  "environments": {
    "prod": {"classification": "safe|suspicious|critical", "reason": "brief reason", "immediate_action": "what to do"},
    "dev":  {"classification": "...", "reason": "...", "immediate_action": "..."}
  },
  "overall": "safe|suspicious|critical",
  "summary": "2-3 sentence executive summary for the on-call engineer"
}"""


def lambda_handler(event, context):
    prod_report = event.get('prod_report', {})
    dev_report  = event.get('dev_report', {})

    user_message = f"""Analyze these drift reports from our AWS environments:

PROD (us-east-1):
{json.dumps(prod_report, indent=2)}

DEV (us-east-1):
{json.dumps(dev_report, indent=2)}"""

    bedrock = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    })

    raw_text = ""
    try:
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body
        )
        response_body = json.loads(response['body'].read())
        raw_text = response_body['content'][0]['text'].strip()

        # Strip markdown fences if model adds them despite instructions
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        classification = json.loads(raw_text)
        logger.info(f"Classification result: {json.dumps(classification)}")

        return {
            "statusCode": 200,
            "classification": classification,
            "overall": classification.get("overall", "unknown"),
            "summary": classification.get("summary", ""),
            "environments": classification.get("environments", {})
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Bedrock response as JSON: {e}. Raw: {raw_text}")
        # Fail safe — treat as suspicious so humans review
        return {
            "statusCode": 200,
            "classification": {},
            "overall": "suspicious",
            "summary": "Classification parsing failed — manual review required.",
            "environments": {
                "prod": {"classification": "suspicious", "reason": "parse error", "immediate_action": "review manually"},
                "dev":  {"classification": "suspicious", "reason": "parse error", "immediate_action": "review manually"}
            }
        }

    except Exception as e:
        logger.error(f"Bedrock invocation failed: {e}")
        raise
