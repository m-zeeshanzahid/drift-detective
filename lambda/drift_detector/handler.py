import boto3
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ─── Load the state file from S3 (Terraform .tfstate or the legacy custom schema) ──
def load_state(bucket: str, key: str, region: str) -> dict:
    s3 = boto3.client('s3', region_name=region)
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj['Body'].read())


def iter_resources(state: dict):
    """Yield (resource_type, resource_name, attributes) for managed resources.
    Supports Terraform tfstate v4 (resources: [...]) and the legacy custom schema
    (resources: {ec2_instances: {...}, security_groups: {...}})."""
    res = state.get('resources')

    # Terraform .tfstate (v4): resources is a list of {mode,type,name,instances[]}
    if isinstance(res, list):
        for r in res:
            if r.get('mode') and r.get('mode') != 'managed':
                continue
            rtype = r.get('type', '')
            rname = r.get('name', '')
            for inst in r.get('instances', []):
                yield rtype, rname, inst.get('attributes', {}) or {}
        return

    # Legacy custom schema
    if isinstance(res, dict):
        for iid, attrs in (res.get('ec2_instances', {}) or {}).items():
            a = dict(attrs)
            a.setdefault('id', iid)
            yield 'aws_instance', iid, a
        for sgid, attrs in (res.get('security_groups', {}) or {}).items():
            a = dict(attrs)
            a.setdefault('id', sgid)
            # legacy uses ingress_rules; normalize to tfstate-style "ingress"
            a.setdefault('ingress', a.get('ingress_rules', []))
            yield 'aws_security_group', sgid, a
        for name, attrs in (res.get('s3_buckets', {}) or {}).items():
            a = dict(attrs)
            a.setdefault('bucket', name)
            yield 'aws_s3_bucket', name, a


# ─── Per-type drift checks (extend this dispatch to support more resource types) ──
def check_instance(rname, attrs, ec2):
    iid = attrs.get('id')
    if not iid:
        return []
    try:
        resp = ec2.describe_instances(InstanceIds=[iid])
        inst = resp['Reservations'][0]['Instances'][0]
    except Exception as e:
        logger.warning(f"describe_instances {iid}: {e}")
        return [{"resource_type": "aws_instance", "resource_name": rname, "resource_id": iid,
                 "attribute": "existence", "desired": "present", "actual": "missing", "severity": "critical"}]
    drifts = []
    actual_type = inst.get('InstanceType')
    actual_state = inst.get('State', {}).get('Name')
    desired_type = attrs.get('instance_type')
    desired_state = attrs.get('instance_state')  # tfstate aws_instance computed attr
    if desired_type and actual_type != desired_type:
        drifts.append({"resource_type": "aws_instance", "resource_name": rname, "resource_id": iid,
                       "attribute": "instance_type", "desired": desired_type, "actual": actual_type, "severity": "suspicious"})
    if desired_state and actual_state and actual_state != desired_state:
        drifts.append({"resource_type": "aws_instance", "resource_name": rname, "resource_id": iid,
                       "attribute": "state", "desired": desired_state, "actual": actual_state, "severity": "critical"})
    return drifts


def check_security_group(rname, attrs, ec2):
    sgid = attrs.get('id')
    if not sgid:
        return []
    try:
        sg = ec2.describe_security_groups(GroupIds=[sgid])['SecurityGroups'][0]
    except Exception as e:
        logger.warning(f"describe_security_groups {sgid}: {e}")
        return [{"resource_type": "aws_security_group", "resource_name": rname, "resource_id": sgid,
                 "attribute": "existence", "desired": "present", "actual": "missing", "severity": "critical"}]
    desired_ingress = attrs.get('ingress', []) or []
    actual_count = len(sg.get('IpPermissions', []))
    desired_count = len(desired_ingress)
    if actual_count != desired_count:
        return [{"resource_type": "aws_security_group", "resource_name": rname, "resource_id": sgid,
                 "attribute": "ingress_rule_count", "desired": desired_count, "actual": actual_count,
                 "severity": "critical",
                 "detail": f"Security group has {actual_count} ingress rules, state file expects {desired_count}"}]
    return []


def check_s3_bucket(rname, attrs, region):
    name = attrs.get('bucket') or attrs.get('id')
    if not name:
        return []
    s3 = boto3.client('s3', region_name=region)
    try:
        s3.head_bucket(Bucket=name)
        return []
    except Exception:
        return [{"resource_type": "aws_s3_bucket", "resource_name": rname, "resource_id": name,
                 "attribute": "existence", "desired": "present", "actual": "missing", "severity": "critical"}]


def format_drift_summary(drifts: list) -> str:
    if not drifts:
        return "No drift detected."
    return "\n".join(
        f"- [{d['resource_type']}] {d.get('resource_name', d['resource_id'])} ({d['resource_id']}): "
        f"{d['attribute']} — state file expects '{d['desired']}', actual '{d['actual']}'"
        for d in drifts
    )


def lambda_handler(event, context):
    environment = os.environ.get('ENVIRONMENT', event.get('environment', 'default'))
    region      = os.environ.get('AWS_REGION_TARGET', event.get('region', 'us-east-1'))
    # Configurable state-file location — point this at ANY tfstate in S3.
    bucket = event.get('state_bucket') or os.environ.get('STATE_BUCKET')
    key    = event.get('state_key') or os.environ.get('STATE_KEY', 'terraform.tfstate')

    logger.info(f"Drift scan: env={environment} region={region} state=s3://{bucket}/{key}")

    try:
        state = load_state(bucket, key, region)
    except Exception as e:
        return {"environment": environment, "region": region, "status": "error",
                "error": f"Could not read state s3://{bucket}/{key}: {e}",
                "drift_count": 0, "drifts": [], "has_drift": False, "classification": "error"}

    ec2 = boto3.client('ec2', region_name=region)
    drifts = []
    unsupported = set()

    for rtype, rname, attrs in iter_resources(state):
        if rtype == 'aws_instance':
            drifts.extend(check_instance(rname, attrs, ec2))
        elif rtype == 'aws_security_group':
            drifts.extend(check_security_group(rname, attrs, ec2))
        elif rtype == 'aws_s3_bucket':
            drifts.extend(check_s3_bucket(rname, attrs, region))
        else:
            unsupported.add(rtype)

    has_critical   = any(d.get('severity') == 'critical' for d in drifts)
    has_suspicious = any(d.get('severity') == 'suspicious' for d in drifts)
    classification = "critical" if has_critical else "suspicious" if (has_suspicious or drifts) else "safe"

    result = {
        "environment": environment,
        "region": region,
        "state_source": f"s3://{bucket}/{key}",
        "has_drift": len(drifts) > 0,
        "drift_count": len(drifts),
        "classification": classification,
        "drifts": drifts,
        "drift_summary": format_drift_summary(drifts),
        "unsupported_types": sorted(unsupported),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Drift scan complete: {json.dumps(result)}")
    return result
