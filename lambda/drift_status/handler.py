import boto3
import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION_TARGET", "us-east-1")
PROJECT = os.environ.get("PROJECT", "drift-detective")
ENVIRONMENTS = ["prod", "dev"]

_lambda = boto3.client("lambda", region_name=REGION)


def _invoke(function_name: str, payload: dict) -> dict:
    resp = _lambda.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload).encode("utf-8"),
    )
    return json.loads(resp["Payload"].read() or b"{}")


def lambda_handler(event, context):
    """Live drift status for the dashboard. Runs each detector, then the classifier,
    and returns an aggregated per-environment view. Exposed via a Lambda Function URL."""
    reports = {}
    for env in ENVIRONMENTS:
        try:
            reports[env] = _invoke(
                f"{PROJECT}-drift-detector-{env}",
                {"environment": env, "region": REGION},
            )
        except Exception as e:
            logger.error(f"detector {env} failed: {e}")
            reports[env] = {"environment": env, "drifts": [], "drift_count": 0,
                            "classification": "unknown", "error": str(e)}

    classification = {}
    try:
        classification = _invoke(
            f"{PROJECT}-drift-classifier",
            {"prod_report": reports.get("prod", {}), "dev_report": reports.get("dev", {})},
        )
    except Exception as e:
        logger.error(f"classifier failed: {e}")

    clf_envs = classification.get("environments", {}) if isinstance(classification, dict) else {}

    environments = {}
    for env in ENVIRONMENTS:
        r = reports.get(env, {})
        c = clf_envs.get(env, {})
        environments[env] = {
            "classification": c.get("classification") or r.get("classification", "unknown"),
            "reason": c.get("reason", ""),
            "immediate_action": c.get("immediate_action", ""),
            "drift_count": r.get("drift_count", 0),
            "drifts": r.get("drifts", []),
            "drift_summary": r.get("drift_summary", ""),
            "checked_at": r.get("checked_at", ""),
        }

    body = {
        "overall": classification.get("overall", "unknown") if isinstance(classification, dict) else "unknown",
        "summary": classification.get("summary", "") if isinstance(classification, dict) else "",
        "environments": environments,
    }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
