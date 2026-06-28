import boto3
import json
import os
import builtins as _builtins
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROJECT = os.environ.get('PROJECT', 'drift-detective')

# Restricted builtins exposed to the AI-generated remediation code.
# (No __import__/open/exec/eval/os/subprocess — limits the blast radius of generated code.)
_SAFE_NAMES = [
    'len', 'range', 'str', 'int', 'float', 'bool', 'dict', 'list', 'tuple', 'set',
    'enumerate', 'zip', 'print', 'isinstance', 'getattr', 'hasattr', 'sorted',
    'min', 'max', 'sum', 'any', 'all', 'map', 'filter', 'reversed', 'repr',
    'Exception', 'KeyError', 'ValueError', 'TypeError', 'IndexError', 'AttributeError',
]
SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _SAFE_NAMES}


def lambda_handler(event, context):
    """Auto-remediator: fetches current drift from the detector, asks the code-generator
    Lambda to write boto3 remediation code in real time, then executes that code.
    No remediation logic is hardcoded here."""
    environment = os.environ.get('ENVIRONMENT', event.get('environment', 'unknown'))
    region      = os.environ.get('AWS_REGION_TARGET', event.get('region', 'us-east-1'))
    approved_by = event.get('approved_by', 'superplane-workflow')
    if approved_by in (None, '', '<nil>'):
        approved_by = 'superplane-workflow'

    lam = boto3.client('lambda', region_name=region)

    # 1. Get the current drift findings from this environment's detector.
    try:
        det = lam.invoke(
            FunctionName=f"{PROJECT}-drift-detector-{environment}",
            Payload=json.dumps({"environment": environment, "region": region}).encode('utf-8'),
        )
        report = json.loads(det['Payload'].read() or b'{}')
        drifts = report.get('drifts', [])
    except Exception as e:
        logger.error(f"Failed to fetch drift from detector: {e}")
        return {"environment": environment, "status": "error", "error": f"detector: {e}",
                "remediation_results": [], "success_count": 0, "error_count": 1}

    if not drifts:
        logger.info("No drift to remediate.")
        return {"environment": environment, "region": region, "status": "no_drift",
                "remediation_results": [], "success_count": 0, "error_count": 0}

    # 2. Ask the code-generator Lambda to write remediation code in real time.
    try:
        gen = lam.invoke(
            FunctionName=f"{PROJECT}-code-generator",
            Payload=json.dumps({"drifts": drifts, "region": region}).encode('utf-8'),
        )
        code = json.loads(gen['Payload'].read() or b'{}').get('code', '')
    except Exception as e:
        logger.error(f"Code generation failed: {e}")
        return {"environment": environment, "status": "error", "error": f"code-generator: {e}",
                "remediation_results": [], "success_count": 0, "error_count": 1}

    if not code:
        return {"environment": environment, "status": "error", "error": "no code generated",
                "remediation_results": [], "success_count": 0, "error_count": 1}

    # 3. Execute the generated code in a restricted namespace.
    ec2 = boto3.client('ec2', region_name=region)
    results = []
    namespace = {"__builtins__": SAFE_BUILTINS, "ec2": ec2, "drifts": drifts, "results": results}
    try:
        exec(code, namespace)  # noqa: S102 — intentional: runs AI-generated remediation
        results = namespace.get("results", results)
    except Exception as e:
        logger.error(f"Generated remediation code failed: {e}\nCODE:\n{code}")
        return {"environment": environment, "region": region, "status": "execution_error",
                "error": str(e), "generated_code": code,
                "remediation_results": results, "success_count": 0,
                "error_count": 1}

    return {
        "environment": environment,
        "region": region,
        "approved_by": approved_by,
        "generated_code": code,
        "remediation_results": results,
        "success_count": len([r for r in results if r.get('status') == 'success']),
        "error_count":   len([r for r in results if r.get('status') == 'error']),
    }
